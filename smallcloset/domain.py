"""Pure decision rules. No site selectors or guessed product facts."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_RULES = {
    "아우터": {"price": 51500, "length": 70},
    "상의": {"price": 23800, "length": 68},
    "바지": {"price": 29300, "length": 100},
}
SITE_HOSTS = {"sinsangmarket.kr", "www.sinsangmarket.kr"}
SECRET_KEY = re.compile(r"token|session|auth|password|secret|credential|code|ticket|signature|key", re.I)


def safe_url(value: str, *, site_only=True) -> str:
    p = urlsplit(value.strip())
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("인증 정보 없는 HTTPS URL을 입력하세요.")
    if site_only and p.hostname.lower() not in SITE_HOSTS:
        raise ValueError("확인된 신상마켓 도메인의 URL만 사용합니다.")
    if p.port not in (None, 443):
        raise ValueError("기본 HTTPS 포트만 허용합니다.")
    pairs = parse_qsl(p.query, keep_blank_values=True)
    if any(SECRET_KEY.search(k) for k, _ in pairs):
        raise ValueError("인증 정보로 보이는 쿼리 매개변수가 있는 URL은 저장하지 않습니다.")
    pairs = sorted((k, v) for k, v in pairs if not k.lower().startswith("utm_") and k not in {"fbclid", "gclid"})
    return urlunsplit(("https", p.hostname.lower(), p.path.rstrip("/") or "/", urlencode(pairs), ""))


def parse_length(raw: str) -> float | None:
    """Parse only a field explicitly identified as 총장 by the operator/table header.

    Ambiguous mixed measurements, units, approximations and unlabeled collections
    are rejected. Ranges and explicitly labeled front/back lengths use the max.
    """
    s = raw.strip().lower()
    if not s or re.search(r"가슴|허리|인심|밑위|어깨|소매|단면|엉덩|허벅|밑단|inseam|waist|chest", s):
        return None
    if re.search(r"약|대략|추정|내외|오차|±|미정|unknown|inch|인치|mm|[<>≤≥]", s):
        return None
    s = re.sub(r"(?:총장|기장|length)\s*[:：]?", "", s)
    n = r"(\d{1,3}(?:\.\d{1,2})?)"
    unit = r"\s*(?:cm|㎝|센티미터)?\s*"
    one = re.fullmatch(r"\s*" + n + unit, s)
    values = None
    if one:
        values = [float(one[1])]
    else:
        span = re.fullmatch(r"\s*" + n + unit + r"(?:~|～|–|—|-)\s*" + n + unit, s)
        if span:
            values = [float(span[1]), float(span[2])]
        else:
            fb = re.fullmatch(r"\s*(?:앞|전면|front)\s*[:：]?\s*" + n + unit + r"[/,·\s]+(?:뒤|후면|back)\s*[:：]?\s*" + n + unit, s)
            bf = re.fullmatch(r"\s*(?:뒤|후면|back)\s*[:：]?\s*" + n + unit + r"[/,·\s]+(?:앞|전면|front)\s*[:：]?\s*" + n + unit, s)
            match = fb or bf
            if match:
                values = [float(match[1]), float(match[2])]
    if values and all(0 < v <= 250 for v in values):
        return max(values)
    return None


def evaluate(product: dict, rules: dict) -> dict:
    category = product.get("category")
    if category not in rules:
        return {"status": "review", "reason": "분류를 확인해 주세요.", "matching_options": [], "options": []}
    if product.get("inseparable_set"):
        return {"status": "review", "reason": "세트의 품목별 가격·총장을 구분할 수 없습니다.", "matching_options": [], "options": []}
    if product.get("gender") != "남성":
        return {"status": "review", "reason": "남성 의류 여부 확인이 필요합니다.", "matching_options": [], "options": []}
    results = []
    for option in product.get("options", []):
        label = " / ".join(filter(None, [option.get("size"), option.get("color")])) or "옵션명 미확인"
        price = option.get("price")
        extra = option.get("extra_price")
        length = parse_length(option.get("length_raw", ""))
        price_known = (option.get("price_verified") and bool(option.get("price_evidence", "").strip())
                       and isinstance(price, (int, float)) and not isinstance(price, bool)
                       and isinstance(extra, (int, float)) and not isinstance(extra, bool)
                       and price >= 0 and extra >= 0)
        length_known = (length is not None and option.get("length_verified")
                        and bool(option.get("length_evidence", "").strip()))
        total = price + extra if price_known else None
        reasons = []
        failed = False
        if price_known and total > rules[category]["price"]:
            failed = True
            reasons.append("가격 상한 초과")
        if length_known and length > rules[category]["length"]:
            failed = True
            reasons.append("총장 상한 초과")
        if option.get("stock") == "sold_out":
            failed = True
            reasons.append("품절")
        if not price_known:
            reasons.append("동일 옵션의 표시 가격·추가금 근거 미확인")
        if not length_known:
            reasons.append("총장 수치·근거 미확인 또는 판독 모호")
        if option.get("stock") not in {"available", "sold_out"}:
            reasons.append("구매 가능 여부 미확인")
        if not option.get("size"):
            reasons.append("사이즈 미확인")
        passed = (not failed and price_known and length_known
                  and option.get("stock") == "available" and bool(option.get("size")))
        results.append({"label": label, "status": "pass" if passed else "fail" if failed else "review",
                        "price": total, "length": length, "reason": " / ".join(reasons) or "동일 옵션의 가격·총장·재고 확인"})
    matching = [o["label"] for o in results if o["status"] == "pass"]
    state = "pass" if matching else "review" if not results or any(o["status"] == "review" for o in results) else "fail"
    reason = ("조건 충족: " + ", ".join(matching)) if matching else "확인 가능한 충족 옵션 없음" if state == "fail" else "총장·가격·재고 등 추가 확인 필요"
    return {"status": state, "reason": reason, "matching_options": matching, "options": results}

