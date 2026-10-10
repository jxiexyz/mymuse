#!/usr/bin/env bash
set -e

# ==============================================================================
# MyMuse - Media Generation Pipeline Adapter & Aspect Ratio Optimizer
# ==============================================================================

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="/home/hatch/workspace/bin"
REAL_DIR="$BIN_DIR/real"
TARGET="/opt/hatch/bin/media-generation"
RUNNER="$BIN_DIR/wrapper-runner.sh"
WRAPPER="$BIN_DIR/media-generation-wrapper.py"
SENTINEL="$BIN_DIR/service_sentinel.py"

echo "==> Setting up MyMuse media-generation adapter..."

mkdir -p "$BIN_DIR"
mkdir -p "$REAL_DIR"

# 1. Unmount existing bind mount first if present (prevents backing up wrapper)
if mount | grep -q "$TARGET"; then
  echo "==> Unmounting existing bind mount..."
  umount "$TARGET" || true
fi

# 2. Backup original binary if not already backed up
if [ -f "$TARGET" ] && [ ! -f "$REAL_DIR/media-generation" ]; then
  echo "==> Backing up original binary to $REAL_DIR/media-generation..."
  cp "$TARGET" "$REAL_DIR/media-generation"
  chmod +x "$REAL_DIR/media-generation"
fi

# 3. Copy wrapper scripts
echo "==> Installing wrapper scripts..."
cp "$REPO_DIR/bin/media-generation-wrapper.py" "$WRAPPER"
chmod +x "$WRAPPER"

cp "$REPO_DIR/bin/wrapper-runner.sh" "$RUNNER"
chmod +x "$RUNNER"

if [ -f "$REPO_DIR/bin/service_sentinel.py" ]; then
  echo "==> Installing updated Sentinel watchdog with 5s auto-remount..."
  cp "$REPO_DIR/bin/service_sentinel.py" "$SENTINEL"
  chmod +x "$SENTINEL"
  if systemctl is-active service-sentinel.service >/dev/null 2>&1; then
    systemctl restart service-sentinel.service || true
  fi
fi

# 4. Mount bind wrapper onto target binary
echo "==> Mounting media-generation wrapper to $TARGET..."
mount --bind "$RUNNER" "$TARGET"

# 5. Integrate into ensure-gateway.sh if present
ENSURE_SCRIPT="/home/hatch/workspace/hermes-gateway/ensure-gateway.sh"
if [ -f "$ENSURE_SCRIPT" ] && ! grep -q "ENSURE MEDIA-GENERATION WRAPPER MOUNT" "$ENSURE_SCRIPT"; then
  echo "==> Adding auto-mount hook to $ENSURE_SCRIPT..."
  cat << 'EOF' >> "$ENSURE_SCRIPT"

# ==============================================================================
# 8. ENSURE MEDIA-GENERATION WRAPPER MOUNT
# ==============================================================================
RUNNER=/home/hatch/workspace/bin/wrapper-runner.sh
TARGET=/opt/hatch/bin/media-generation
REAL_DIR=/home/hatch/workspace/bin/real
REAL_BIN="$REAL_DIR/media-generation"

if [ -f "$TARGET" ] && [ -x "$RUNNER" ]; then
  mkdir -p "$REAL_DIR"
  if ! mount | grep -q "$TARGET"; then
    if [ ! -f "$REAL_BIN" ]; then
      cp "$TARGET" "$REAL_BIN"
      chmod +x "$REAL_BIN"
    fi
    mount --bind "$RUNNER" "$TARGET"
    echo "MEDIA_GENERATION_MOUNTED"
  else
    echo "MEDIA_GENERATION_ALREADY_MOUNTED"
  fi
fi
EOF
fi

echo "==> Done! Adapter successfully installed and active."
