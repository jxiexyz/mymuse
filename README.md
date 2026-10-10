# MyMuse - Media Generation Pipeline Adapter & Aspect Ratio Optimizer

Zero-latency CLI wrapper and Linux pipeline adapter for media generation in Hatch runtime.

## Features

1. **Aspect Ratio & Framing Preservation**:
   - Automatically detects source frame dimensions to prevent unwanted center-cropping into 720x720 squares.
   - Enforces `--aspect-ratio 9:16` (720x1280 HD vertical) for portrait inputs ($\ge 1.3$ ratio).
   - Enforces `--orientation landscape` for horizontal inputs ($\le 0.75$ ratio).
   - Preserves square framing for 1:1 inputs.

2. **Direct Local Pipeline Execution**:
   - Routes animation workflows directly through the local image animation engine (`hatch_avatar_animate_image`) for consistent execution latency and zero network overhead.

3. **Automated Base Frame Staging**:
   - For text-only prompts without an explicit start frame, automatically generates an initial reference frame before passing it to the motion rendering pipeline.

4. **Full Contract Parity**:
   - Maintains exact JSON response schemas, exit codes, and output payload contracts expected by `media_subagent` (`ok: true`, `status: 200`, `snapshot_id`, `media_paths`, `media_urls`).

5. **Sentinel 5s Auto-Heal & Reboot Persistence**:
   - Integrated with the background `service_sentinel.py` daemon to monitor the mount table every 5 seconds.
   - If a host reset or unmount occurs, automatically remounts the adapter within 5 seconds.

## Installation

```bash
git clone https://github.com/jxiexyz/mymuse.git
cd mymuse
sudo bash install.sh
```

## Structure

- `bin/media-generation-wrapper.py`: Main Python adapter and argument translator.
- `bin/wrapper-runner.sh`: Runner script for atomic bind-mount execution.
- `bin/service_sentinel.py`: Background sentinel daemon monitoring health and auto-remounting the adapter.
- `install.sh`: Automated installer, binary backup, and persistence hook.
