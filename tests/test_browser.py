"""Actual Chromium with intercepted TEST HTML; no live-site validation claim."""
import os
import tempfile
import unittest
from smallcloset.browser import Browser, Paused
from smallcloset.domain import evaluate, DEFAULT_RULES

URL='https://www.sinsangmarket.kr/test-only-browser-fixture'


@unittest.skipUnless(os.environ.get('SM_BROWSER_TESTS')=='1','set SM_BROWSER_TESTS=1 to exercise Chromium')
class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.browser=Browser(self.temp.name)
        await self.browser.open()
        self.html=''
        async def fixture(route):
            await route.fulfill(status=200,content_type='text/html; charset=utf-8',body=self.html)
        await self.browser.context.route('https://www.sinsangmarket.kr/test-only-browser-fixture*',fixture)
    async def asyncTearDown(self):
        await self.browser.close();self.temp.cleanup()

    async def test_real_rendered_description_tab_and_sizes(self):
        self.html='''<title>TEST ONLY</title><button role="tab" onclick="document.getElementById('size').hidden=false">제품설명</button>
        <table id="size" hidden><tr><th>사이즈</th><th>가슴단면</th><th>총장</th></tr>
        <tr><td>S</td><td>60</td><td>67</td></tr><tr><td>M</td><td>62</td><td>69</td></tr></table>'''
        data=await self.browser.capture(URL,{'category':'상의'})
        self.assertEqual([(o['size'],o['length_raw']) for o in data['options']],[('S','67'),('M','69')])
        self.assertIn('실제 제품설명 탭을 열었습니다',data['capture_note'])
        self.assertEqual(evaluate(data,DEFAULT_RULES)['status'],'review')
        self.assertNotIn('cookies',data)

    async def test_login_pauses_without_reading_password_value(self):
        self.html='<title>TEST ONLY LOGIN</title><input type="password" value="TEST-ONLY-NOT-A-CREDENTIAL">'
        with self.assertRaisesRegex(Paused,'로그인'):
            await self.browser.capture(URL,{})

    async def test_captcha_pauses(self):
        self.html='<title>TEST ONLY</title><p>CAPTCHA verify you are human</p>'
        with self.assertRaisesRegex(Paused,'CAPTCHA'):
            await self.browser.capture(URL,{})

    async def test_only_actual_safe_links_exposed(self):
        self.html='<a href="/test-only-item?utm_source=x">실제 DOM 링크</a><a href="https://example.com">외부</a><a href="/x?session=TEST-ONLY">인증</a>'
        await self.browser.navigate(URL)
        links=await self.browser.links()
        self.assertEqual(links,[{'url':'https://www.sinsangmarket.kr/test-only-item','label':'실제 DOM 링크'}])
