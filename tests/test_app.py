"""Self-contained tests. Run: python -m unittest discover -s tests -v"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
from unittest.mock import patch

BASE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('mada_server', BASE / 'server.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)


class FakeYoutubeDL:
    def __init__(self, opts): self.opts = opts
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def extract_info(self, url, download=False):
        info = {'id':'test-123','title':'ملف تجربة', 'webpage_url':'https://example.com/watch?v=1',
                'thumbnail':'https://example.com/poster.jpg','duration':30,
                'uploader':'Example', 'formats':[{'height':720,'vcodec':'h264'}]}
        if download:
            path = self.opts['outtmpl'].replace('%(title).160B','Sample').replace('%(id)s', 'test-123').replace('%(ext)s','mp4')
            p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'0123456789' * 100)
            self.opts['progress_hooks'][0]({'status':'downloading','downloaded_bytes':500,'total_bytes':1000,'info_dict':info})
            self.opts['progress_hooks'][0]({'status':'finished','info_dict':info})
        return info


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.downloads = Path(cls.temp.name) / 'downloads'
        app.DOWNLOAD_DIR = cls.downloads
        app.DB_PATH = Path(cls.temp.name) / 'jobs.json'
        app.manager = app.DownloadManager()
        cls.fake = type('FakeModule', (), {'YoutubeDL':FakeYoutubeDL})
        cls.module_patch = patch.dict(sys.modules, {'yt_dlp':cls.fake})
        cls.module_patch.start()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()
        cls.module_patch.stop()
        cls.temp.cleanup()

    def get(self, path):
        return urlopen(self.url + path,timeout=5)

    def post(self, path, data):
        return urlopen(Request(self.url+path, data=json.dumps(data).encode(),
                       headers={'Content-Type':'application/json'},method='POST'),timeout=5)

    def test_url_rules(self):
        self.assertEqual(app.clean_url('www.example.com/a'), 'https://www.example.com/a')
        for value in ['file:///etc/passwd','http://127.0.0.1/','http://192.168.1.1/a',
                      'http://localhost/test','ftp://test.com/a']:
            with self.assertRaises(ValueError): app.clean_url(value)

    def test_health_and_static(self):
        health=json.load(self.get('/api/health'))
        self.assertTrue(health['ok']);self.assertTrue(health['engine'])
        self.assertIn('html',self.get('/').headers['content-type'])
        self.assertGreater(len(self.get('/app.js').read()),1000)
        self.assertIn('image/png',self.get('/icon-192.png').headers['content-type'])

    def test_info(self):
        data=json.load(self.post('/api/info',{'url':'https://example.com/video'}))
        self.assertEqual(data['item']['title'],'ملف تجربة')
        self.assertEqual(data['item']['heights'],[720])

    def test_download_and_range_and_delete(self):
        response=json.load(self.post('/api/jobs',{'url':'https://example.com/video','quality':'720','format':'mp4'}))
        jid=response['job']['id']
        status=None
        for _ in range(30):
            jobs=json.load(self.get('/api/jobs'))['jobs']
            status=next(v for v in jobs if v['id']==jid)['status']
            if status in ('completed','error'): break
            time.sleep(.1)
        self.assertEqual(status,'completed',app.manager.jobs[jid].get('error'))
        req=Request(self.url+'/api/file/'+jid,headers={'Range':'bytes=20-29'})
        with urlopen(req) as r:
            self.assertEqual(r.status,206);self.assertEqual(r.read(),b'0123456789')
        self.assertTrue(json.load(self.post('/api/jobs/'+jid+'/delete',{}))['ok'])
        self.assertIsNone(app.manager.file_for(jid))

    def test_no_engine_error(self):
        with patch.object(app,'yt_dlp_module',return_value=None):
            with self.assertRaises(RuntimeError):app.manager.enqueue('https://example.com','mp4','720')

if __name__ == '__main__': unittest.main()
