#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
(sleep 2; termux-open-url http://127.0.0.1:8787 >/dev/null 2>&1 || true) &
python server.py
