"""Generic rendered-page inspection, deliberately no unverified site selectors.

The user selects real product links from their current logged-in page. Captures
are evidence drafts, NOT claimed structured product extraction. This adapter
must be validated against live pages before automatic approval is implemented.
"""
import asyncio
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright
from .domain import safe_url, SITE_HOSTS
from .companion import challenge_reason


class Paused(Exception):
    pass


class Browser:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = asyncio.Lock()
        self.context = self.page = self.playwright = None
        self.state = "브라우저를 열어 신상마켓에 직접 로그인하세요."

    async def open(self):
        if self.context and self.page and not self.page.is_closed():
            return
        if self.context:
            await self.close()
        self.playwright = await async_playwright().start()
        executable = os.environ.get("SM_CHROMIUM") or shutil.which("chromium") or shutil.which("google-chrome")
        profile = self.directory / "browser-session"
        profile.mkdir(exist_ok=True, mode=0o700)
        profile.chmod(0o700)
        headless = os.environ.get("SM_HEADLESS", "1" if not os.environ.get("DISPLAY") and os.name != "nt" else "0") == "1"
        options = dict(headless=headless, viewport={"width": 1200, "height": 850}, accept_downloads=False)
        proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy_url:
            proxy = urlsplit(proxy_url)
            if proxy.scheme in {"http", "https", "socks5"} and proxy.hostname:
                server = f"{proxy.scheme}://{proxy.hostname}" + (f":{proxy.port}" if proxy.port else "")
                options["proxy"] = {"server": server, "bypass": "localhost,127.0.0.1"}
                if proxy.username:
                    from urllib.parse import unquote
                    options["proxy"]["username"] = unquote(proxy.username)
                    options["proxy"]["password"] = unquote(proxy.password or "")
        if executable:
            options["executable_path"] = executable
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(str(profile), **options)
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            await self.context.route("**/*", self._route)
            self.state = "브라우저 준비됨. 로그인·CAPTCHA는 직접 조작하세요."
        except Exception:
            await self.playwright.stop()
            self.playwright = None
            raise Paused("Chromium을 실행할 수 없습니다. 설치 안내의 브라우저 설치 단계를 확인하세요.")

    async def _route(self, route):
        request = route.request
        if request.is_navigation_request() and request.frame == self.page.main_frame:
            parts = urlsplit(request.url)
            if parts.scheme != "https" or parts.hostname not in SITE_HOSTS:
                self.state = "확인되지 않은 외부 로그인/이동 URL입니다. 자동 이동을 중지했습니다."
                await route.abort()
                return
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            # Browser login and read-only search may use POST. No code clicks
            # purchase/message controls; automation only navigates selected URLs.
            pass
        await route.continue_()

    async def navigate(self, url):
        await self.open()
        try:
            response = await self.page.goto(safe_url(url), wait_until="domcontentloaded", timeout=30000)
            if response and response.status in {401, 403, 429}:
                raise Paused(f"사이트 또는 네트워크에서 HTTP {response.status} 응답. 접근 제한을 우회하지 않고 중지했습니다.")
            safe_url(self.page.url)
            try:
                text = await self.page.locator("body").inner_text(timeout=3000)
            except Exception:
                text = ""
            reason = challenge_reason(text)
            if reason:
                self.state = reason
                raise Paused(reason)
        except Paused:
            raise
        except ValueError:
            raise Paused("외부 도메인 또는 인증 URL로 이동했습니다. 실제 지원 경로 확인이 필요합니다.")
        except Exception as exc:
            import re
            codes = re.findall(r"net::ERR_[A-Z_]+", str(exc))
            code = " (" + codes[0] + ")" if codes else ""
            raise Paused("페이지 접속 실패" + code + ". 네트워크 허용 설정 또는 브라우저 화면을 확인하세요.")

    async def guard(self):
        if not self.page or self.page.is_closed():
            raise Paused("먼저 브라우저를 열고 로그인하세요.")
        text = await self.page.locator("body").inner_text(timeout=10000)
        reason = challenge_reason(text)
        if reason:
            raise Paused(reason)
        passwords = self.page.locator('input[type="password"]')
        if any([await passwords.nth(i).is_visible() for i in range(await passwords.count())]):
            raise Paused("로그인이 필요합니다. 같은 브라우저에서 직접 로그인한 뒤 재개하세요.")
        try:
            safe_url(self.page.url)
        except ValueError:
            raise Paused("상품 페이지인지 확인할 수 없습니다. 로그인 후 상품 목록으로 이동하세요.")

    async def links(self):
        await self.guard()
        # Standard DOM links, not hypothetical product-specific paths/classes.
        links = await self.page.locator("a[href]").evaluate_all("els => els.map(e => ({url:e.href, label:(e.innerText || e.getAttribute('aria-label') || '').trim().slice(0,180)}))")
        unique = {}
        for link in links:
            try:
                url = safe_url(link["url"])
            except ValueError:
                continue
            if link["label"]:
                unique.setdefault(url, {"url": url, "label": link["label"]})
        return list(unique.values())[:500]

    async def capture(self, url, scope):
        await self.navigate(url)
        await self.guard()
        # No cookies, headers, localStorage, scripts, hidden fields or HTML dumps.
        # Avoid copying the whole authenticated page into result files.
        title = (await self.page.title())[:300]
        # The operator identified '제품설명' as the total-length location.
        # Only click a unique, visible matching element actually present now.
        tab = self.page.get_by_role("tab", name="제품설명", exact=True)
        if await tab.count() != 1:
            tab = self.page.get_by_text("제품설명", exact=True)
        opened_description = False
        if await tab.count() == 1 and await tab.is_visible():
            await tab.click(timeout=5000)
            opened_description = True
            await self.guard()
        tables = await self.page.locator("table:visible").evaluate_all("els => els.slice(0,20).map(t => [...t.rows].slice(0,60).map(r => [...r.cells].map(c => ({text:c.innerText.trim(), span:c.colSpan, rows:c.rowSpan}))))")
        options = table_candidates(tables)
        return {"url": safe_url(self.page.url), "name": title or "상품명 확인 필요",
                "supplier": "", "location": "", "gender": "남성" if scope.get("men_category_confirmed") else "미확인", "category": scope.get("category", "상의"),
                "image_url": "", "options": options, "capture_note": "실제 페이지 열기 완료. " + ("실제 제품설명 탭을 열었습니다. " if opened_description else "제품설명 탭을 자동으로 식별하지 못했습니다. ") + "상품명은 페이지 제목의 임시값입니다. HTML 표에서 찾은 총장도 검토용 후보이며, 가격·총장·옵션·남성 여부를 근거와 함께 확인하세요.",
                "source_type": "browser_draft", "inseparable_set": False, "separate_charges": ""}

    async def selected_text(self):
        await self.guard()
        text = await self.page.evaluate("window.getSelection().toString()")
        if not text.strip():
            raise Paused("상품 설명 또는 사이즈표에서 필요한 부분만 마우스로 선택한 뒤 가져오세요.")
        return text[:20000]

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self.context = self.page = self.playwright = None


