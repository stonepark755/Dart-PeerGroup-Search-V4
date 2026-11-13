"""업무지시서 13장 시나리오(A, C, D, E, F)를 가짜 DART 클라이언트로 검증한다.
실행:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import CompanyRun  # noqa: E402

TODAY = date(2026, 11, 13)
M = 1_000_000


def rows(fs, rev, op, ni, rcept, add=None, prev_add=None):
    """add/prev_add: dict(item -> 금액). ni 는 연결이면 지배주주 순이익(총 당기순이익은 더 크게 따로 넣음)."""
    add, prev_add = add or {}, prev_add or {}

    def row(sj, aid, nm, key, cur):
        return {"sj_div": sj, "account_id": aid, "account_nm": nm, "rcept_no": rcept,
                "thstrm_amount": str(cur),
                "thstrm_add_amount": str(add[key]) if key in add else "",
                "frmtrm_add_amount": str(prev_add[key]) if key in prev_add else ""}
    out = [row("IS", "ifrs-full_Revenue", "매출액", "rev", rev),
           row("IS", "dart_OperatingIncomeLoss", "영업이익", "op", op)]
    if fs == "CFS":
        out.append(row("IS", "ifrs-full_ProfitLoss", "당기순이익", "ni_total", ni + 7 * M))
        out.append(row("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent",
                       "지배기업 소유주지분", "ni", ni))
        out.append(row("IS", "ifrs-full_ProfitLossAttributableToNoncontrollingInterests",
                       "비지배지분", "nci", 7 * M))
    else:
        out.append(row("IS", "ifrs-full_ProfitLoss", "당기순이익", "ni", ni))
    return out


class Fake:
    def __init__(self, reports, stmts, has_cons=None):
        self.reports, self.stmts, self.has_cons = reports, stmts, has_cons or {}

    def company(self, cc):
        return {"acc_mt": "12", "corp_cls": "Y"}

    def list_periodic(self, cc, b, e):
        return [{"report_nm": n, "rcept_no": r, "rcept_dt": "20260101"} for n, r in self.reports]

    def list_major(self, cc, b, e):
        return [{"report_nm": "타법인주식및출자증권취득결정", "rcept_no": "20260510000001", "rcept_dt": "20260510"}]

    def statement(self, cc, y, rc, fs, rcept_no=None):
        return self.stmts.get((y, rc, fs))

    def doc_has_consolidated(self, rn):
        return self.has_cons.get(rn, False)


def run(fake, periods=None):
    periods = periods or {"revenue": "TTM", "operating_income": "TTM", "net_income": "TTM"}
    return CompanyRun(fake, {"corp_code": "00000001", "corp_name": "테스트", "stock_code": "000001"}, TODAY).run(periods)


REPORTS = [("사업보고서 (2025.12)", "20260320000001"), ("분기보고서 (2025.03)", "20250515000001"),
           ("반기보고서 (2025.06)", "20250814000001"), ("분기보고서 (2025.09)", "20251114000001"),
           ("분기보고서 (2026.03)", "20260515000001"), ("반기보고서 (2026.06)", "20260814000001"),
           ("분기보고서 (2026.09)", "20261113000001")]
R = dict((n, r) for n, r in REPORTS)


class T(unittest.TestCase):
    def test_A_all_consolidated(self):
        s = {}
        # 연결: 3개 분기 보고서는 3개월(thstrm)+누적(add) 제공
        s[(2025, "11014", "CFS")] = rows("CFS", 300, 30, 20, "q3_25", add={"rev": 900, "op": 90, "ni": 60, "ni_total": 67, "nci": 7})
        s[(2025, "11011", "CFS")] = rows("CFS", 1300, 130, 90, "ar_25")   # 연간
        s[(2026, "11013", "CFS")] = rows("CFS", 310, 31, 21, "q1_26")
        s[(2026, "11012", "CFS")] = rows("CFS", 320, 32, 22, "h_26", add={"rev": 630, "op": 63, "ni": 43})
        s[(2026, "11014", "CFS")] = rows("CFS", 330, 33, 23, "q3_26", add={"rev": 960, "op": 96, "ni": 66})
        r = run(Fake(REPORTS, s))
        qs = r["quarters"]
        self.assertEqual([q["fs_div"] for q in qs], ["CFS"] * 4)
        # 4Q25 = 1300-900 = 400
        self.assertEqual(qs[0]["items"]["revenue"]["value"], 400)
        self.assertEqual(r["ttm"]["revenue"]["value"], 400 + 310 + 320 + 330)
        # 순이익은 지배주주 귀속분 (연결 당기순이익 전체 X)
        self.assertEqual(qs[1]["items"]["net_income"]["value"], 21)
        self.assertEqual(r["ttm"]["net_income"]["basis"], "연결")
        self.assertFalse(r["basis_changes"])

    def test_C_individual_to_consolidated_and_E_midyear(self):
        s = {}
        s[(2025, "11014", "OFS")] = rows("OFS", 300, 30, 20, "q3_25", add={"rev": 900, "op": 90, "ni": 60})
        s[(2025, "11011", "OFS")] = rows("OFS", 1300, 130, 90, "ar_25")
        s[(2026, "11013", "OFS")] = rows("OFS", 310, 31, 21, "q1_26")
        # 반기보고서부터 연결 (별도도 함께 공시 → 연결이 주 재무제표)
        s[(2026, "11012", "CFS")] = rows("CFS", 520, 52, 32, "h_26", add={"rev": 830, "op": 83, "ni": 53})
        s[(2026, "11012", "OFS")] = rows("OFS", 320, 32, 22, "h_26", add={"rev": 630, "op": 63, "ni": 43})
        s[(2026, "11014", "CFS")] = rows("CFS", 530, 53, 33, "q3_26", add={"rev": 1360, "op": 136, "ni": 86})
        r = run(Fake(REPORTS, s))
        qs = r["quarters"]
        self.assertEqual([q["fs_div"] for q in qs], ["OFS", "OFS", "CFS", "CFS"])
        # 시나리오 E: 2Q 는 반기보고서의 2분기 단독 '연결' 값 (830-310 같은 기준 불일치 차감 아님)
        q2 = qs[2]["items"]["revenue"]
        self.assertEqual((q2["value"], q2["method"]), (520, "direct"))
        self.assertEqual(qs[2]["items"]["net_income"]["value"], 32)   # 지배주주
        self.assertEqual(qs[1]["items"]["net_income"]["value"], 21)   # 개별 당기순이익
        self.assertEqual(r["ttm"]["revenue"]["value"], 400 + 310 + 520 + 530)
        self.assertEqual(r["ttm"]["revenue"]["basis"], "혼합(연결·개별)")
        self.assertTrue(r["mixed_flag"])
        ch = r["basis_changes"]
        self.assertEqual(len(ch), 1)
        self.assertEqual((ch[0]["from"], ch[0]["to"], ch[0]["first_quarter"]), ("OFS", "CFS", "2026년 2Q"))
        self.assertTrue(any("혼재" in n for n in r["notes"]))

    def test_D_consolidated_to_individual(self):
        s = {}
        s[(2025, "11014", "CFS")] = rows("CFS", 300, 30, 20, "q3_25", add={"rev": 900, "op": 90, "ni": 60})
        s[(2025, "11011", "CFS")] = rows("CFS", 1300, 130, 90, "ar_25")
        s[(2026, "11013", "CFS")] = rows("CFS", 310, 31, 21, "q1_26")
        s[(2026, "11012", "OFS")] = rows("OFS", 320, 32, 22, "h_26", add={"rev": 630, "op": 63, "ni": 43})
        s[(2026, "11014", "OFS")] = rows("OFS", 330, 33, 23, "q3_26", add={"rev": 960, "op": 96, "ni": 66})
        r = run(Fake(REPORTS, s))
        self.assertEqual([q["fs_div"] for q in r["quarters"]], ["CFS", "CFS", "OFS", "OFS"])
        self.assertEqual(r["ttm"]["revenue"]["value"], 400 + 310 + 320 + 330)
        self.assertEqual(r["basis_changes"][0]["to"], "OFS")

    def test_F_q4_basis_change_uses_comparative(self):
        s = {}
        s[(2025, "11014", "OFS")] = rows("OFS", 300, 30, 20, "q3_25", add={"rev": 900, "op": 90, "ni": 60})
        s[(2025, "11011", "CFS")] = rows("CFS", 2000, 200, 150, "ar_25")      # 연간만 연결
        s[(2026, "11013", "CFS")] = rows("CFS", 510, 51, 41, "q1_26")
        s[(2026, "11012", "CFS")] = rows("CFS", 520, 52, 42, "h_26", add={"rev": 1030, "op": 103, "ni": 83})
        s[(2026, "11014", "CFS")] = rows("CFS", 530, 53, 43, "q3_26",
                                         add={"rev": 1560, "op": 156, "ni": 126},
                                         prev_add={"rev": 1500, "op": 150, "ni": 110})   # 전기 3Q 누적(연결 재작성)
        r = run(Fake(REPORTS, s))
        q4 = r["quarters"][0]["items"]["revenue"]
        # 연간 연결(2000) - 3Q 누적 '개별'(900) 을 차감하면 안 된다 → 연결 비교정보(1500) 사용
        self.assertEqual(q4["value"], 500)
        self.assertEqual(q4["method"], "calc")
        self.assertIn("1,500", q4["formula"])
        self.assertNotIn("900", q4["formula"])

    def test_F_unverifiable_gives_no_ttm(self):
        s = {}
        s[(2025, "11014", "OFS")] = rows("OFS", 300, 30, 20, "q3_25", add={"rev": 900, "op": 90, "ni": 60})
        s[(2025, "11011", "CFS")] = rows("CFS", 2000, 200, 150, "ar_25")
        s[(2026, "11013", "CFS")] = rows("CFS", 510, 51, 41, "q1_26")
        s[(2026, "11012", "CFS")] = rows("CFS", 520, 52, 42, "h_26", add={"rev": 1030, "op": 103, "ni": 83})
        s[(2026, "11014", "CFS")] = rows("CFS", 530, 53, 43, "q3_26", add={"rev": 1560, "op": 156, "ni": 126})  # 비교정보 없음
        r = run(Fake(REPORTS, s))
        self.assertEqual(r["quarters"][0]["items"]["revenue"]["status"], "unverified")
        for i in ("revenue", "operating_income", "net_income"):
            self.assertIsNone(r["ttm"][i]["value"])
            self.assertNotEqual(r["ttm"][i]["status"], "verified")

    def test_cfs_api_missing_but_document_has_consolidated(self):
        s = {(2025, "11011", "OFS"): rows("OFS", 1300, 130, 90, "ar_25")}
        fake = Fake(REPORTS, s, has_cons={R["사업보고서 (2025.12)"]: True})
        r = run(fake, {"revenue": "FY", "operating_income": "FY", "net_income": "FY"})
        self.assertEqual(r["items"]["revenue"]["status"], "unverified")   # 개별로 단정하지 않음
        self.assertIsNone(r["items"]["revenue"]["value"])

    def test_fy_individual(self):
        s = {(2025, "11011", "OFS"): rows("OFS", 1300, 130, 90, "ar_25")}
        r = run(Fake(REPORTS, s), {"revenue": "FY", "operating_income": "FY", "net_income": "FY"})
        self.assertEqual(r["items"]["net_income"]["value"], 90)
        self.assertEqual(r["items"]["revenue"]["basis"], "개별")
        self.assertEqual(r["items"]["revenue"]["period_label"], "2025년 연간")


if __name__ == "__main__":
    unittest.main()
