# MyMuse - Media Generation Region Bypass & Aspect Ratio Optimizer

Zero-latency CLI wrapper & Linux mount-bind interceptor to bypass Meta's 403 `video_not_available` country/region rollout gate in Muse VM and prevent unwanted center-cropping.

## Problem Statement

1. **Meta Region Gate (403 `video_not_available`)**:
   When an account is connected to WhatsApp (e.g. `+62` / Indonesia), Meta tags the user account metadata as non-US/Canada. Calling `media.generate_video` via the standard `media_subagent` entry point returns:
   ```json
   {
     "downstream_status": 403,
     "error_code": "video_not_available",
     "error_detail": "Video generation isn't available in your country or region."
   }
   ```
2. **Crop & Degradation**:
   The avatar animation engine defaults to `square (720x720)` when orientation parameters are missing, center-cropping vertical portrait (9:16) frames into squares and reducing bitrate.

## How the Bypass Works

- **Direct Pipeline Interception**: Meta only enforces the region gate at the public `media_subagent` endpoint. The internal animation pipeline (`hatch_avatar_animate_image`) running inside the VM is **not region-restricted**.
- **Transparent Linux Bind-Mount**: The wrapper is mounted directly over `/opt/hatch/bin/media-generation` using `mount --bind`. Muse calls `/opt/hatch/bin/media-generation` as normal without knowing it is running through a wrapper.
- **Auto Aspect-Ratio Detection**: The wrapper inspects the input start-frame image dimensions:
  - Height > Width (>= 1.3 ratio) -> Sets `--aspect-ratio 9:16` (720x1280 HD vertical, no crop).
  - Width > Height (<= 0.75 ratio) -> Sets `--orientation landscape`.
  - Square -> Sets `--orientation square`.
- **Text-to-Video Fallback**: If Muse provides only text without an image, the wrapper first generates a base frame image (which is not region blocked), then passes it to the animation pipeline.
- **Exact Contract Emulation**: Emulates the exact JSON schema, exit code, and `media_subagent` output fields Muse expects (`ok: true`, `status: 200`, `snapshot_id`, `media_paths`, `media_urls`, etc.).

## Installation

```bash
git clone https://github.com/jxiexyz/mymuse.git
cd mymuse
sudo bash install.sh
```

## Structure

- `bin/media-generation-wrapper.py`: Main Python interceptor and argument translator.
- `bin/wrapper-runner.sh`: Trampoline bash runner for atomic bind-mount execution.
- `install.sh`: Automated installer, binary backup, and persistence hook.
