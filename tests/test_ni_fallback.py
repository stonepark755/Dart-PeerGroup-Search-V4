"""연결 당기순이익 추출 순서 검증: 지배주주 순이익 → 지배주주 총포괄이익 → 연결 당기순이익 전체.
한텍(귀속 항목이 '총포괄이익'만 있음), 우양에이치씨(귀속 항목 없음) 실제 화면 구조를 재현."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dart_web as W
from engine import find_item, CompanyRun
from test_scenarios import Fake, REPORTS, TODAY

HEAD = ("<p>연결 포괄손익계산서</p><p>제 29 기 반기 2026.01.01 부터 2026.06.30 까지</p><p>(단위 : 원)</p>"
        "<table><tr><td rowspan=2></td><td colspan=2>제 29 기 반기</td><td colspan=2>제 28 기 반기</td></tr>"
        "<tr><td>3개월</td><td>누적</td><td>3개월</td><td>누적</td></tr>")

HANTEC = HEAD + """
<tr><td>매출액 (주26,27,28)</td><td>46,339,420,661</td><td>93,364,808,342</td><td>49,313,953,657</td><td>83,054,990,319</td></tr>
<tr><td>매출원가 (주21)</td><td>30,246,840,498</td><td>65,364,447,427</td><td>28,579,320,172</td><td>54,902,095,657</td></tr>
<tr><td>영업이익</td><td>10,537,133,379</td><td>18,232,072,597</td><td>18,172,050,118</td><td>20,306,350,001</td></tr>
<tr><td>법인세비용차감전순이익</td><td>12,301,710,042</td><td>22,694,416,871</td><td>13,724,272,933</td><td>15,687,930,377</td></tr>
<tr><td>반기순이익</td><td>8,975,739,322</td><td>17,013,234,251</td><td>13,840,495,892</td><td>15,665,664,776</td></tr>
<tr><td>반기총포괄이익</td><td>8,524,853,347</td><td>16,576,768,210</td><td>13,626,919,653</td><td>15,487,875,937</td></tr>
<tr><td>총포괄이익의 귀속</td><td></td><td></td><td></td><td></td></tr>
<tr><td>&nbsp;&nbsp;지배기업의 소유주지분 총포괄이익</td><td>8,524,853,347</td><td>16,576,768,210</td><td>13,626,919,653</td><td>15,487,875,937</td></tr>
<tr><td>&nbsp;&nbsp;비지배지분 총포괄이익</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>
<tr><td>주당이익</td><td></td><td></td><td></td><td></td></tr>
<tr><td>기본주당이익 (단위 : 원)</td><td>807</td><td>1,530</td><td>1,245</td><td>1,531</td></tr></table>"""

WOOYANG = HEAD + """
<tr><td>수익</td><td>19,836,790,348</td><td>50,993,368,592</td><td>27,000,711,969</td><td>57,037,580,489</td></tr>
<tr><td>영업이익(손실)</td><td>2,014,872,621</td><td>5,026,201,386</td><td>2,505,003,159</td><td>5,863,822,151</td></tr>
<tr><td>반기순이익(손실)</td><td>2,619,648,449</td><td>7,100,396,341</td><td>(194,584,376)</td><td>(2,167,457,637)</td></tr>
<tr><td>총포괄손익</td><td>2,619,648,449</td><td>7,100,396,341</td><td>(194,584,376)</td><td>(2,167,457,637)</td></tr>
<tr><td>주당이익</td><td></td><td></td><td></td><td></td></tr>
<tr><td>기본주당이익(손실) (단위 : 원)</td><td>177</td><td>480</td><td>(13)</td><td>(153)</td></tr></table>"""

TIER1 = HEAD + """
<tr><td>매출액</td><td>1,000</td><td>3,000</td><td>900</td><td>2,700</td></tr>
<tr><td>영업이익</td><td>100</td><td>300</td><td>90</td><td>270</td></tr>
<tr><td>당기순이익</td><td>80</td><td>240</td><td>70</td><td>210</td></tr>
<tr><td>총포괄이익</td><td>85</td><td>250</td><td>75</td><td>220</td></tr>
<tr><td>당기순이익의 귀속</td><td></td><td></td><td></td><td></td></tr>
<tr><td>지배기업의 소유주지분</td><td>70</td><td>210</td><td>60</td><td>180</td></tr>
<tr><td>비지배지분</td><td>10</td><td>30</td><td>10</td><td>30</td></tr>
<tr><td>총포괄이익의 귀속</td><td></td><td></td><td></td><td></td></tr>
<tr><td>지배기업의 소유주지분</td><td>75</td><td>220</td><td>65</td><td>190</td></tr>
<tr><td>비지배지분</td><td>10</td><td>30</td><td>10</td><td>30</td></tr></table>"""

CI_ONLY_UNLABELED = HEAD + """
<tr><td>매출액</td><td>1,000</td><td>3,000</td><td>900</td><td>2,700</td></tr>
<tr><td>영업이익</td><td>100</td><td>300</td><td>90</td><td>270</td></tr>
<tr><td>당기순이익</td><td>80</td><td>240</td><td>70</td><td>210</td></tr>
<tr><td>총포괄이익의 귀속</td><td></td><td></td><td></td><td></td></tr>
<tr><td>지배기업의 소유주지분</td><td>75</td><td>220</td><td>65</td><td>190</td></tr></table>"""


def rows_of(html):
    r, _, _ = W.extract_statements(W.tokenize(html), "R")
    return r


class N(unittest.TestCase):
    def test_hantec_uses_total_net_income_before_comprehensive(self):
        rows = rows_of(HANTEC)
        self.assertTrue(all(r["fs"] == "CFS" for r in rows))
        f = find_item(rows, "net_income", "CFS")                       # 새 순서: 연결 당기순이익 전체가 총포괄이익보다 우선
        self.assertEqual(f["tier"], 2)
        self.assertEqual((f["cur"], f["add"]), (8975739322, 17013234251))
        self.assertEqual(f["account_nm"], "반기순이익")
        c = find_item(rows, "net_income", "CFS", tier=3)               # 3순위: 지배기업 소유주지분 총포괄이익
        self.assertEqual((c["cur"], c["add"]), (8524853347, 16576768210))
        self.assertIn("총포괄이익", c["account_nm"])
        self.assertEqual(find_item(rows, "revenue", "CFS")["cur"], 46339420661)      # (주26,27,28) 제거
        self.assertEqual(find_item(rows, "operating_income", "CFS")["add"], 18232072597)

    def test_wooyang_uses_total_net_income(self):
        rows = rows_of(WOOYANG)
        f = find_item(rows, "net_income", "CFS")
        self.assertEqual(f["tier"], 2)
        self.assertEqual((f["cur"], f["add"], f["prev_add"]), (2619648449, 7100396341, -2167457637))
        self.assertEqual(find_item(rows, "revenue", "CFS")["cur"], 19836790348)

    def test_tier1_preferred_and_sections_disambiguate(self):
        f = find_item(rows_of(TIER1), "net_income", "CFS")
        self.assertEqual((f["tier"], f["cur"]), (1, 70))             # 총포괄 귀속(75)이 아니라 순이익 귀속(70)

    def test_unlabeled_name_under_ci_header_is_comprehensive_not_tier1(self):
        rows = rows_of(CI_ONLY_UNLABELED)
        f = find_item(rows, "net_income", "CFS")
        self.assertEqual((f["tier"], f["cur"]), (2, 80))               # 순이익 귀속이 아니므로 1순위 아님 → 연결 당기순이익 전체
        self.assertEqual(find_item(rows, "net_income", "CFS", tier=3)["cur"], 75)   # 총포괄 귀속은 3순위

    def test_explicit_tier_request(self):
        rows = rows_of(TIER1)
        self.assertEqual(find_item(rows, "net_income", "CFS", tier=2)["cur"], 80)
        self.assertEqual(find_item(rows, "net_income", "CFS", tier=3)["cur"], 75)

    # ---- 엔진 전체: 대체기준 표시와 동일 기준 차감
    @staticmethod
    def _row(sj, nm, cur, add="", prev_add="", rn="r"):
        return {"sj_div": sj, "account_id": None, "account_nm": nm, "rcept_no": rn,
                "thstrm_amount": str(cur), "thstrm_add_amount": str(add), "frmtrm_add_amount": str(prev_add)}

    def _stmt(self, ni_rows, rev=100, op=10, add=False, rn="r"):
        a = (lambda v: v * 3) if add else (lambda v: "")
        return ([self._row("CIS", "매출액", rev, a(rev), rn=rn), self._row("CIS", "영업이익", op, a(op), rn=rn)]
                + [self._row("CIS", n, c, a(c) if add else "", rn=rn) for n, c in ni_rows])

    def test_engine_marks_fallback_and_keeps_total_net_income(self):
        s = {}
        tot = [("반기순이익(손실)", 30)]
        for (y, rc) in [(2025, "11014"), (2025, "11011"), (2026, "11013"), (2026, "11012"), (2026, "11014")]:
            s[(y, rc, "CFS")] = self._stmt(tot, add=rc in ("11014", "11012"))
        s[(2025, "11011", "CFS")] = self._stmt(tot, rev=500, op=50)
        s[(2025, "11011", "CFS")][2]["thstrm_amount"] = "150"
        r = CompanyRun(Fake(REPORTS, s), {"corp_code": "1", "corp_name": "t", "stock_code": "1"}, TODAY).run(
            {"revenue": "TTM", "operating_income": "TTM", "net_income": "TTM"})
        ni = r["ttm"]["net_income"]
        self.assertEqual(ni["status"], "verified")
        self.assertTrue(ni["fallback"])
        q = r["quarters"][1]["items"]["net_income"]
        self.assertEqual((q["tier"], q["fallback"]), (2, True))
        self.assertIn("연결 당기순이익 전체", q["ni_basis"])
        self.assertTrue(any("당기순이익 대체기준" in n for n in r["notes"]))

    def test_subtraction_never_mixes_tiers(self):
        # 반기: 단독 3개월 금액 없이 누적만 공시 + 지배주주 순이익(1순위) 존재 / 1분기: 연결 당기순이익 전체(2순위)만 존재
        # → 추출기준이 달라 '반기 누적 - 1분기 누적' 차감을 하면 안 된다.
        half = self._stmt([("당기순이익의 귀속", ""), ("지배기업 소유주 귀속 당기순이익", 60), ("당기순이익", 90)])
        s = {(2025, "11014", "CFS"): self._stmt([("당기순이익", 30)], add=True),
             (2025, "11011", "CFS"): self._stmt([("당기순이익", 30)]),
             (2026, "11013", "CFS"): self._stmt([("당기순이익", 30)]),
             (2026, "11012", "CFS"): half,
             (2026, "11014", "CFS"): self._stmt([("당기순이익", 30)], add=True)}
        r = CompanyRun(Fake(REPORTS, s), {"corp_code": "1", "corp_name": "t", "stock_code": "1"}, TODAY).run(
            {"revenue": "TTM", "operating_income": "TTM", "net_income": "TTM"})
        q2 = r["quarters"][2]["items"]["net_income"]
        self.assertEqual(q2["status"], "unverified")
        self.assertIsNone(r["ttm"]["net_income"]["value"])

    def test_subtraction_same_tier_ok(self):
        s = {(2025, "11014", "CFS"): self._stmt([("당기순이익", 30)], add=True),
             (2025, "11011", "CFS"): self._stmt([("당기순이익", 30)]),
             (2026, "11013", "CFS"): self._stmt([("당기순이익", 30)]),
             (2026, "11012", "CFS"): self._stmt([("당기순이익", 70)]),        # 누적만, 2순위
             (2026, "11014", "CFS"): self._stmt([("당기순이익", 30)], add=True)}
        r = CompanyRun(Fake(REPORTS, s), {"corp_code": "1", "corp_name": "t", "stock_code": "1"}, TODAY).run(
            {"revenue": "TTM", "operating_income": "TTM", "net_income": "TTM"})
        q2 = r["quarters"][2]["items"]["net_income"]
        self.assertEqual((q2["status"], q2["value"], q2["method"]), ("verified", 40, "calc"))   # 70 - 30

    def test_excel_mentions_fallback(self):
        import io, zipfile
        from xlsx import build_workbook
        tot = [("반기순이익(손실)", 30)]
        s = {}
        for (y, rc) in [(2025, "11014"), (2025, "11011"), (2026, "11013"), (2026, "11012"), (2026, "11014")]:
            s[(y, rc, "CFS")] = self._stmt(tot, add=rc in ("11014", "11012"))
        s[(2025, "11011", "CFS")][2]["thstrm_amount"] = "150"
        r = CompanyRun(Fake(REPORTS, s), {"corp_code": "1", "corp_name": "t", "stock_code": "1", "market": "KOSDAQ"}, TODAY).run(
            {"revenue": "TTM", "operating_income": "TTM", "net_income": "TTM"})
        z = zipfile.ZipFile(io.BytesIO(build_workbook({"results": [r], "unit": "원"})))
        all_xml = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("xl/worksheets"))
        self.assertIn("[대체]", all_xml)
        self.assertIn("대체기준 포함", all_xml)


if __name__ == "__main__":
    unittest.main()
