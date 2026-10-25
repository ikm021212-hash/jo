"""Real Chromium extension + local server, synthetic TEST pages only."""
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import base64
import io
import json
import re
from urllib.parse import urlsplit
from pathlib import Path
import httpx
from playwright.async_api import async_playwright, expect

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from smallcloset.companion import EXTENSION_ID

URL='https://www.sinsangmarket.kr/test-only-companion'
HTML='''<title>테스트 전용 상품</title><p id="description">제품설명 테스트 전용 총장 근거</p>
<input type="hidden" value="TEST-ONLY-PRIVATE-MUST-NOT-LEAK">
<table><tr><th>사이즈</th><th>가슴단면</th><th>총장</th></tr>
<tr><td>S</td><td>60</td><td>67</td></tr><tr><td>M</td><td>62</td><td>69</td></tr></table>'''


async def exercise_automatic(client,context,product,popup,base):
    from PIL import Image,ImageDraw
    image=Image.new('RGB',(200,200),'#35644b');ImageDraw.Draw(image).text((20,80),'TEST PHOTO',fill='white')
    buffer=io.BytesIO();image.save(buffer,format='PNG')
    photo='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
    chart='data:image/png;base64,'+base64.b64encode((ROOT/'tests/fixtures/korean-size-table.png').read_bytes()).decode()
    gate={'blocked':True};visits={}
    def item_html(index):
        name=f'크롭 후드집업 테스트 {index}'
        expensive=index==3
        offers=[{'@type':'Offer','price':25000 if expensive else 23800,'priceCurrency':'KRW','availability':'https://schema.org/InStock','itemOffered':{'@type':'Product','size':'S','color':'검정'},'seller':{'name':'테스트 거래처'}},
                {'@type':'Offer','price':23000,'priceCurrency':'KRW','availability':'https://schema.org/InStock','itemOffered':{'@type':'Product','size':'M','color':'검정'}}]
        metadata={'@context':'https://schema.org','@type':'Product','name':name,'image':photo,'offers':offers}
        measurements=(f'<img src="{chart}" alt="사이즈표">' if index==2 else
                      '<table><caption>단위: cm</caption><tr><th>사이즈</th><th>총장(cm)</th></tr><tr><td>S</td><td>67</td></tr><tr><td>M</td><td>69</td></tr></table>')
        return f'''<title>사이트 공통 제목</title><script type="application/ld+json">{json.dumps(metadata,ensure_ascii=False)}</script>
        <main><h1>{name}</h1><img src="{photo}" alt="{name}"><p>{'25,000' if expensive else '23,800'}원 / 23,000원</p>
        <input type="hidden" value="TEST-ONLY-PRIVATE-MUST-NOT-LEAK">
        <button onclick="document.querySelector('#description').hidden=false">제품설명</button><div id="description" hidden>크롭 디자인 제품설명</div>
        <button onclick="document.querySelector('#cuts').hidden=false">디테일컷</button><section id="cuts" hidden>{measurements}</section></main>'''
    listing='https://www.sinsangmarket.kr/test-auto-men-list?keyword=all'
    async def route(request):
        path=urlsplit(request.request.url).path
        if path=='/test-auto-men-list':
            cards=''.join(f'<a href="https://www.sinsangmarket.kr/test-auto-product-{i}" title="크롭 후드집업 테스트 {i}"><img src="{photo}"><span>크롭 후드집업 테스트 {i} 23,800원</span></a>' for i in range(1,21))
            content='<title>남성 목록 테스트</title><h1>남성의류</h1>'+cards
        else:
            index=int(path.rsplit('-',1)[-1]);visits[index]=visits.get(index,0)+1
            content='<title>보안 확인 수행 중</title><p>사람인지 확인하십시오</p>' if index==4 and gate['blocked'] else item_html(index)
        await request.fulfill(status=200,content_type='text/html; charset=utf-8',body=content)
    await context.route(re.compile(r'https://www\.sinsangmarket\.kr/test-auto-'),route)
    await product.goto(listing);await product.bring_to_front()
    await popup.locator('#limit').fill('20')
    await popup.locator('#auto-start').evaluate('(el)=>el.click()')
    await expect(popup.locator('#job-id')).to_have_value(re.compile(r'\d+'),timeout=20000)
    job_id=int(await popup.locator('#job-id').input_value())
    async def wait_state(expected,timeout=160):
        for _ in range(timeout*4):
            job=(await client.get(base+f'/api/companion/auto/{job_id}')).json()
            if job.get('state')==expected:return job
            await asyncio.sleep(0.25)
        raise AssertionError(f'Automatic job did not reach {expected}: {job}')
    paused=await wait_state('paused')
    assert paused['done']==3 and paused['total']==20,paused
    assert '보안 확인' in paused['reason']
    assert visits[4]==1,'security gate must not be automatically retried'
    await product.bring_to_front();await popup.locator('#auto-resume').evaluate('(el)=>el.click()')
    await asyncio.sleep(0.4)
    assert (await client.get(base+f'/api/companion/auto/{job_id}')).json()['state']=='paused'
    assert visits[4]==1
    # Simulated human completion on a synthetic page, never a real CAPTCHA.
    gate['blocked']=False;await product.set_content(item_html(4))
    await product.bring_to_front();await popup.locator('#auto-resume').evaluate('(el)=>el.click()')
    completed=await wait_state('completed')
    assert completed['done']==20 and completed['failed']==0,completed
    state=(await client.get(base+'/api/state')).json()
    records=[p for p in state['products'] if p['source_type']=='chrome_auto']
    assert len(records)==20
    by_index={int(p['url'].rsplit('-',1)[-1]):p for p in records}
    assert by_index[1]['name']=='크롭 후드집업 테스트 1'
    assert by_index[1]['supplier']=='테스트 거래처'
    assert by_index[1]['decision']['matching_options']==['S / 검정']
    assert '디테일컷' in by_index[1]['capture_note']
    assert by_index[3]['decision']['status']=='fail','must not mix cheapest and shortest variants'
    assert by_index[2]['decision']['status']=='review'
    assert '67' in by_index[2]['ocr_notes'] and by_index[2]['evidence_images']
    assert 'TEST-ONLY-PRIVATE-MUST-NOT-LEAK' not in str(state)
    for record in records:
        assert record['image_url'].startswith('/api/evidence/')
        response=await client.get(base+record['image_url']);assert response.status_code==200
        assert response.content.startswith(b'\x89PNG')
    dashboard=await context.new_page();await dashboard.goto(base)
    await expect(dashboard.locator('.card-image img')).to_have_count(20,timeout=15000)
    for _ in range(50):
        if await dashboard.locator('.card-image img').evaluate_all('(images)=>images.length===20 && images.every(image=>image.complete && image.naturalWidth>0)'):
            break
        await asyncio.sleep(0.1)
    else:raise AssertionError('saved product images did not load in the results screen')
    await expect(dashboard.get_by_role('heading',name='크롭 후드집업 테스트 1',exact=True)).to_be_visible()
    print('PASS: ONE start -> 20 real extension-driven synthetic detail visits; detail-cut tab measurements; exact names, suppliers and reloaded local photos; image OCR; security pause/no retry/manual resume; same-option S-only match; no duplicate or cookie leak. NOT LIVE SITE DATA.')


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
                        # Never send synthetic cookies or test paths to the live site.
                        await context.route('https://www.sinsangmarket.kr/**',lambda route:route.abort())
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
                        await popup.locator('body[data-ready="true"]').wait_for()
                        await popup.locator('#port').fill(str(port));await popup.locator('#category').select_option('상의')
                        await popup.locator('#confirmed').check();await product.bring_to_front()
                        await popup.locator('#capture').evaluate('(el)=>el.click()')
                        await expect(popup.locator('#status')).to_contain_text('초안을 저장',timeout=20000)
                        state=(await client.get(base+'/api/state')).json()
                        assert len(state['products'])==1
                        record=state['products'][0]
                        assert record['decision']['status']=='review'
                        assert [(o['size'],o['length_raw']) for o in record['options']]==[('S','67'),('M','69')]
                        assert 'TEST-ONLY-PRIVATE-MUST-NOT-LEAK' not in str(state)
                        await popup.locator('#capture').evaluate('(el)=>el.click()')
                        await expect(popup.locator('#status')).to_contain_text('초안을 저장',timeout=20000)
                        assert len((await client.get(base+'/api/state')).json()['products'])==1
                        # User-reported Cloudflare text: no capture/no retry.
                        await product.set_content('<title>보안 확인 수행 중</title><p>사람인지 확인하십시오</p>')
                        await product.bring_to_front();await popup.locator('#capture').evaluate('(el)=>el.click()')
                        await expect(popup.locator('#status')).to_contain_text('보안 확인',timeout=15000)
                        assert len((await client.get(base+'/api/state')).json()['products'])==1
                        await product.set_content('<title>TEST LOGIN</title><input type="password" value="TEST-ONLY-PRIVATE-MUST-NOT-LEAK">')
                        await product.bring_to_front();await popup.locator('#capture').evaluate('(el)=>el.click()')
                        await expect(popup.locator('#status')).to_contain_text('로그인 화면',timeout=15000)
                        assert len((await client.get(base+'/api/state')).json()['products'])==1
                        print('PASS: real extension popup -> active page DOM -> local app; Korean table candidates; duplicate update; no cookie/hidden input leak; reported security screen and password form refused. TEST PAGES ONLY.')
                        await exercise_automatic(client,context,product,popup,base)
                    finally:await context.close()
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()


if __name__=='__main__':asyncio.run(main())
