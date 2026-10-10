#!/usr/bin/env python3
"""
service_sentinel.py — Realtime Health Detector & Auto-Restart Daemon
Monitors:
  1. 9Router (HTTP health on port 20128) — auto-restart via systemd
  2. Chrome CDP (port 9222) — auto-recover via ensure-chrome.sh
  3. hermes-gateway (unit file exists + systemctl is-active) — auto-recover via ensure-gateway.sh
  4. Proxy relay (TCP 127.0.0.1:18888, Telegram's lifeline) — auto-restart directly
Runs continuously as systemd daemon, polling every 5 seconds.
"""

import os
import re
import sys
import time
import signal
import socket
import logging
import subprocess
import urllib.request
import urllib.error

# Configure paths
LOG_DIR = "/home/hatch/.hermes/logs"
LOG_FILE = os.path.join(LOG_DIR, "sentinel.log")
MAX_LOG_SIZE = 2 * 1024 * 1024  # 2MB

os.makedirs(LOG_DIR, exist_ok=True)

# Truncate log if too big on startup
if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_SIZE:
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
        with open(LOG_FILE, "w") as f:
            f.writelines(lines[-2000:])
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SENTINEL] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

running = True

def handle_signal(sig, frame):
    global running
    logging.info(f"Received signal {sig}, stopping sentinel gracefully...")
    running = False

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

def run_cmd(cmd, timeout=10):
    try:
        res = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -2, "", str(e)

def check_9router_health():
    """Probe 9router HTTP endpoint on 127.0.0.1:20128"""
    url = "http://127.0.0.1:20128/v1/models"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Sentinel/1.0"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return resp.status == 200
    except Exception:
        return False

def check_chrome_health():
    """Check Chrome CDP port 9222"""
    url = "http://127.0.0.1:9222/json/version"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Sentinel/1.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False

def restart_9router():
    logging.warning("Initiating 9router restart...")
    # First try systemctl restart
    code, _, err = run_cmd("systemctl restart 9router.service", timeout=10)
    time.sleep(2)
    if check_9router_health():
        logging.info("9router restarted successfully via systemd.")
        return True
    
    # If still not healthy, kill any stale node/9router and restart
    logging.warning("9router not responding after systemctl restart, force killing stale process...")
    run_cmd("pkill -9 -f '[9]router'", timeout=5)
    time.sleep(1)
    run_cmd("systemctl restart 9router.service", timeout=10)
    
    # Poll for recovery
    for _ in range(8):
        time.sleep(1)
        if check_9router_health():
            logging.info("9router recovered and responding on port 20128.")
            return True
            
    logging.error("9router failed to recover after force restart!")
    return False

def restart_chrome():
    logging.warning("Chrome CDP is down, executing ensure-chrome.sh...")
    script = "/home/hatch/workspace/bin/ensure-chrome.sh"
    if os.path.exists(script):
        run_cmd(f"bash {script}", timeout=15)
        time.sleep(2)
        if check_chrome_health():
            logging.info("Chrome CDP recovered successfully.")
            return True
    return False

def check_hermes_gateway():
    """Check hermes-gateway unit file exists and service is active.
    Catches both failure modes: dead process AND vanished unit file."""
    unit = "/etc/systemd/system/hermes-gateway.service"
    if not os.path.exists(unit):
        return False
    _, out, _ = run_cmd("systemctl is-active hermes-gateway", timeout=5)
    return out.strip() == "active"

def recover_hermes_gateway():
    logging.warning("hermes-gateway down or unit file missing, running ensure-gateway.sh...")
    script = "/home/hatch/workspace/hermes-gateway/ensure-gateway.sh"
    if os.path.exists(script):
        # Only runs when the service is NOT active, so this never restarts a healthy gateway.
        run_cmd(f"bash {script}", timeout=180)
        time.sleep(3)
        if check_hermes_gateway():
            logging.info("hermes-gateway recovered successfully.")
            return True
        logging.error("hermes-gateway failed to recover after ensure-gateway.sh!")
    return False

def check_relay():
    """Check proxy relay TCP port 127.0.0.1:18888 (Telegram's lifeline)."""
    try:
        s = socket.create_connection(("127.0.0.1", 18888), timeout=3)
        s.close()
        return True
    except OSError:
        return False

