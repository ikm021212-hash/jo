"""Real Chromium extension + local server, synthetic TEST pages only."""
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
import httpx
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from smallcloset.companion import EXTENSION_ID

URL='https://www.sinsangmarket.kr/test-only-companion'
HTML='''<title>테스트 전용 상품</title><p id="description">제품설명 테스트 전용 총장 근거</p>
<input type="hidden" value="TEST-ONLY-PRIVATE-MUST-NOT-LEAK">
<table><tr><th>사이즈</th><th>가슴단면</th><th>총장</th></tr>
<tr><td>S</td><td>60</td><td>67</td></tr><tr><td>M</td><td>62</td><td>69</td></tr></table>'''


async def main():
    with tempfile.TemporaryDirectory(prefix='smallcloset companion ') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        server=subprocess.Popen([sys.executable,'-m','smallcloset.app'],cwd=ROOT,
                                env={**os.environ,'SM_DATA_DIR':str(Path(directory)/'data'),'SM_PORT':str(port)},
                                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            async with httpx.AsyncClient() as client:
                for _ in range(80):
                    try:
                        if (await client.get(base+'/api/health')).status_code==200:break
                    except httpx.ConnectError:pass
                    await asyncio.sleep(0.1)
                else:raise AssertionError('companion test server not ready')
                async with async_playwright() as p:
                    extension=str(ROOT/'chrome-extension')
                    # Test-only extension loader documented by Chrome DevTools.
                    # The user's ordinary Chrome uses its normal Load Unpacked UI.
                    options=dict(headless=True,channel='chromium',ignore_default_args=['--disable-extensions'],
                                 args=['--enable-unsafe-extension-debugging'])
                    if shutil.which('chromium'):options['executable_path']=shutil.which('chromium')
                    context=await p.chromium.launch_persistent_context(str(Path(directory)/'profile'),**options)
                    try:
                        cdp=await context.browser.new_browser_cdp_session()
                        loaded=await cdp.send('Extensions.loadUnpacked',{'path':extension})
                        assert loaded['id']==EXTENSION_ID
                        await context.route(URL,lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=HTML))
                        await context.add_cookies([{'url':URL,'name':'TEST_ONLY_SESSION','value':'TEST-ONLY-PRIVATE-MUST-NOT-LEAK'}])
                        product=await context.new_page();await product.goto(URL)
                        await product.evaluate("() => { const range=document.createRange(); range.selectNodeContents(document.querySelector('#description')); const s=getSelection();s.removeAllRanges();s.addRange(range); }")
                        # MV3 workers may be asleep until the popup sends a
                        # message. The stable public key makes this URL fixed.
                        popup=await context.new_page()
                        await popup.goto(f'chrome-extension://{EXTENSION_ID}/popup.html')
                        await popup.locator('#port').fill(str(port));await popup.locator('#category').select_option('상의')
                        await popup.locator('#confirmed').check();await product.bring_to_front()
                        await popup.locator('#capture').evaluate('(el)=>el.click()')
                        await popup.wait_for_function("document.querySelector('#status').textContent.includes('초안을 저장')",timeout=20000)
                        state=(await client.get(base+'/api/state')).json()
                        assert len(state['products'])==1
                        record=state['products'][0]
                        assert record['decision']['status']=='review'
                        assert [(o['size'],o['length_raw']) for o in record['options']]==[('S','67'),('M','69')]
                        assert 'TEST-ONLY-PRIVATE-MUST-NOT-LEAK' not in str(state)
                        await popup.locator('#capture').evaluate('(el)=>el.click()')
                        await popup.wait_for_function("document.querySelector('#status').textContent.includes('초안을 저장')",timeout=20000)
                        assert len((await client.get(base+'/api/state')).json()['products'])==1
                        # User-reported Cloudflare text: no capture/no retry.
                        await product.set_content('<title>보안 확인 수행 중</title><p>사람인지 확인하십시오</p>')
                        await product.bring_to_front();await popup.locator('#capture').evaluate('(el)=>el.click()')
                        await popup.wait_for_function("document.querySelector('#status').textContent.includes('보안 확인')",timeout=15000)
                        assert len((await client.get(base+'/api/state')).json()['products'])==1
                        await product.set_content('<title>TEST LOGIN</title><input type="password" value="TEST-ONLY-PRIVATE-MUST-NOT-LEAK">')
                        await product.bring_to_front();await popup.locator('#capture').evaluate('(el)=>el.click()')
                        await popup.wait_for_function("document.querySelector('#status').textContent.includes('로그인 화면')",timeout=15000)
                        assert len((await client.get(base+'/api/state')).json()['products'])==1
                        print('PASS: real extension popup -> active page DOM -> local app; Korean table candidates; duplicate update; no cookie/hidden input leak; reported security screen and password form refused. TEST PAGES ONLY.')
                    finally:await context.close()
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()


if __name__=='__main__':asyncio.run(main())
