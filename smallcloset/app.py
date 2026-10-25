import asyncio
import base64
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.cors import CORSMiddleware
from .browser import Browser, Collector, Paused, table_candidates
from .companion import EXTENSION_DIRECTORY, EXTENSION_ID, EXTENSION_ORIGIN, challenge_reason
from .domain import DEFAULT_RULES, safe_url
from .ocr import read_image
from .store import Store
from .runtime import data_dir


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Option(Model):
    size: str = Field(default="", max_length=100)
    color: str = Field(default="", max_length=100)
    price: float | None = Field(default=None, ge=0, le=100000000)
    extra_price: float | None = Field(default=None, ge=0, le=100000000)
    length_raw: str = Field(default="", max_length=500)
    stock: Literal["available", "sold_out", "unknown"] = "unknown"
    price_verified: bool = False
    length_verified: bool = False
    price_evidence: str = Field(default="", max_length=2000)
    length_evidence: str = Field(default="", max_length=2000)


class Product(Model):
    url: str = Field(max_length=2048)
    name: str = Field(default="", max_length=300)
    supplier: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    category: Literal["아우터", "상의", "바지", "미분류"] = "미분류"
    gender: Literal["남성", "여성", "미확인"] = "미확인"
    image_url: str = Field(default="", max_length=2048)
    inseparable_set: bool = False
    separate_charges: str = Field(default="", max_length=500)
    options: list[Option] = Field(default_factory=list, max_length=200)
    capture_note: str = Field(default="", max_length=2000)
    source_excerpt: str = Field(default="", max_length=1500)
    source_type: Literal["manual", "browser_draft", "chrome_companion"] = "manual"

    @field_validator("url")
    @classmethod
    def url_check(cls, value):
        return safe_url(value)

    @field_validator("image_url")
    @classmethod
    def image_check(cls, value):
        if not value or re.fullmatch(r"/api/evidence/[a-f0-9]{64}\.png", value):
            return value
        return safe_url(value, site_only=False)


class Bounds(Model):
    price: float = Field(ge=0, le=100000000)
    length: float = Field(gt=0, le=250)


class Rules(Model):
    rules: dict[str, Bounds]

    @field_validator("rules")
    @classmethod
    def categories(cls, value):
        if set(value) != set(DEFAULT_RULES):
            raise ValueError("아우터·상의·바지의 기준이 모두 필요합니다.")
        return value


class Annotation(Model):
    favorite: bool | None = None
    excluded: bool | None = None
    memo: str | None = Field(default=None, max_length=10000)


class Job(Model):
    urls: list[str] = Field(min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=200)
    category: Literal["아우터", "상의", "바지", "미분류"] = "상의"
    keyword: str = Field(default="", max_length=200)
    men_category_confirmed: Literal[True]


class Navigate(Model):
    url: str = Field(max_length=2048)


class Action(Model):
    kind: Literal["click", "type", "key", "scroll", "drag"]
    x: float = Field(default=0, ge=0, le=1200)
    y: float = Field(default=0, ge=0, le=850)
    end_x: float = Field(default=0, ge=0, le=1200)
    end_y: float = Field(default=0, ge=0, le=850)
    text: str = Field(default="", max_length=1000)
    delta: int = Field(default=500, ge=-1500, le=1500)


class Crop(Model):
    x: float = Field(ge=0, le=1200)
    y: float = Field(ge=0, le=850)
    width: float = Field(ge=20, le=1200)
    height: float = Field(ge=20, le=850)


class CapturedCell(Model):
    text: str = Field(max_length=500)
    span: int = Field(ge=1, le=100)
    rows: int = Field(ge=1, le=100)


class CompanionProduct(Model):
    url: str = Field(max_length=2048)
    title: str = Field(default="", max_length=300)
    category: Literal["미분류", "아우터", "상의", "바지"] = "미분류"
    selection: str = Field(default="", max_length=1500)
    confirmed_product: Literal[True]
    men_category_confirmed: Literal[True]
    tables: list[list[list[CapturedCell]]] = Field(default_factory=list, max_length=20)

    @field_validator("url")
    @classmethod
    def url_check(cls, value):
        return safe_url(value)

    @field_validator("tables")
    @classmethod
    def limit_tables(cls, value):
        if any(len(table) > 60 or any(len(row) > 20 for row in table) for table in value):
            raise ValueError("표의 행·열이 너무 많습니다. 필요한 사이즈표만 직접 확인해 주세요.")
        cells = [cell for table in value for row in table for cell in row]
        if len(cells) > 2000 or sum(len(cell.text) for cell in cells) > 100000:
            raise ValueError("표 데이터가 너무 큽니다. 필요한 사이즈표만 직접 확인해 주세요.")
        return value


