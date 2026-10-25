import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .domain import DEFAULT_RULES, evaluate, safe_url


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.path = self.directory / "products.sqlite3"
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, data TEXT NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0, excluded INTEGER NOT NULL DEFAULT 0,
                    memo TEXT NOT NULL DEFAULT '', collected_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, url TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
                    UNIQUE(job_id,url));
            ''')
            db.execute("UPDATE jobs SET state='paused',reason='프로그램 재시작: 브라우저 상태 확인 후 재개하세요.' WHERE state='running'")
            db.execute("UPDATE queue SET state='pending' WHERE state='working'")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            # sqlite3's own context manager commits/rolls back but does not close.
            # Windows keeps the DB/WAL locked until every handle is closed.
            with db:
                yield db
        finally:
            db.close()

    def rules(self):
        with self.connect() as db:
            row = db.execute("SELECT data FROM settings WHERE key='rules'").fetchone()
        return json.loads(row[0]) if row else json.loads(json.dumps(DEFAULT_RULES))

    def save_rules(self, rules):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('rules',?)", (json.dumps(rules),))

    def upsert(self, data):
        data = dict(data)
        url = safe_url(data.pop("url"))
        stamp = now()
        # Never persist browser cookies, storage state or arbitrary request headers.
        with self.connect() as db:
            db.execute('''INSERT INTO products(url,data,collected_at,updated_at) VALUES (?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET data=excluded.data,
                collected_at=excluded.collected_at,updated_at=excluded.updated_at''',
                       (url, json.dumps(data, ensure_ascii=False), stamp, stamp))
            return db.execute("SELECT id FROM products WHERE url=?", (url,)).fetchone()[0]

    def products(self):
        rules = self.rules()
        with self.connect() as db:
            rows = db.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item.update(json.loads(item.pop("data")))
            item["decision"] = evaluate(item, rules)
            output.append(item)
        return output

    def product(self, product_id):
        return next((p for p in self.products() if p["id"] == product_id), None)

    def annotate(self, product_id, **data):
        allowed = {k: v for k, v in data.items() if k in {"favorite", "excluded", "memo"}}
        if allowed:
            with self.connect() as db:
                db.execute("UPDATE products SET " + ",".join(k + "=?" for k in allowed) + ",updated_at=? WHERE id=?",
                           [*allowed.values(), now(), product_id])

    def create_job(self, urls, limit, scope):
        unique = list(dict.fromkeys(safe_url(url) for url in urls))[:limit]
        if not unique:
            raise ValueError("수집할 상품 URL을 선택하세요.")
        with self.connect() as db:
            cursor = db.execute("INSERT INTO jobs(state,scope,created_at) VALUES ('paused',?,?)", (json.dumps(scope, ensure_ascii=False), now()))
            job_id = cursor.lastrowid
            db.executemany("INSERT INTO queue(job_id,url) VALUES (?,?)", [(job_id, url) for url in unique])
        return job_id

    def jobs(self):
        with self.connect() as db:
            jobs = [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 30")]
            for job in jobs:
                job["scope"] = json.loads(job["scope"])
                job["items"] = [dict(r) for r in db.execute("SELECT * FROM queue WHERE job_id=? ORDER BY id", (job["id"],))]
                job["total"] = len(job["items"])
                job["done"] = sum(i["state"] == "done" for i in job["items"])
                job["failed"] = sum(i["state"] == "failed" for i in job["items"])
        return jobs

    def set_job(self, job_id, state, reason=""):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state=?,reason=? WHERE id=?", (state, reason, job_id))

    def set_item(self, item_id, state, error=""):
        with self.connect() as db:
            db.execute("UPDATE queue SET state=?,error=? WHERE id=?", (state, error, item_id))

    def csv(self, products):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["판정", "상품명", "상품 링크", "거래처", "상가·층·호수", "분류", "표시 가격·옵션 추가금", "사이즈별 총장", "충족 옵션", "색상·재고", "메모", "수집 시각", "가격·총장 근거", "판정 이유", "배송비·부가세 별도 표기"])
        status = {"pass": "조건 충족", "review": "확인 필요", "fail": "조건 미충족"}
        for p in products:
            opts = p.get("options", [])
            row = [status[p["decision"]["status"]], p.get("name", ""), p["url"], p.get("supplier", ""), p.get("location", ""), p.get("category", ""),
                   "; ".join(f"{o.get('size','')} {o.get('color','')}: {o.get('price')} + {o.get('extra_price')}원" for o in opts),
                   "; ".join(f"{o.get('size','')} {o.get('color','')}: {o.get('length_raw','미확인')}" for o in opts),
                   "; ".join(p["decision"]["matching_options"]),
                   "; ".join(f"{o.get('color','')}: {o.get('stock','unknown')}" for o in opts), p.get("memo", ""), p["collected_at"],
                   "; ".join(f"{o.get('size','')}: 가격 {o.get('price_evidence','')} / 총장 {o.get('length_evidence','')}" for o in opts),
                   p["decision"]["reason"], p.get("separate_charges", "")]
            # Excel formula injection: neutralize user/site-controlled cells.
            writer.writerow(["'" + str(v) if str(v).lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else str(v) for v in row])
        return ("\ufeff" + stream.getvalue()).encode("utf-8")
