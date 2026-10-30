#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Python 3.11+ is required.'; exit 1; }
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --upgrade -r requirements.txt
printf '\n✓ Ready. For MP3 and high-resolution merging, install FFmpeg:\n'
printf 'Ubuntu: sudo apt update && sudo apt install ffmpeg nodejs\nmacOS: brew install ffmpeg node\n'
printf 'Then run ./start_ubuntu_mac.sh\n'
