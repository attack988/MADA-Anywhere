# MADA Anywhere v2 — تطبيق متعدد المنصات / Cross-platform PWA

واجهة عربية لتحليل وتنزيل الوسائط المسموح بها. يدعم المواقع بحسب إمكانيات yt-dlp؛ لا يتجاوز DRM. **ليس نسخة مطابقة من Snaptube وليس تطبيق iOS أو Android أصليًا.**

## الدعم الحقيقي بحسب النظام

| النظام | الواجهة | محرك التنزيل |
|---|---|---|
| Ubuntu / Linux | Chrome/Firefox/PWA | Python محلي أو خادم HTTPS |
| Windows | Edge/Chrome/PWA | Python محلي أو خادم HTTPS |
| macOS | Safari/Chrome/PWA | Python محلي أو خادم HTTPS |
| Android | Chrome/PWA | Termux محلي أو خادم HTTPS |
| iPhone/iPad | Safari → Add to Home Screen | **خادم خارجي HTTPS مطلوب**؛ لا يعمل yt-dlp داخل iOS PWA |

## التثبيت والتشغيل محليًا

- **Ubuntu/Linux**: `sudo apt install python3-venv ffmpeg` ثم `bash install_ubuntu_mac.sh && bash start_ubuntu_mac.sh`
- **macOS**: ثبّت `python3` و`ffmpeg` و`node` عبر Homebrew ثم `bash install_ubuntu_mac.sh && bash start_ubuntu_mac.sh`
- **Windows**: ثبّت Python 3.11+ (Add to PATH) وFFmpeg، شغّل `install_windows.bat` ثم `start_windows.bat`.
- **Android**: ثبّت Termux من مصدر رسمي. داخل مجلد المشروع شغّل `bash install_android_termux.sh && bash start_android_termux.sh`. افتح `http://127.0.0.1:8787` وأضف الصفحة للشاشة الرئيسية. يحتاج Termux أن يبقى يعمل.

عند التشغيل المحلي، افتح `http://127.0.0.1:8787`. يوصى بمشغّل JavaScript حديث مع yt-dlp-ejs لدعم مزيد من مواقع الفيديو.

## نشر الواجهة على GitHub Pages (للعمل على iPhone وAndroid والمتصفح من أي مكان)

1. انشر مجلد `web/` كجذر موقع HTTPS ثابت، مثل GitHub Pages، وليس ملف `index.html` وحده.
2. شغّل محرك التنزيل `server.py` على خادم خاص متصل بالإنترنت خلف HTTPS reverse proxy. **GitHub Pages لا يشغّل Python أو yt-dlp**.
3. عيّن `MADA_API_TOKEN` إلى رمز قوي فريد و`MADA_ALLOWED_ORIGINS` إلى عنوان موقع الواجهة مثل `https://username.github.io`.
4. في التطبيق → الإعدادات → عنوان المحرك: أدخل رابط HTTPS للخادم، وأدخل الرمز السري (يُحفظ حتى إغلاق جلسة المتصفح).
5. عند حفظ أي ملف على جهازك، اضغط «حفظ على الجهاز» بعد اكتمال التحميل على الخادم. الملف يوجد على الخادم أولًا؛ نقل الملفات الكبيرة وتوافق Safari يختلف حسب النظام.

**مثال تشغيل Docker خاص**: انسخ `.env.example` إلى `.env` وعدّل الرمز والأصل. شغّل `docker compose up -d --build`؛ المنفذ محصور في `127.0.0.1` افتراضيًا لتمريره عبر reverse proxy HTTPS. لا تفتح port 8787 مباشرة للإنترنت. يجب توفير تخزين دائم عند الاستضافة كي لا تضيع التنزيلات.

## الأمان

- لا تضع `.env` أو مفاتيح الوصول في GitHub؛ `.gitignore` يستثنيها.
- الطلبات البعيدة تتطلب Bearer token؛ روابط تشغيل الملفات تستخدم تذاكر محددة المدة بدل تمرير الرمز السري في الرابط.
- يقتصر CORS على الأصول الموثوقة؛ الخادم لا يسمح بـ `--host 0.0.0.0` دون رمز طويل وأصول مسموحة.
- يجب حصر المستخدمين الذين يملكون الرمز؛ لا تجعل خدمة التنزيل مفتوحة للجمهور.
- استخدم التطبيق للمحتوى الذي تملكه أو لديك تصريح بحفظه؛ مواقع مثل YouTube قد تفرض شروطًا وقيودًا إضافية.

## English

MADA Anywhere runs as a responsive installable web app on Linux, Windows, macOS, Android, and iOS. Python + yt-dlp operates locally on desktop/Android Termux, or on a private HTTPS backend for iOS and hosted installations. For iOS the browser UI works but the download engine is **not native**. `Dockerfile` and `compose.yaml` are provided for private hosting. MP3/HD conversions require FFmpeg. The backend stores files first and lets users retrieve them to their device. Never commit real tokens or expose the backend without HTTPS and authentication.
