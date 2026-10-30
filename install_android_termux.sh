#!/data/data/com.termux/files/usr/bin/bash
set -e
cd "$(dirname "$0")"
echo 'Installing MADA Anywhere for Android Termux...'
pkg update -y
pkg install -y python ffmpeg nodejs
python -m pip install --upgrade -r requirements.txt
termux-setup-storage || true
echo 'Done. Run bash start_android_termux.sh'
