import asyncio
import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from smallcloset.app import create_app
from smallcloset.browser import Collector, Paused
from smallcloset.ocr import read_image, ocr_available
from smallcloset.store import Store
from test_domain import product, option

HEADERS={"X-Local-Client":"smallcloset"}


class FakeBrowser:
    """Test-only fixture, never installed in the production app."""
    def __init__(self):
        self.lock=asyncio.Lock();self.page=None;self.state="TEST ONLY";self.calls=[];self.pause_at=None
    async def capture(self,url,scope):
        if self.pause_at==len(self.calls):
            self.pause_at=None
            raise Paused("TEST ONLY expired session")
        self.calls.append(url)
        return product(option(),url=url)
    async def close(self):pass


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(self.temp.name,browser_override=FakeBrowser())
        self.context=TestClient(self.app)
        self.client=self.context.__enter__()
    def tearDown(self):
        self.context.__exit__(None,None,None);self.temp.cleanup()
    def post(self,p):return self.client.post('/api/products',json=p,headers=HEADERS)

    def test_home_and_empty_real_state(self):
        self.assertEqual(self.client.get('/').status_code,200)
        state=self.client.get('/api/state').json()
        self.assertEqual(state['products'],[])
        self.assertFalse(state['integration']['verified'])

    def test_boundary_save_and_reload(self):
        response=self.post(product(option()));self.assertEqual(response.status_code,200)
        items=self.client.get('/api/state').json()['products']
        self.assertEqual(items[0]['decision']['status'],'pass')
        self.assertEqual(Store(self.temp.name).products()[0]['decision']['matching_options'],['S / 선택 색상'])

    def test_duplicate_update_preserves_annotation(self):
        first=self.post(product(option())).json()['id']
        self.client.patch(f'/api/products/{first}',json={'memo':'내 메모','favorite':True,'excluded':True},headers=HEADERS)
        second=self.post(product(option(price=24000),url='https://www.sinsangmarket.kr/test-only-item/?utm_source=x')).json()['id']
        self.assertEqual(first,second)
        items=self.app.state.store.products();self.assertEqual(len(items),1)
        self.assertEqual(items[0]['memo'],'내 메모');self.assertTrue(items[0]['favorite']);self.assertTrue(items[0]['excluded'])
        self.assertEqual(items[0]['decision']['status'],'fail')

    def test_csv_bom_fields_selection_and_no_browser_data(self):
        first=self.post(product(option(),supplier='테스트 거래처')).json()['id']
        self.post(product(option(length='69'),url='https://www.sinsangmarket.kr/test-only-2'))
        self.client.patch(f'/api/products/{first}',json={'memo':'=danger()'},headers=HEADERS)
        response=self.client.get('/api/export?ids='+str(first));self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),2);self.assertIn('테스트 거래처',rows[1]);self.assertIn("'=danger()",rows[1])
        self.assertNotIn('browser-session',response.text);self.assertNotIn('cookies',response.text)
        self.assertEqual(len(list(csv.reader(io.StringIO(self.client.get('/api/export?status=fail').content.decode('utf-8-sig'))))),2)

    def test_rules_reclassify_saved_products(self):
        self.post(product(option()))
        rules=self.app.state.store.rules();rules['상의']['length']=67
        response=self.client.put('/api/rules',json={'rules':rules},headers=HEADERS)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.app.state.store.products()[0]['decision']['status'],'fail')

    def test_invalid_price_fields_and_nan(self):
        for overrides in [dict(price=-1),dict(extra_price=-1)]:
            self.assertEqual(self.post(product(option(**overrides))).status_code,422)
        self.assertEqual(self.post(product(option(),cookies='not allowed')).status_code,422)

    def test_csrf_and_host_checks(self):
        self.assertEqual(self.client.post('/api/products',json=product(option())).status_code,403)
        self.assertEqual(self.client.get('/api/state',headers={'Host':'evil.example'}).status_code,400)

    def test_cannot_serve_session_or_traverse_evidence(self):
        self.assertEqual(self.client.get('/api/evidence/session.json').status_code,404)
        self.assertEqual(self.client.get('/browser-session/Default/Cookies').status_code,404)

    def test_job_default_limit_and_dedup(self):
        urls=[f'https://www.sinsangmarket.kr/test-only-{i}' for i in range(25)]
        response=self.client.post('/api/jobs',json={'urls':urls+[urls[0]],'men_category_confirmed':True},headers=HEADERS)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.app.state.store.jobs()[0]['total'],20)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.browser=FakeBrowser();self.collector=Collector(self.store,self.browser)
        original_sleep=asyncio.sleep
        async def quick_sleep(seconds):await original_sleep(0)
        self.patch=patch('smallcloset.browser.asyncio.sleep',side_effect=quick_sleep);self.patch.start()
    async def asyncTearDown(self):
        self.patch.stop();self.temp.cleanup()
    def job(self,n=3):
        return self.store.create_job([f'https://www.sinsangmarket.kr/test-only-{i}' for i in range(n)],20,{})

    async def test_twenty_fixture_products(self):
        job=self.job(20);await self.collector.start(job);await self.collector.task
        self.assertEqual(self.store.jobs()[0]['done'],20)
        self.assertEqual(len(self.store.products()),20)
        self.assertEqual(self.store.jobs()[0]['state'],'completed')

    async def test_expiry_resume_same_queue_no_duplicates(self):
        job=self.job();self.browser.pause_at=1
        await self.collector.start(job);await self.collector.task
        self.assertEqual(self.store.jobs()[0]['state'],'paused')
        self.assertEqual(self.store.jobs()[0]['done'],1)
        await self.collector.start(job);await self.collector.task
        self.assertEqual(self.store.jobs()[0]['done'],3)
        self.assertEqual(len(self.store.products()),3)
        self.assertEqual(len(self.browser.calls),3)

    async def test_user_pause_then_resume(self):
        job=self.job();await self.collector.start(job);self.collector.pause();await self.collector.task
        self.assertEqual(self.store.jobs()[0]['state'],'paused')
        self.assertEqual(self.store.jobs()[0]['done'],0)
        await self.collector.start(job);await self.collector.task
        self.assertEqual(self.store.jobs()[0]['done'],3)

    async def test_restart_recovers_working_item(self):
        job=self.job();item=self.store.jobs()[0]['items'][0];self.store.set_job(job,'running');self.store.set_item(item['id'],'working')
        restored=Store(self.temp.name)
        self.assertEqual(restored.jobs()[0]['state'],'paused')
        self.assertEqual(restored.jobs()[0]['items'][0]['state'],'pending')

    async def test_error_bounded_retry_and_partial_results(self):
        original=self.browser.capture;counter=0
        async def fail_second(url,scope):
            nonlocal counter
            if url.endswith('-1'):
                counter+=1;raise RuntimeError('TEST ONLY failure')
            return await original(url,scope)
        self.browser.capture=fail_second
        job=self.job();await self.collector.start(job);await self.collector.task
        self.assertEqual(counter,2)
        self.assertEqual(self.store.jobs()[0]['failed'],1)
        self.assertEqual(self.store.jobs()[0]['done'],2)
        self.assertEqual(len(self.store.products()),2)


