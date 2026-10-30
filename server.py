#!/usr/bin/env python3
"""MADA Anywhere — local, cross-platform personal media downloader.

Run with Python 3.11+: python server.py. The interface is at http://127.0.0.1:8787.
Only download media you have permission to save. No DRM bypass is attempted.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import secrets
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit, parse_qs

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
APP_VERSION = "2.0.0"
API_TOKEN = os.environ.get("MADA_API_TOKEN", "").strip()
ALLOWED_ORIGINS = {v.strip().rstrip("/") for v in os.environ.get("MADA_ALLOWED_ORIGINS", "").split(",") if v.strip()}
PORT = 8787


def default_downloads_dir() -> Path:
    explicit = os.environ.get("MADA_DOWNLOAD_DIR")
    if explicit:
        return Path(explicit).expanduser()
    # Termux: export finished media directly to Android's shared Downloads directory.
    if "com.termux" in os.environ.get("PREFIX", ""):
        shared = Path.home() / "storage" / "downloads"
        if shared.is_dir():
            return shared / "MADA_Anywhere"
    return Path.home() / "Downloads" / "MADA_Anywhere"


DOWNLOAD_DIR = default_downloads_dir()
DB_PATH = Path(os.environ.get("MADA_DATA_DIR", APP_DIR)) / "jobs.json"
MAX_JOBS_SAVED = 300


def yt_dlp_module():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        return None


def clean_url(s: str) -> str:
    s = str(s).strip()
    if not s:
        raise ValueError("أدخل رابط فيديو أولًا.")
    if s.startswith("www."):
        s = "https://" + s
    if len(s) > 4096:
        raise ValueError("الرابط طويل جدًا.")
    p = urlsplit(s)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
        raise ValueError("استخدم رابط http أو https صحيحًا.")
    h = p.hostname.lower()
    if h in {"localhost", "localhost.localdomain"} or h.endswith((".local", ".internal")):
        raise ValueError("الروابط المحلية غير مدعومة.")
    try:
        addr = ipaddress.ip_address(h.strip("[]"))
        if not addr.is_global:
            raise ValueError("الروابط إلى الشبكات الخاصة غير مدعومة.")
    except ValueError as exc:
        if "الشبكات الخاصة" in str(exc):
            raise
    return s


def pretty_error(e: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    return msg[-400:] if msg else "تعذر إكمال العملية. حاول لاحقًا."


def simplify_video(info: dict) -> dict:
    if not isinstance(info, dict):
        return {}
    if info.get("_type") in ("playlist", "multi_video"):
        entries = [v for v in (info.get("entries") or []) if v]
        if not entries:
            raise ValueError("لم يتم العثور على فيديوهات في هذه القائمة.")
        info = entries[0]
    heights = sorted({int(f.get("height")) for f in info.get("formats", [])
                      if f.get("height") and f.get("vcodec") not in ("none", None)}, reverse=True)
    thumb = info.get("thumbnail", "") or ""
    if thumb and not thumb.startswith(("https://", "http://")):
        thumb = ""
    return {
        "title": str(info.get("title") or "فيديو بدون عنوان")[:250],
        "url": info.get("webpage_url") or info.get("original_url") or info.get("url") or "",
        "thumbnail": thumb,
        "uploader": str(info.get("uploader") or info.get("channel") or "")[:120],
        "duration": info.get("duration") if isinstance(info.get("duration"), (float, int)) else None,
        "id": str(info.get("id") or "")[:120],
        "site": str(info.get("extractor_key") or info.get("extractor") or "")[:75],
        "heights": heights[:20],
        "description": str(info.get("description") or "")[:260],
    }


class DownloadManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mada-download")
        self.jobs = {}
        self.cancel_flags = {}
        if DB_PATH.exists():
            try:
                with DB_PATH.open(encoding="utf-8") as f:
                    old_jobs = json.load(f)
                for item in old_jobs[:MAX_JOBS_SAVED]:
                    if item["status"] in ("queued", "downloading", "processing"):
                        item["status"] = "interrupted"
                        item["error"] = "أُغلق التطبيق قبل اكتمال التنزيل. أعد المحاولة."
                    self.jobs[item["id"]] = item
            except (OSError, ValueError, KeyError, TypeError):
                pass

    def _persist(self):
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = DB_PATH.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(sorted(self.jobs.values(), key=lambda j: j.get("created_at", 0))[-MAX_JOBS_SAVED:], f, ensure_ascii=False)
            tmp.replace(DB_PATH)
        except OSError as e:
            print("History could not be saved:", e)

    def snapshot(self):
        with self.lock:
            # Never disclose physical paths or internal control flags to the UI.
            return [self._public(j) for j in sorted(self.jobs.values(), key=lambda j: j.get("created_at", 0), reverse=True)]

    @staticmethod
    def _public(j):
        return {k: v for k, v in j.items() if k != "path"}

    def enqueue(self, url: str, fmt: str, quality: str):
        clean_url(url)
        if fmt not in ("mp4", "mp3", "m4a"):
            raise ValueError("صيغة التنزيل غير مدعومة.")
        if quality not in ("best", "2160", "1440", "1080", "720", "480", "360"):
            raise ValueError("الجودة المختارة غير صحيحة.")
        if not yt_dlp_module():
            raise RuntimeError("المحرك yt-dlp غير مُثبت. شغّل ملف التثبيت أولًا.")
        if fmt == "mp3" and not shutil.which("ffmpeg"):
            raise RuntimeError("تنزيل MP3 يتطلب FFmpeg. ثبّته ثم أعد المحاولة.")
        jid = uuid.uuid4().hex[:16]
        item = {
            "id": jid, "url": clean_url(url), "format": fmt, "quality": quality,
            "title": "جارٍ التحضير...", "thumbnail": "", "status": "queued",
            "progress": 0, "speed": None, "eta": None, "downloaded": 0,
            "total": None, "created_at": time.time(), "error": "", "filename": "",
            "path": "",
        }
        with self.lock:
            self.jobs[jid] = item
            self.cancel_flags[jid] = threading.Event()
            self._persist()
        self.executor.submit(self._run, jid)
        return self._public(item)

    def _patch(self, jid, **changes):
        with self.lock:
            if jid not in self.jobs:
                return
            self.jobs[jid].update(changes)
            return self.jobs[jid]

    def _run(self, jid):
        import yt_dlp
        with self.lock:
            j = self.jobs[jid]
            url, fmt, quality = j["url"], j["format"], j["quality"]
        folder = DOWNLOAD_DIR / jid
        folder.mkdir(parents=True, exist_ok=True)
        have_ffmpeg = bool(shutil.which("ffmpeg"))
        limit = "" if quality == "best" else f"[height<={int(quality)}]"
        options = {
            "noplaylist": True, "ignoreerrors": False,
            "outtmpl": str(folder / "%(title).160B [%(id)s].%(ext)s"),
            "quiet": True, "no_warnings": True,
            "windowsfilenames": True, "trim_file_name": 170,
            "continuedl": True, "retries": 5, "fragment_retries": 5,
            "progress_hooks": [lambda x: self._hook(jid, x)],
        }
        if fmt == "mp3":
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
        elif fmt == "m4a":
            options["format"] = "bestaudio[ext=m4a]/bestaudio/best" if have_ffmpeg else "bestaudio[ext=m4a]"
            if have_ffmpeg:
                options["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
        else:
            if have_ffmpeg:
                options["format"] = (f"bv[ext=mp4]{limit}+ba[ext=m4a]/"
                                     f"b[ext=mp4]{limit}/b{limit}/b")
                options["merge_output_format"] = "mp4"
            else:
                options["format"] = f"b[ext=mp4]{limit}/b{limit}/b"

        try:
            self._patch(jid, status="downloading")
            with yt_dlp.YoutubeDL(options) as ydl:
                # One video per job; playlists are intentionally not downloaded implicitly.
                info = ydl.extract_info(url, download=True)
                if info:
                    self._patch(jid, title=str(info.get("title") or self.jobs[jid]["title"])[:250],
                                thumbnail=simplify_video(info)["thumbnail"])
            if self.cancel_flags[jid].is_set():
                self._patch(jid, status="canceled", error="ألغى المستخدم التنزيل.")
            else:
                # Post-processing can change the filename/extension.
                all_files = sorted((f for f in folder.iterdir() if f.is_file()
                                    and not f.name.endswith((".part", ".ytdl", ".temp", ".info.json"))),
                                   key=lambda p: p.stat().st_size, reverse=True)
                files = [f for f in all_files if f.suffix.lower() in (".mp4", ".m4a", ".mp3", ".webm", ".mkv", ".mov", ".opus", ".ogg")]
                if not files:
                    raise RuntimeError("لم ينتج ملف قابل للتشغيل. تأكد من الرابط والجودة.")
                chosen = files[0]
                self._patch(jid, status="completed", progress=100, filename=chosen.name,
                            path=str(chosen.resolve()), total=chosen.stat().st_size,
                            downloaded=chosen.stat().st_size, speed=None, eta=0)
        except Exception as e:
            if self.cancel_flags[jid].is_set():
                self._patch(jid, status="canceled", error="ألغى المستخدم التنزيل.")
            else:
                self._patch(jid, status="error", error=pretty_error(e))
        finally:
            with self.lock:
                self.cancel_flags.pop(jid, None)
                self._persist()

    def _hook(self, jid, info):
        with self.lock:
            event = self.cancel_flags.get(jid)
            if event and event.is_set():
                raise Exception("User cancelled download")
            job = self.jobs.get(jid)
            if not job:
                return
            if (info.get("info_dict") or {}).get("title"):
                job["title"] = str(info["info_dict"]["title"])[:250]
            if info.get("status") == "finished":
                job.update(status="processing", progress=max(job["progress"], 98), speed=None)
            elif info.get("status") == "downloading":
                total = info.get("total_bytes") or info.get("total_bytes_estimate")
                downloaded = info.get("downloaded_bytes") or 0
                job.update(status="downloading", downloaded=downloaded, total=total,
                           speed=info.get("speed"), eta=info.get("eta"))
                if total:
                    job["progress"] = min(97, round(downloaded / total * 97, 1))

    def cancel(self, jid):
        with self.lock:
            job = self.jobs.get(jid)
            if not job:
                raise ValueError("العملية غير موجودة.")
            if job["status"] not in ("queued", "downloading", "processing"):
                raise ValueError("لا يمكن إلغاء هذه العملية.")
            event = self.cancel_flags.get(jid)
            if event:
                event.set()
            job["status"] = "canceled"
            self._persist()

    def delete(self, jid):
        with self.lock:
            job = self.jobs.get(jid)
            if not job:
                raise ValueError("العملية غير موجودة.")
            if job["status"] in ("queued", "downloading", "processing"):
                raise ValueError("ألغِ العملية أولًا، ثم احذفها.")
            del self.jobs[jid]
            self._persist()
        shutil.rmtree(DOWNLOAD_DIR / jid, ignore_errors=True)

    def file_for(self, jid):
        with self.lock:
            job = self.jobs.get(jid)
            if not job or job["status"] != "completed":
                return None
            val = job.get("path")
        if not val:
            return None
        p = Path(val).resolve()
        try:
            if not p.is_relative_to(DOWNLOAD_DIR.resolve()) or not p.is_file():
                return None
        except OSError:
            return None
        return p


def make_ticket(jid: str, expires: int) -> str:
    payload = f"{jid}.{expires}"
    signature = hmac.new(API_TOKEN.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def ticket_ok(jid: str, ticket: str) -> bool:
    try:
        raw_id, expiry, signature = ticket.split(".")
        if raw_id != jid or int(expiry) < time.time() or int(expiry) > time.time() + 3600:
            return False
        expected = hmac.new(API_TOKEN.encode(), f"{raw_id}.{expiry}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except (ValueError, TypeError):
        return False


manager = DownloadManager()


class Handler(BaseHTTPRequestHandler):
    server_version = "MADAAnywhere/1.0"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def allowed_origin(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if not origin:
            return ""
        own = f"http://{self.headers.get('Host', '')}"
        own_https = f"https://{self.headers.get('Host', '')}"
        if origin in (own, own_https) or origin in ALLOWED_ORIGINS:
            return origin
        return None

    def cors(self):
        origin = self.allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def authorize(self, ticket_jid=None):
        if self.allowed_origin() is None:
            self.send_json({"error": "هذا الموقع غير مخوّل بالاتصال بالمحرك."}, 403)
            return False
        if not API_TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if token and secrets.compare_digest(token, API_TOKEN):
            return True
        if ticket_jid:
            tickets = parse_qs(urlsplit(self.path).query).get("ticket", [])
            if tickets and ticket_ok(ticket_jid, tickets[0]):
                return True
        self.send_json({"error": "رمز الوصول غير صحيح. أدخله في الإعدادات."}, 401)
        return False

    def do_OPTIONS(self):
        if self.allowed_origin() is None:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def send_json(self, data, status=200):
        blob = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(blob)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0") or "0")
        if size <= 0 or size > 40_000:
            raise ValueError("حجم الطلب غير صالح.")
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/") and not self.authorize(path.split("/")[-1] if path.startswith("/api/file/") else None):
            return
        if path == "/api/health":
            self.send_json({"ok": True, "version": APP_VERSION,
                            "engine": yt_dlp_module() is not None,
                            "ffmpeg": bool(shutil.which("ffmpeg")),
                            "downloads_dir": "مجلد الخادم" if API_TOKEN else str(DOWNLOAD_DIR),
                            "android": "com.termux" in os.environ.get("PREFIX", "")})
            return
        if path == "/api/jobs":
            self.send_json({"jobs": manager.snapshot()})
            return
        if path.startswith("/api/file/"):
            jid = path.split("/")[-1]
            if not re.fullmatch(r"[0-9a-f]{16}", jid):
                self.send_json({"error": "رقم الملف غير صحيح"}, 400)
                return
            f = manager.file_for(jid)
            if not f:
                self.send_json({"error": "الملف غير موجود"}, 404)
                return
            self.send_media(f)
            return
        if path.startswith("/api/"):
            self.send_json({"error": "المسار غير موجود"}, 404)
            return
        self.send_static(path)

    def send_media(self, f: Path):
        length = f.stat().st_size
        typ = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        start, end = 0, length - 1
        range_header = self.headers.get("Range")
        if range_header:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not m:
                self.send_error(416)
                return
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), length - 1) if m.group(2) else end
            elif m.group(2):
                start = max(0, length - int(m.group(2)))
            if start > end or start >= length:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{length}")
                self.end_headers()
                return
        amount = end - start + 1
        self.send_response(206 if range_header else 200)
        self.cors()
        self.send_header("Content-Type", typ)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(amount))
        if range_header:
            self.send_header("Content-Range", f"bytes {start}-{end}/{length}")
        disposition = "attachment" if parse_qs(urlsplit(self.path).query).get("download") == ["1"] else "inline"
        self.send_header("Content-Disposition", disposition + "; filename*=UTF-8''" + quote(f.name))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        try:
            with f.open("rb") as fp:
                fp.seek(start)
                while amount > 0:
                    chunk = fp.read(min(256 * 1024, amount))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    amount -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_static(self, path):
        mapping = {
            "/": "index.html", "/index.html": "index.html",
            "/style.css": "style.css", "/app.js": "app.js",
            "/manifest.webmanifest": "manifest.webmanifest",
            "/sw.js": "sw.js", "/icon-192.png": "icon-192.png",
            "/icon-512.png": "icon-512.png",
        }
        file = mapping.get(path)
        if not file:
            self.send_error(404)
            return
        location = WEB_DIR / file
        if not location.exists():
            self.send_error(404)
            return
        data = location.read_bytes()
        typ, _ = mimetypes.guess_type(str(location))
        if file.endswith(".webmanifest"):
            typ = "application/manifest+json"
        if file.endswith(".js"):
            typ = "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", (typ or "application/octet-stream") + ("; charset=utf-8" if file.endswith(("html", "css", "js", "webmanifest")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = urlsplit(self.path).path
        if not self.authorize():
            return
        try:
            body = self.read_json()
            if not isinstance(body, dict):
                raise ValueError("صيغة الطلب غير صحيحة")
            if path == "/api/info":
                yt_dlp = yt_dlp_module()
                if not yt_dlp:
                    raise RuntimeError("المحرك yt-dlp غير مُثبت. شغّل ملف التثبيت أولًا.")
                url = clean_url(str(body.get("url", "")))
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                                       "skip_download": True}) as ydl:
                    data = ydl.extract_info(url, download=False)
                self.send_json({"item": simplify_video(data)})
            elif path == "/api/search":
                yt_dlp = yt_dlp_module()
                if not yt_dlp:
                    raise RuntimeError("المحرك yt-dlp غير مُثبت. شغّل ملف التثبيت أولًا.")
                query = str(body.get("query", "")).strip()[:120]
                if len(query) < 2:
                    raise ValueError("اكتب كلمتين أو أكثر للبحث.")
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                       "extract_flat": "in_playlist", "skip_download": True,
                                       "ignoreerrors": True}) as ydl:
                    data = ydl.extract_info("ytsearch8:" + query, download=False)
                items = []
                for v in (data.get("entries") or []) if data else []:
                    if not v:
                        continue
                    item = simplify_video(v)
                    if not item["url"].startswith(("http://", "https://")):
                        vid = str(v.get("id") or "")
                        item["url"] = "https://www.youtube.com/watch?v=" + vid if re.fullmatch(r"[\w-]{11}", vid) else ""
                    if item["url"]:
                        items.append(item)
                self.send_json({"items": items})
            elif path == "/api/jobs":
                job = manager.enqueue(str(body.get("url", "")), str(body.get("format", "mp4")),
                                      str(body.get("quality", "720")))
                self.send_json({"job": job}, 201)
            elif re.fullmatch(r"/api/jobs/[0-9a-f]{16}/ticket", path):
                jid = path.split("/")[3]
                if not manager.file_for(jid):
                    raise ValueError("الملف غير موجود.")
                ticket = f"?ticket={make_ticket(jid, int(time.time()) + 900)}" if API_TOKEN else ""
                self.send_json({"url": f"/api/file/{jid}{ticket}"})
            elif re.fullmatch(r"/api/jobs/[0-9a-f]{16}/cancel", path):
                jid = path.split("/")[3]
                manager.cancel(jid)
                self.send_json({"ok": True})
            elif re.fullmatch(r"/api/jobs/[0-9a-f]{16}/delete", path):
                jid = path.split("/")[3]
                manager.delete(jid)
                self.send_json({"ok": True})
            else:
                self.send_json({"error": "المسار غير موجود"}, 404)
        except (ValueError, json.JSONDecodeError) as e:
            self.send_json({"error": pretty_error(e)}, 400)
        except RuntimeError as e:
            self.send_json({"error": pretty_error(e)}, 503)
        except Exception as e:
            self.send_json({"error": pretty_error(e)}, 500)


def main():
    parser = argparse.ArgumentParser(description="MADA Anywhere media download manager")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--open", action="store_true", help="Open the interface in a browser")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; remote hosting needs HTTPS proxy and MADA_API_TOKEN")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1") and (len(API_TOKEN) < 24 or not ALLOWED_ORIGINS):
        parser.error("Public/LAN binding requires a strong MADA_API_TOKEN (24+ characters) and MADA_ALLOWED_ORIGINS")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        print(f"Could not start server on port {args.port}: {e}")
        raise SystemExit(1)
    url = f"http://{args.host}:{args.port}"
    print("=" * 55)
    print(" MADA ANYWHERE — مستعرض وتنزيل الوسائط")
    print(" App: ", url)
    print(" Downloads:", DOWNLOAD_DIR)
    print(" yt-dlp:", "installed" if yt_dlp_module() else "NOT INSTALLED")
    print(" FFmpeg:", "installed" if shutil.which("ffmpeg") else "not installed (MP3/HD merge unavailable)")
    print(" Ctrl+C to stop")
    print("=" * 55)
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
