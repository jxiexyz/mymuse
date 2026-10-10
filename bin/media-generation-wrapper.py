#!/usr/bin/env python3
import sys
import os
import json
import subprocess
import uuid

REAL_BIN = "/home/hatch/workspace/bin/real/media-generation"

def get_image_ratio(path):
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
            if w > 0:
                return h / w
    except Exception:
        pass
    return 1.77  # Default to vertical ~9:16

def main():
    argv = sys.argv[1:]

    # Check if this is video generation through media_subagent
    is_video = False
    conv_json_str = None
    output_dir = "/home/hatch/workspace/imagine_media"
    timeout_secs = "120"
    output_name = None
    explicit_orientation = None
    explicit_aspect_ratio = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--media-subagent-output-type" and i + 1 < len(argv):
            if argv[i + 1] == "video":
                is_video = True
            i += 2
        elif arg == "--conversation-json" and i + 1 < len(argv):
            conv_json_str = argv[i + 1]
            i += 2
        elif arg == "--output-dir" and i + 1 < len(argv):
            output_dir = argv[i + 1]
            i += 2
        elif arg == "--output-name" and i + 1 < len(argv):
            output_name = argv[i + 1]
            i += 2
        elif arg == "--timeout-secs" and i + 1 < len(argv):
            timeout_secs = argv[i + 1]
            i += 2
        elif arg == "--orientation" and i + 1 < len(argv):
            explicit_orientation = argv[i + 1]
            i += 2
        elif arg == "--aspect-ratio" and i + 1 < len(argv):
            explicit_aspect_ratio = argv[i + 1]
            i += 2
        else:
            i += 1

    # Pass through directly if not video generation
    if not is_video or not os.path.exists(REAL_BIN):
        os.execv(REAL_BIN, [REAL_BIN] + argv)

    # Intercept video request
    try:
        conv = json.loads(conv_json_str) if conv_json_str else []
    except Exception:
        conv = []

    images = []
    texts = []

    for item in conv:
        if isinstance(item, dict):
            img_val = item.get("image") or item.get("image_file") or item.get("image_path") or item.get("path")
            if img_val:
                # Resolve relative path if needed
                if not os.path.isabs(img_val):
                    p1 = os.path.join("/home/hatch", img_val)
                    p2 = os.path.join("/home/hatch/workspace", img_val)
                    if os.path.exists(p1):
                        img_val = p1
                    elif os.path.exists(p2):
                        img_val = p2
                if os.path.exists(img_val):
                    images.append(img_val)
            txt_val = item.get("text")
            if txt_val:
                texts.append(txt_val.strip())

    prompt_text = " ".join(texts) if texts else "Animate with natural continuous smooth motion"

    os.makedirs(output_dir, exist_ok=True)

    # If no input image, generate base image first
    if not images:
        img_cmd = [
            REAL_BIN,
            "--media-subagent-output-type", "image",
            "--conversation-json", json.dumps([{"text": prompt_text}]),
            "--output-dir", output_dir,
            "--timeout-secs", timeout_secs
        ]
        if output_name:
            img_cmd.extend(["--output-name", output_name])

        res_img = subprocess.run(img_cmd, capture_output=True, text=True)
        if res_img.returncode != 0:
            sys.stderr.write(res_img.stderr or res_img.stdout)
            sys.exit(res_img.returncode)

        try:
            img_data = json.loads(res_img.stdout)
            base_image = img_data["media_paths"][0]
        except Exception as e:
            sys.stderr.write(f"Failed to parse image output: {e}\n{res_img.stdout}\n")
            sys.exit(1)
    else:
        base_image = images[0]

    # Determine optimal orientation/aspect ratio matching source image
    ratio = get_image_ratio(base_image)

    anim_cmd = [
        REAL_BIN,
        "--avatar-animate-image",
        "--image-file", base_image,
        "--output-dir", output_dir,
        "--timeout-secs", timeout_secs
    ]

    if explicit_aspect_ratio:
        anim_cmd.extend(["--aspect-ratio", explicit_aspect_ratio])
    elif explicit_orientation:
        anim_cmd.extend(["--orientation", explicit_orientation])
    else:
        # Auto-match from source image aspect ratio
        if ratio >= 1.3:
            # Vertical 9:16 (phone/reels/shorts)
            anim_cmd.extend(["--aspect-ratio", "9:16"])
        elif ratio <= 0.75:
            # Landscape 16:9
            anim_cmd.extend(["--orientation", "landscape"])
        else:
            # Square 1:1
            anim_cmd.extend(["--orientation", "square"])

    if output_name:
        anim_cmd.extend(["--output-name", output_name])
    anim_cmd.append(prompt_text)

    res_anim = subprocess.run(anim_cmd, capture_output=True, text=True)
    if res_anim.returncode != 0:
        sys.stderr.write(res_anim.stderr or res_anim.stdout)
        sys.exit(res_anim.returncode)

    try:
        anim_data = json.loads(res_anim.stdout)
    except Exception as e:
        sys.stderr.write(f"Failed to parse animation output: {e}\n{res_anim.stdout}\n")
        sys.exit(1)

    snap_id = f"{uuid.uuid4()}:subagent"
    payload_path = anim_data.get("output_path")

    # Update payload JSON file to match media_subagent contract
    if payload_path and os.path.exists(payload_path):
        try:
            with open(payload_path, "r") as f:
                p_data = json.load(f)
            p_data["text"] = json.dumps({"status": "ok", "snapshot_id": snap_id})
            with open(payload_path, "w") as f:
                json.dump(p_data, f, indent=2)
        except Exception as e:
            sys.stderr.write(f"Warning updating payload json: {e}\n")

    # Construct exact media_subagent video output
    subagent_out = {
        "bytes": anim_data.get("bytes", 0),
        "media_handles": anim_data.get("media_handles", []),
        "media_paths": anim_data.get("media_paths", []),
        "media_type": "video",
        "media_urls": anim_data.get("media_urls", []),
        "ok": True,
        "output_path": payload_path,
        "snapshot_id": snap_id,
        "status": 200,
        "tool": "media_subagent"
    }

    print(json.dumps(subagent_out))
    sys.exit(0)

if __name__ == "__main__":
    main()