class OCRTests(unittest.TestCase):
    def test_invalid_image(self):
        with tempfile.TemporaryDirectory() as d,self.assertRaises(ValueError):read_image(b'not image',Path(d))

    @unittest.skipUnless(ocr_available() and os.environ.get('SM_TESSDATA'),'OCR installation required')
    def test_local_numeric_ocr_and_original_saved(self):
        from PIL import Image,ImageDraw,ImageFont
        image=Image.new('RGB',(600,250),'white');draw=ImageDraw.Draw(image);font=ImageFont.load_default(size=60)
        draw.text((30,25),'S 67 cm',fill='black',font=font);draw.text((30,130),'M 69 cm',fill='black',font=font)
        buffer=io.BytesIO();image.save(buffer,format='PNG')
        with tempfile.TemporaryDirectory() as d:
            result=read_image(buffer.getvalue(),Path(d))
            self.assertIn('67',result['text']);self.assertIn('69',result['text'])
            self.assertTrue((Path(d)/'evidence'/result['evidence']).exists())
            self.assertIn('OCR 초안',result['warning'])

    @unittest.skipUnless(ocr_available() and os.environ.get('SM_TESSDATA'),'OCR installation required')
    def test_korean_table_ocr_is_unverified_draft(self):
        # The same pixels exercise both native backends; OS-installed fonts do
        # not silently alter the input or cause the Windows OCR test to skip.
        content=(Path(__file__).parent/'fixtures/korean-size-table.png').read_bytes()
        with tempfile.TemporaryDirectory() as d:
            result=read_image(content,Path(d))
            self.assertIn('총장',result['text']);self.assertIn('67',result['text']);self.assertIn('69',result['text'])
            self.assertNotIn('options',result)
