import copy
import unittest
from smallcloset.domain import DEFAULT_RULES, evaluate, parse_length, safe_url
from smallcloset.browser import table_candidates


def option(size="S", price=23800, length="68", **overrides):
    row = dict(size=size, color="선택 색상", price=price, extra_price=0, length_raw=length,
               stock="available", price_verified=True, length_verified=True,
               price_evidence="테스트 전용 가격 원문", length_evidence="테스트 전용 총장 원문")
    row.update(overrides)
    return row


def product(*options, **overrides):
    row = dict(url="https://www.sinsangmarket.kr/test-only-item", name="테스트 전용 상품",
               category="상의", gender="남성", options=list(options))
    row.update(overrides)
    return row


class DecisionTests(unittest.TestCase):
    def test_all_named_pants_use_bottom_inclusive_limits(self):
        for name in ['청바지','데님 팬츠','슬랙스','조거팬츠','카고팬츠','반바지','트레이닝 바지','JEANS','PANTS']:
            with self.subTest(name=name):
                p=product(option(price=29300,length='100'),name=name,category='상의')
                self.assertEqual(evaluate(p,DEFAULT_RULES)['status'],'pass')

    def test_denim_fabric_does_not_turn_a_jacket_into_pants(self):
        p=product(option(price=51500,length='70'),name='데님 재킷',category='아우터')
        self.assertEqual(evaluate(p,DEFAULT_RULES)['status'],'pass')
    def test_cardigans_and_zip_hoodies_use_top_price_limit(self):
        for name in ['가디건','카디건','후드집업','후드 집업','남성 후드-집업']:
            with self.subTest(name=name):
                p=product(option(price=23801,length='68'),name=name,category='아우터')
                self.assertEqual(evaluate(p,DEFAULT_RULES)['status'],'fail')

    def test_short_keyword_is_candidate_not_verified_length(self):
        for source in [dict(name='숏기장 가디건'),dict(name='일반 상품',source_excerpt='크롭 디자인'),dict(name='숏 기장 후드 집업')]:
            with self.subTest(source=source):
                result=evaluate(product(option(length=''),**source),DEFAULT_RULES)
                self.assertEqual(result['status'],'review');self.assertEqual(result['matching_options'],[])
                self.assertIn('후보',result['reason'])

    def test_short_keyword_does_not_override_known_excess(self):
        self.assertEqual(evaluate(product(option(length='69'),name='크롭 가디건'),DEFAULT_RULES)['status'],'fail')
    def test_inclusive_boundaries_all_categories(self):
        for category, rule in DEFAULT_RULES.items():
            with self.subTest(category=category):
                d = evaluate(product(option(price=rule["price"], length=str(rule["length"])), category=category), DEFAULT_RULES)
                self.assertEqual(d["status"], "pass")

    def test_price_over(self):
        self.assertEqual(evaluate(product(option(price=23801)), DEFAULT_RULES)["status"], "fail")

    def test_length_over(self):
        self.assertEqual(evaluate(product(option(length="68.1")), DEFAULT_RULES)["status"], "fail")

    def test_missing_total_is_review(self):
        self.assertEqual(evaluate(product(option(length="")), DEFAULT_RULES)["status"], "review")

    def test_only_s_passes(self):
        d = evaluate(product(option(length="67"), option(size="M", length="69")), DEFAULT_RULES)
        self.assertEqual(d["status"], "pass")
        self.assertEqual(d["matching_options"], ["S / 선택 색상"])
        self.assertEqual(d["options"][1]["status"], "fail")

    def test_dont_mix_cheap_large_and_expensive_short(self):
        d = evaluate(product(option(size="S",price=25000,length="67"), option(size="M",price=23000,length="69")), DEFAULT_RULES)
        self.assertEqual(d["status"], "fail")
        self.assertEqual(d["matching_options"], [])

    def test_extra_price_same_option(self):
        self.assertEqual(evaluate(product(option(price=23000, extra_price=800)), DEFAULT_RULES)["status"], "pass")
        self.assertEqual(evaluate(product(option(price=23000, extra_price=801)), DEFAULT_RULES)["status"], "fail")
        self.assertEqual(evaluate(product(option(extra_price=None)), DEFAULT_RULES)["status"], "review")

    def test_unknown_stock_not_available(self):
        self.assertEqual(evaluate(product(option(stock="unknown")), DEFAULT_RULES)["status"], "review")
        self.assertEqual(evaluate(product(option(stock="sold_out")), DEFAULT_RULES)["status"], "fail")

    def test_missing_evidence_or_verification_not_passed(self):
        for field, value in [("price_verified",False),("length_verified",False),("price_evidence",""),("length_evidence","")]:
            with self.subTest(field=field):
                self.assertEqual(evaluate(product(option(**{field:value})), DEFAULT_RULES)["status"], "review")

    def test_inseparable_set_and_gender(self):
        self.assertEqual(evaluate(product(option(),inseparable_set=True), DEFAULT_RULES)["status"], "review")
        self.assertEqual(evaluate(product(option(),gender="미확인"), DEFAULT_RULES)["status"], "review")

    def test_range_and_front_back_use_larger(self):
        self.assertEqual(parse_length("67~69cm"),69)
        self.assertEqual(parse_length("앞 65 / 뒤 68"),68)
        self.assertEqual(parse_length("앞 68cm / 뒤 69cm"),69)
        self.assertEqual(parse_length("뒤 70 / 앞 66"),70)
        self.assertEqual(evaluate(product(option(length="67~69cm")), DEFAULT_RULES)["status"], "fail")

    def test_reject_wrong_dimensions_and_ambiguous_numbers(self):
        for text in ["가슴단면 60", "인심 67", "밑위 30", "허리단면 36", "S 67 M 69", "67/69", "약 67", "67 ± 2", "27 inch", "670mm", "68 이상", "1000", "NaN", "-1", "0"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_length(text))

    def test_no_evidence_does_not_change_original(self):
        p=product(option());before=copy.deepcopy(p);evaluate(p,DEFAULT_RULES);self.assertEqual(p,before)


class URLTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(safe_url("https://www.sinsangmarket.kr/item/?b=2&utm_source=x&a=1#top"),"https://www.sinsangmarket.kr/item?a=1&b=2")

    def test_no_credentials_other_site_or_localhost(self):
        for url in ["https://user:secret@www.sinsangmarket.kr/item", "http://www.sinsangmarket.kr", "https://127.0.0.1", "https://example.com", "https://www.sinsangmarket.kr/a?session=x", "https://www.sinsangmarket.kr/a?access_token=x"]:
            with self.subTest(url=url),self.assertRaises(ValueError):safe_url(url)


class TableTests(unittest.TestCase):
    def cells(self, rows):
        return [[dict(text=str(c),span=1,rows=1) for c in row] for row in rows]

    def test_vertical_total_not_chest(self):
        rows=self.cells([["사이즈","가슴단면","총장(cm)"],["S",60,67],["M",62,69]])
        result=table_candidates([rows]);self.assertEqual([o["length_raw"] for o in result],["67","69"])
        self.assertFalse(any(o["length_verified"] for o in result))

    def test_horizontal(self):
        result=table_candidates([self.cells([["SIZE","S","M"],["가슴",60,62],["총장",67,69]])])
        self.assertEqual([(o["size"],o["length_raw"]) for o in result],[("S","67"),("M","69")])

    def test_exact_gijang_header_and_inseam_are_distinct(self):
        result=table_candidates([self.cells([["사이즈","인심","기장"],["S",65,98]])])
        self.assertEqual(result[0]['length_raw'],'98')

    def test_merged_or_duplicate_headers_refused(self):
        rows=self.cells([["SIZE","총장"],["S",67]]);rows[1][1]["span"]=2
        self.assertEqual(table_candidates([rows]),[])
        self.assertEqual(table_candidates([self.cells([["SIZE","총장","총장"],["S",67,69]])]),[])