def create_app(directory=None, browser_override=None):
    store = Store(directory or data_dir())
    browser = browser_override or Browser(store.directory)
    collector = Collector(store, browser)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if collector.task and not collector.task.done():
            collector.task.cancel()
            try:
                await collector.task
            except asyncio.CancelledError:
                pass
        await browser.close()

    app = FastAPI(title="작은옷장 선별실", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.browser, app.state.collector = store, browser, collector
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.add_middleware(CORSMiddleware, allow_origins=[EXTENSION_ORIGIN], allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Local-Client"], allow_credentials=False)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        extension_preflight = request.method == "OPTIONS" and request.headers.get("origin") == EXTENSION_ORIGIN
        if request.method not in {"GET", "HEAD"} and not extension_preflight and request.headers.get("x-local-client") != "smallcloset":
            return Response("local client required", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(Paused)
    async def paused(request, exc):
        from fastapi.responses import JSONResponse
        browser.state = str(exc)
        return JSONResponse({"detail": str(exc)}, status_code=409)

    def require_idle():
        if collector.task and not collector.task.done():
            raise HTTPException(409, "수집을 일시정지한 뒤 브라우저를 직접 조작하세요.")

    @app.get("/api/state")
    async def state():
        return {"products": store.products(), "rules": store.rules(), "jobs": store.jobs(),
                "browser": browser.state, "browser_open": browser.page is not None,
                "integration": {"verified": False, "message": "실제 사이트 자동 추출 미검증 · 링크 선택 수집은 검토용 초안입니다. 가격·총장·재고 근거 확인 후 판정합니다."}}

    @app.get("/api/health")
    async def health():
        return {"app": "smallcloset", "ready": True}

    @app.get("/api/companion/info")
    async def companion_info():
        return {"extension_id": EXTENSION_ID, "folder": str(EXTENSION_DIRECTORY), "installed_source": EXTENSION_DIRECTORY.is_dir()}

    @app.post("/api/companion/open-folder")
    async def companion_folder():
        if os.name != "nt":
            raise HTTPException(409, "이 PC에서 표시된 chrome-extension 폴더 경로를 직접 여세요.")
        os.startfile(str(EXTENSION_DIRECTORY))
        return {"ok": True}

    @app.post("/api/companion/products")
    async def companion_product(body: CompanionProduct, request: Request):
        if request.headers.get("origin") not in {None, EXTENSION_ORIGIN}:
            raise HTTPException(403, "등록된 Chrome 확장프로그램에서만 가져올 수 있습니다.")
        reason = challenge_reason(body.title + "\n" + body.selection)
        if reason:
            raise HTTPException(409, reason)
        tables = [[[cell.model_dump() for cell in row] for row in table] for table in body.tables]
        data = Product(url=body.url, name=body.title or "상품명 확인 필요", category=body.category, gender="남성",
                       options=table_candidates(tables), source_type="chrome_companion",
                       source_excerpt=body.selection,
                       capture_note="일반 Chrome에서 남성의류 카테고리로부터 이동한 상품임을 사용자가 확인했습니다. 상품명은 페이지 제목의 임시값이며 가격·총장·재고 확인이 필요합니다.\n선택한 원문: " + body.selection)
        return {"id": store.upsert(data.model_dump()), "status": "review"}

    @app.put("/api/rules")
    async def rules(body: Rules):
        store.save_rules({key: value.model_dump() for key, value in body.rules.items()})
        return {"ok": True}

    @app.post("/api/products")
    async def product(body: Product):
        return {"id": store.upsert(body.model_dump())}

    @app.put("/api/products/{product_id}")
    async def update_product(product_id: int, body: Product):
        old = store.product(product_id)
        if not old:
            raise HTTPException(404, "상품이 없습니다.")
        if body.url != old["url"]:
            raise HTTPException(400, "상품 식별 URL은 변경할 수 없습니다. 새 상품으로 등록하세요.")
        return {"id": store.upsert(body.model_dump())}

    @app.patch("/api/products/{product_id}")
    async def annotate(product_id: int, body: Annotation):
        if not store.product(product_id):
            raise HTTPException(404, "상품이 없습니다.")
        store.annotate(product_id, **body.model_dump(exclude_none=True))
        return {"ok": True}

    @app.get("/api/export")
    async def export(ids: str = "", status: str = "", category: str = "", supplier: str = "", favorite: bool = False, include_excluded: bool = False):
        products = store.products()
        if ids:
            try:
                selected = {int(value) for value in ids.split(",")}
            except ValueError:
                raise HTTPException(400, "상품 선택 값이 올바르지 않습니다.")
            products = [p for p in products if p["id"] in selected]
        else:
            products = [p for p in products if (not status or p["decision"]["status"] == status)
                        and (not category or p.get("category") == category)
                        and (not supplier or p.get("supplier") == supplier)
                        and (not favorite or p["favorite"])
                        and (include_excluded or not p["excluded"])]
        return Response(store.csv(products), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="smallcloset.csv"'})

    @app.post("/api/jobs")
    async def create_job(body: Job):
        job_id = store.create_job(body.urls, body.limit, {"category": body.category, "keyword": body.keyword, "men_category_confirmed": True})
        return {"id": job_id}

    @app.post("/api/jobs/{job_id}/resume")
    async def resume(job_id: int):
        await collector.start(job_id)
        return {"ok": True}

    @app.post("/api/jobs/pause")
    async def pause():
        collector.pause()
        return {"ok": True, "message": "현재 요청 처리 후 중지합니다. 최대 30초가 걸릴 수 있습니다."}

    @app.post("/api/browser/open")
    async def open_browser():
        require_idle()
        async with browser.lock:
            await browser.open()
        return {"ok": True}

    @app.post("/api/browser/navigate")
    async def navigate(body: Navigate):
        require_idle()
        async with browser.lock:
            await browser.navigate(body.url)
        return {"ok": True}

    @app.post("/api/browser/close")
    async def close_browser():
        require_idle()
        async with browser.lock:
            await browser.close()
        return {"ok": True}

    @app.get("/api/browser/screenshot")
    async def screenshot():
        if not browser.page:
            raise HTTPException(409, "브라우저를 먼저 열어주세요.")
        async with browser.lock:
            content = await browser.page.screenshot(type="jpeg", quality=75)
        return Response(content, media_type="image/jpeg")

    @app.post("/api/browser/action")
    async def action(body: Action):
        require_idle()
        if not browser.page:
            raise HTTPException(409, "브라우저가 열려 있지 않습니다.")
        async with browser.lock:
            if body.kind == "click":
                await browser.page.mouse.click(body.x, body.y)
            elif body.kind == "type":
                await browser.page.keyboard.insert_text(body.text)
            elif body.kind == "key":
                if body.text not in {"Enter", "Tab", "Backspace", "ControlOrMeta+A", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"}:
                    raise HTTPException(400, "지원하지 않는 키입니다.")
                await browser.page.keyboard.press(body.text)
            elif body.kind == "drag":
                await browser.page.mouse.move(body.x, body.y)
                await browser.page.mouse.down()
                try:
                    await browser.page.mouse.move(body.end_x, body.end_y, steps=20)
                finally:
                    await browser.page.mouse.up()
            else:
                await browser.page.mouse.wheel(0, body.delta)
        return {"ok": True}

    @app.get("/api/browser/links")
    async def links():
        require_idle()
        async with browser.lock:
            return {"links": await browser.links()}

    @app.get("/api/browser/selection")
    async def selection():
        require_idle()
        async with browser.lock:
            return {"text": await browser.selected_text()}

    @app.post("/api/ocr")
    async def ocr(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 10_000_000:
                raise HTTPException(413, "이미지는 10MB 이하로 올려주세요.")
        return await asyncio.to_thread(read_image, bytes(content), store.directory)

    @app.post("/api/browser/ocr-crop")
    async def ocr_crop(body: Crop):
        require_idle()
        if body.x + body.width > 1200 or body.y + body.height > 850:
            raise HTTPException(400, "브라우저 화면 안에서 사이즈표만 선택하세요.")
        async with browser.lock:
            await browser.guard()
            content = await browser.page.screenshot(type="png", clip=body.model_dump())
        return await asyncio.to_thread(read_image, content, store.directory)

    @app.get("/api/evidence/{name}")
    async def evidence(name: str):
        if not re.fullmatch(r"[a-f0-9]{64}\.png", name):
            raise HTTPException(404)
        path = store.directory / "evidence" / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png")

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html")

    return app


def main():
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("SM_PORT", "8000")), access_log=False)


if __name__ == "__main__":
    main()