def table_candidates(tables):
    """Read real standard HTML tables, never treat other dimensions as length.

    Both orientations supported. Merged cells, duplicate/ambiguous headers and
    different column counts are deliberately refused. All candidates unverified.
    """
    import re
    def header(value):
        return re.sub(r"[\s():：㎝]", "", value.lower()).replace("cm", "")
    output = []
    for table in tables:
        if not table or any(c["span"] != 1 or c["rows"] != 1 for row in table for c in row):
            continue
        rows = [[c["text"] for c in row] for row in table]
        headers = [header(c) for c in rows[0]]
        size_cols = [i for i, h in enumerate(headers) if h in {"사이즈", "size"}]
        length_cols = [i for i, h in enumerate(headers) if h in {"총장", "총기장", "기장"}]
        candidates = []
        if len(size_cols) == len(length_cols) == 1:
            for row in rows[1:]:
                if len(row) == len(headers):
                    candidates.append((row[size_cols[0]], row[length_cols[0]]))
        elif headers and headers[0] in {"사이즈", "size"}:
            length_rows = [r for r in rows[1:] if r and header(r[0]) in {"총장", "총기장", "기장"}]
            if len(length_rows) == 1 and len(length_rows[0]) == len(headers):
                candidates = list(zip(rows[0][1:], length_rows[0][1:]))
        for size, raw in candidates:
            if size and raw:
                output.append({"size": size, "color": "", "length_raw": raw[:500], "price": None,
                                "extra_price": None, "stock": "unknown", "price_verified": False,
                                "length_verified": False, "price_evidence": "", "length_evidence": "실제 HTML 표 총장 후보: " + size[:100] + " / " + raw[:500]})
    return output[:200]


