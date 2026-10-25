"""Interpret observed standard Product/Offer data, never hypothetical site APIs."""
import re
from .browser import table_candidates
from .domain import DEFAULT_RULES, classify_category, parse_length


def explicit_minimum(label):
    if "중복 링크" in (label or ""):
        return None
    amounts = re.findall(r"(?<![\d,.])(\d[\d,]*)\s*원", label or "")
    if len(amounts) == 1 and re.search(r"최저|부터", label or ""):
        value = int(amounts[0].replace(",", ""))
        return value if 0 <= value <= 100000000 else None
    return None


def size_key(value):
    return re.sub(r"\s+", "", value).upper()


def build_automatic_product(observed, category):
    name = observed.get("name") or observed.get("title") or "상품명 확인 필요"
    if category not in DEFAULT_RULES:
        actual_category = observed.get("site_category", "")
        if re.search(r"하의|바지|팬츠|\bpants\b|\bjeans\b", actual_category, re.I):
            category = "바지"
        elif re.search(r"상의|\btops?\b", actual_category, re.I):
            category = "상의"
        elif re.search(r"아우터|\bouterwear\b", actual_category, re.I):
            category = "아우터"
        else:
            category = classify_category(actual_category, category)
    rows = {}
    tables = observed.get("tables", [])
    units = observed.get("table_units", [])
    for index, table in enumerate(tables):
        candidates = table_candidates([table])
        labels = [cell["text"] for row in table for cell in row if re.search(r"총장|총기장|^기장", cell["text"])]
        explicit_unit = any(re.search(r"cm|㎝|센티미터", label, re.I) for label in labels)
        if index < len(units):
            explicit_unit = explicit_unit or bool(re.search(r"단위\s*[:：]?\s*(?:cm|㎝)", units[index], re.I))
        for option in candidates:
            key = size_key(option["size"])
            length = parse_length(option["length_raw"])
            record = {**option, "length_verified": bool(explicit_unit and length is not None)}
            if key in rows and rows[key]["length_raw"] != record["length_raw"]:
                record["length_verified"] = False
                record["length_evidence"] += " / 같은 사이즈의 표 수치가 서로 달라 확인 필요"
                record["conflict"] = True
            if rows.get(key, {}).get("conflict"):
                record["length_verified"] = False; record["conflict"] = True
            rows[key] = record
    options = []
    for offer in observed.get("offers", []):
        size = offer.get("size", "")
        measured = rows.get(size_key(size), {})
        price = offer.get("price")
        text = offer.get("visible_price_text", "")
        numbers = [int(n.replace(",", "")) for n in re.findall(r"(?<![\d,.])(\d[\d,]*)\s*원", text)]
        known = (bool(size) and isinstance(price, (int, float)) and not isinstance(price, bool)
                 and offer.get("currency") == "KRW" and price in numbers)
        raw_availability = offer.get("availability", "")
        availability = ""
        for status in ["InStock", "OutOfStock", "SoldOut", "Discontinued", "PreOrder", "BackOrder"]:
            if raw_availability in {status, "https://schema.org/" + status, "http://schema.org/" + status}:
                availability = status
                break
        stock = "available" if availability == "InStock" else "sold_out" if availability in {"OutOfStock", "SoldOut", "Discontinued"} else "unknown"
        options.append({"size": size, "color": offer.get("color", ""), "price": price,
                        "extra_price": 0 if known else None, "price_verified": known, "stock": stock,
                        "price_evidence": ("해당 사이즈 Product/Offer 최종가격: " + str(price) + " KRW / 표시 원문: " + text + " / 재고 원문: " + availability)[:2000],
                        "length_raw": measured.get("length_raw", ""), "length_verified": measured.get("length_verified", False),
                        "length_evidence": measured.get("length_evidence", "총장·기장에 해당하는 사이즈 표 수치 미확인")})
    existing = {size_key(o["size"]) for o in options}
    options += [{key: value for key, value in row.items() if key != "conflict"} for size, row in rows.items() if size not in existing]
    note = "자동 수집. 상품명 근거: " + observed.get("name_source", "페이지 제목 후보")
    if not observed.get("offers"):
        note += " / 사이즈별 가격·재고의 명시적 구조화 근거 없음: 자동 통과시키지 않음"
    if observed.get("detail_note"):
        note += " / " + observed["detail_note"]
    return {"url": observed["url"], "name": name[:300], "supplier": observed.get("supplier", ""),
            "category": classify_category(name, category), "gender": "남성", "options": options[:200],
            "image_url": observed.get("image_url", ""), "capture_note": note[:2000],
            "source_excerpt": observed.get("selection", "")[:1500], "source_type": "chrome_auto",
            "ocr_notes": observed.get("ocr_notes", "")[:20000], "evidence_images": observed.get("evidence_images", [])[:4]}
