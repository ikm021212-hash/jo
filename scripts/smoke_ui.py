"""Browser smoke test against a temporary local DB, never actual site data."""
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from playwright.async_api import async_playwright
import httpx

ROOT = Path(__file__).resolve().parent.parent


async def main():
    with tempfile.TemporaryDirectory(prefix="smallcloset-ui-test-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0));port=sock.getsockname()[1]
        base=f"http://127.0.0.1:{port}"
        server=subprocess.Popen([sys.executable,"-m","smallcloset.app"],cwd=ROOT,
                                env={**os.environ,"SM_DATA_DIR":directory,"SM_PORT":str(port)},
                                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            async with httpx.AsyncClient() as client:
                for _ in range(50):
                    try:
                        if (await client.get(base+"/api/state")).status_code==200:break
                    except httpx.ConnectError:pass
                    await asyncio.sleep(0.1)
                else:raise AssertionError("test server startup failed")
            async with async_playwright() as p:
                options={"headless":True}
                if shutil.which("chromium"):options["executable_path"]=shutil.which("chromium")
                browser=await p.chromium.launch(**options)
                page=await browser.new_page(viewport={"width":1440,"height":1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto(base)
                await page.wait_for_function("document.querySelector('#count-all').textContent === '0'")
                await page.screenshot(path="/tmp/smallcloset-empty-ui.png",full_page=True)
                await page.click('#new-product')
                await page.fill('#p-url','https://www.sinsangmarket.kr/ui-test-only')
                await page.fill('#p-name','테스트 전용 S·M 총장 상품')
                await page.fill('#p-supplier','테스트 거래처')
                await page.select_option('#p-category','상의')
                await page.select_option('#p-gender','남성')
                for size,length in [('S','67'),('M','69')]:
                    if size=='M':await page.click('#add-option')
                    row=page.locator('.option').last
                    for field,value in dict(size=size,color='테스트 색상',price='23800',extra_price='0',length_raw=length,
                                             price_evidence='테스트 전용 원문 23800원 추가금 없음',length_evidence='테스트 전용 총장 '+length+'cm').items():
                        await row.locator('[data-field='+field+']').fill(value)
                    await row.locator('[data-field=stock]').select_option('available')
                    await row.locator('[data-field=price_verified]').check()
                    await row.locator('[data-field=length_verified]').check()
                await page.fill('#p-memo','UI 테스트 메모')
                await page.locator('#product-form button[type=submit]').click()
                await page.wait_for_selector('#editor',state='hidden')
                await page.wait_for_selector('.card')
                assert '조건 충족: S / 테스트 색상' in await page.locator('.reason').inner_text()
                assert 'M / 테스트 색상' not in await page.locator('.reason').inner_text()
                await page.click('[data-action=favorite]')
                await page.wait_for_selector('.favorite.on')
                await page.check('#filter-favorite')
                assert await page.locator('.card').count()==1
                await page.check('.card-select')
                async with page.expect_download() as download_info:
                    await page.click('#export')
                download=await download_info.value
                output=Path(directory)/'test.csv';await download.save_as(output)
                assert output.read_bytes().startswith(b'\xef\xbb\xbf')
                assert 'UI 테스트 메모' in output.read_text(encoding='utf-8-sig')
                await page.click('[data-action=exclude]')
                await page.wait_for_selector('.card',state='detached')
                await page.check('#show-excluded')
                await page.wait_for_selector('.card.excluded')
                await page.reload();await page.wait_for_selector('#empty:not(.hidden)')
                await page.check('#show-excluded');await page.wait_for_selector('.card.excluded')
                assert 'UI 테스트 메모' in await page.locator('.memo-preview').inner_text()
                await page.screenshot(path='/tmp/smallcloset-fixture-ui.png',full_page=True)
                await page.set_viewport_size({'width':390,'height':844})
                await page.screenshot(path='/tmp/smallcloset-mobile-ui.png',full_page=True)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile overflow'
                assert errors==[],errors
                await browser.close()
                print('PASS: UI create, same-option S-only result, favorite, filter, exclude, reload persistence, selected CSV, mobile layout, no JS errors. TEST DATA ONLY.')
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()


if __name__=='__main__':asyncio.run(main())
