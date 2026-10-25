import hashlib
import http.server
import io
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw, ImageFont
from smallcloset.desktop import is_our_server, open_when_ready, reserve_port
from smallcloset.ocr import ocr_available, read_image
from smallcloset.runtime import data_dir, default_data_dir

from scripts.setup_models import fetch_verified


class SetupTests(unittest.TestCase):
    def test_windows_uses_localappdata_not_source_folder(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'LOCALAPPDATA':d}):
            self.assertEqual(default_data_dir('win32'),Path(d)/'SmallCloset')

    def test_explicit_data_location_preserved(self):
        with tempfile.TemporaryDirectory(prefix='smallcloset test ') as d,patch.dict(os.environ,{'SM_DATA_DIR':d}):
            self.assertEqual(data_dir(),Path(d).resolve())

    def test_model_verified_then_reused(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'trusted-source';source.write_bytes(b'test model')
            target=Path(d)/'models'/'kor.traineddata'
            sha=hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertTrue(fetch_verified(source.as_uri(),target,sha))
            source.unlink()
            self.assertFalse(fetch_verified(source.as_uri(),target,sha))

    def test_bad_download_keeps_existing_model_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'corrupt-source';source.write_bytes(b'CORRUPT TEST ONLY')
            parent=Path(d)/'models';parent.mkdir()
            target=parent/'kor.traineddata';target.write_bytes(b'previous user file')
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                fetch_verified(source.as_uri(),target,'0'*64)
            self.assertEqual(target.read_bytes(),b'previous user file')
            self.assertEqual(list(parent.iterdir()),[target])

    @unittest.skipUnless(ocr_available() and os.environ.get('SM_TESSDATA'),'OCR installation required')
    def test_ocr_worker_accepts_korean_path_and_returns_unicode(self):
        image=Image.new('RGB',(400,150),'white')
        ImageDraw.Draw(image).text((20,25),'67 cm',font=ImageFont.load_default(size=60),fill='black')
        content=io.BytesIO();image.save(content,format='PNG')
        with tempfile.TemporaryDirectory(prefix='smallcloset unicode ') as d:
            directory=Path(d)/'작은옷장 사이즈표';directory.mkdir()
            result=read_image(content.getvalue(),directory)
            self.assertIn('67',result['text'])
            self.assertTrue((directory/'evidence'/result['evidence']).exists())


class DesktopTests(unittest.TestCase):
    def setUp(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'app':'smallcloset'}).encode())
            def log_message(self,*args):pass
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def test_ready_opens_browser_only_after_our_health_response(self):
        opened=[]
        self.assertTrue(open_when_ready(self.port,timeout=2,open_browser=lambda url:opened.append(url) or True))
        self.assertEqual(opened,[f'http://127.0.0.1:{self.port}'])

    def test_busy_port_uses_another_local_port(self):
        sock=reserve_port(self.port)
        try:
            self.assertNotEqual(sock.getsockname()[1],self.port)
            self.assertEqual(sock.getsockname()[0],'127.0.0.1')
        finally:sock.close()

    def test_does_not_open_browser_for_unrelated_server(self):
        with patch('smallcloset.desktop.is_our_server',return_value=False):
            opened=[]
            self.assertFalse(open_when_ready(self.port,timeout=0.01,open_browser=lambda url:opened.append(url) or True))
            self.assertEqual(opened,[])