def restart_relay():
    logging.warning("Proxy relay (127.0.0.1:18888) is down, restarting...")
    # Upstream proxy URL (with auth) lives in the hermes-gateway unit file,
    # injected by ensure-gateway.sh. Fall back to our own env.
    https_proxy = ""
    try:
        with open("/etc/systemd/system/hermes-gateway.service") as f:
            for line in f:
                m = re.match(r'Environment="HTTPS_PROXY=([^"]+)"', line)
                if m:
                    https_proxy = m.group(1)
                    break
    except OSError:
        pass
    if not https_proxy:
        https_proxy = os.environ.get("HTTPS_PROXY", "") or os.environ.get("https_proxy", "")
    if not https_proxy:
        logging.error("Cannot restart relay: no HTTPS_PROXY available")
        return False
    env = dict(os.environ, HTTPS_PROXY=https_proxy, https_proxy=https_proxy)
    try:
        with open("/home/hatch/workspace/bin/chrome-persistent.log", "a") as lf:
            subprocess.Popen(
                ["python3", "/home/hatch/workspace/bin/proxy-relay.py"],
                stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                env=env, start_new_session=True,
            )
    except Exception as e:
        logging.error(f"Failed to spawn proxy relay: {e}")
        return False
    time.sleep(2)
    if check_relay():
        logging.info("Proxy relay restarted successfully.")
        return True
    logging.error("Proxy relay failed to restart!")
    return False

def check_and_ensure_media_mount():
    """Ensure /opt/hatch/bin/media-generation is bind-mounted to our wrapper."""
    target = "/opt/hatch/bin/media-generation"
    runner = "/home/hatch/workspace/bin/wrapper-runner.sh"
    real_bin = "/home/hatch/workspace/bin/real/media-generation"
    if not (os.path.exists(target) and os.path.exists(runner) and os.path.exists(real_bin)):
        return
    code, out, _ = run_cmd("mount", timeout=3)
    if target not in out:
        logging.warning("media-generation bind mount missing, mounting now...")
        run_cmd(f"mount --bind {runner} {target}", timeout=5)


def main():
    logging.info("Service Sentinel started. Monitoring 9Router (port 20128), Chrome CDP (port 9222), hermes-gateway, proxy relay (18888).")
    
    fail_9router = 0
    fail_chrome = 0
    fail_hermes = 0
    fail_relay = 0
    last_heartbeat = time.time()
    
    while running:
        try:
            # 1. Check 9Router
            if check_9router_health():
                if fail_9router > 0:
                    logging.info(f"9router back online (cleared {fail_9router} failures).")
                fail_9router = 0
            else:
                fail_9router += 1
                logging.warning(f"9router health check failed (consecutive: {fail_9router})")
                if fail_9router >= 2:
                    restart_9router()
                    fail_9router = 0

            # 2. Check Chrome CDP (skip if intentionally disabled via kill-switch)
            if os.path.exists("/home/hatch/workspace/bin/.chrome-disabled"):
                fail_chrome = 0
            elif check_chrome_health():
                fail_chrome = 0
            else:
                fail_chrome += 1
                if fail_chrome >= 4:
                    restart_chrome()
                    fail_chrome = 0

            # 3. Check hermes-gateway
            if check_hermes_gateway():
                if fail_hermes > 0:
                    logging.info(f"hermes-gateway back online (cleared {fail_hermes} failures).")
                fail_hermes = 0
            else:
                fail_hermes += 1
                logging.warning(f"hermes-gateway check failed (consecutive: {fail_hermes})")
                if fail_hermes >= 2:
                    recover_hermes_gateway()
                    fail_hermes = 0

            # 4. Check proxy relay (Telegram's lifeline)
            if check_relay():
                if fail_relay > 0:
                    logging.info(f"Proxy relay back online (cleared {fail_relay} failures).")
                fail_relay = 0
            else:
                fail_relay += 1
                logging.warning(f"Proxy relay check failed (consecutive: {fail_relay})")
                if fail_relay >= 2:
                    restart_relay()
                    fail_relay = 0

            # 5. Check media-generation bind mount
            check_and_ensure_media_mount()

            # Heartbeat log every 15 minutes
            now = time.time()
            if now - last_heartbeat >= 900:
                logging.info("Heartbeat: All monitored services (9Router, Chrome CDP, hermes-gateway, proxy relay) are healthy.")
                last_heartbeat = now

        except Exception as e:
            logging.error(f"Unexpected error in sentinel loop: {e}")

        # Sleep interval: 5 seconds
        for _ in range(5):
            if not running:
                break
            time.sleep(1)

    logging.info("Service Sentinel stopped.")

if __name__ == "__main__":
    main()