class Collector:
    def __init__(self, store, browser):
        self.store, self.browser = store, browser
        self.task = None
        self.stop_requested = False

    async def start(self, job_id):
        if self.task and not self.task.done():
            raise ValueError("현재 수집을 중지한 뒤 다른 작업을 시작하세요.")
        job = next((j for j in self.store.jobs() if j["id"] == job_id), None)
        if not job:
            raise ValueError("수집 작업을 찾을 수 없습니다.")
        self.stop_requested = False
        self.store.set_job(job_id, "running")
        self.task = asyncio.create_task(self.run(job))

    def pause(self):
        self.stop_requested = True

    async def run(self, job):
        current = None
        try:
            for item in job["items"]:
                if item["state"] == "done":
                    continue
                if self.stop_requested:
                    self.store.set_job(job["id"], "paused", "사용자 중지. 완료한 결과는 저장되어 있습니다.")
                    return
                current = item
                self.store.set_item(item["id"], "working")
                try:
                    async with self.browser.lock:
                        data = await self.browser.capture(item["url"], job["scope"])
                    if self.stop_requested:
                        self.store.set_item(item["id"], "pending")
                        self.store.set_job(job["id"], "paused", "사용자 중지")
                        return
                    self.store.upsert(data)
                    self.store.set_item(item["id"], "done")
                except Paused as exc:
                    self.store.set_item(item["id"], "pending")
                    self.store.set_job(job["id"], "paused", str(exc))
                    return
                except Exception:
                    # One retry only for transient capture failures, with backoff.
                    await asyncio.sleep(3)
                    if self.stop_requested:
                        self.store.set_item(item["id"], "pending")
                        self.store.set_job(job["id"], "paused", "사용자 중지")
                        return
                    try:
                        async with self.browser.lock:
                            data = await self.browser.capture(item["url"], job["scope"])
                        self.store.upsert(data)
                        self.store.set_item(item["id"], "done")
                    except Paused as exc:
                        self.store.set_item(item["id"], "pending")
                        self.store.set_job(job["id"], "paused", str(exc))
                        return
                    except Exception:
                        self.store.set_item(item["id"], "failed", "페이지 증거 수집 실패 (1회 재시도 완료)")
                # Sequential, conservative pace; pause interrupts this delay.
                for _ in range(20):
                    if self.stop_requested:
                        break
                    await asyncio.sleep(0.1)
            self.store.set_job(job["id"], "completed")
        except asyncio.CancelledError:
            if current:
                self.store.set_item(current["id"], "pending")
            self.store.set_job(job["id"], "paused", "프로그램 종료: 재개할 수 있습니다.")
            raise
        except Exception:
            if current:
                self.store.set_item(current["id"], "pending")
            self.store.set_job(job["id"], "paused", "수집 오류. 저장된 결과는 유지됩니다.")
