"""Endpoint auth, cross-origin rules, signed URLs, and portable PWA asset paths."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
from unittest.mock import patch

BASE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('mada_security', BASE / 'server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class Security(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.original_token, cls.original_origins = app.API_TOKEN, app.ALLOWED_ORIGINS
        app.API_TOKEN = 'SECURE_TEST_KEY_' + 'x' * 28
        app.ALLOWED_ORIGINS = {'https://example.github.io'}
        app.DOWNLOAD_DIR = Path(cls.tmp.name) / 'media'
        app.DB_PATH = Path(cls.tmp.name) / 'jobs.json'
        app.manager = app.DownloadManager()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:%d' % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()
        app.API_TOKEN, app.ALLOWED_ORIGINS = cls.original_token, cls.original_origins
        cls.tmp.cleanup()

    def req(self, path, method='GET', headers=None, data=None):
        return Request(self.base + path, method=method, headers=headers or {}, data=data)

    def test_requires_token(self):
        with self.assertRaises(HTTPError) as cm:
            urlopen(self.req('/api/health'), timeout=3)
        self.assertEqual(cm.exception.code, 401)
        result=json.load(urlopen(self.req('/api/health', headers={'Authorization':'Bearer '+app.API_TOKEN}), timeout=3))
        self.assertTrue(result['ok'])
        self.assertEqual(result['downloads_dir'], 'مجلد الخادم')

    def test_cors_rejects_other_origin(self):
        with self.assertRaises(HTTPError) as cm:
            urlopen(self.req('/api/health', headers={'Authorization':'Bearer '+app.API_TOKEN,'Origin':'https://attacker.example'}), timeout=3)
        self.assertEqual(cm.exception.code, 403)
        with urlopen(self.req('/api/health',headers={'Authorization':'Bearer '+app.API_TOKEN,'Origin':'https://example.github.io'}),timeout=3) as r:
            self.assertEqual(r.headers.get('Access-Control-Allow-Origin'), 'https://example.github.io')
        with urlopen(self.req('/api/jobs', method='OPTIONS',headers={'Origin':'https://example.github.io','Access-Control-Request-Headers':'Authorization'}),timeout=3) as r:
            self.assertEqual(r.status,204)

    def test_ticket_cannot_be_forged(self):
        jid='a'*16
        ticket=app.make_ticket(jid, int(__import__('time').time())+600)
        self.assertTrue(app.ticket_ok(jid,ticket))
        self.assertFalse(app.ticket_ok(jid,ticket[:-1]+'0'))
        self.assertFalse(app.ticket_ok('b'*16,ticket))

    def test_manifest_paths_portable(self):
        info=json.loads((BASE/'web'/'manifest.webmanifest').read_text())
        self.assertEqual(info['start_url'],'./')
        self.assertEqual(info['scope'],'./')
        markup=(BASE/'web'/'index.html').read_text()
        self.assertIn('href="./style.css"', markup)
        self.assertIn('src="./app.js"', markup)

if __name__=='__main__': unittest.main()
