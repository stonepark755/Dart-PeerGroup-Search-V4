import io, os, sys, unittest, zipfile
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xlsx import build_workbook
from datetime import date
from test_scenarios import Fake, REPORTS, rows, TODAY
from engine import CompanyRun


class X(unittest.TestCase):
    def test_workbook(self):
        s = {(2025, "11014", "OFS"): rows("OFS", 300, 30, 20, "q3", add={"rev": 900, "op": 90, "ni": 60}),
             (2025, "11011", "OFS"): rows("OFS", 1300, 130, 90, "ar"),
             (2026, "11013", "OFS"): rows("OFS", 310, 31, 21, "q1"),
             (2026, "11012", "CFS"): rows("CFS", 520, 52, 32, "h", add={"rev": 830, "op": 83, "ni": 53}),
             (2026, "11014", "CFS"): rows("CFS", 530, 53, 33, "q3b", add={"rev": 1360, "op": 136, "ni": 86})}
        per = {"revenue": "TTM", "operating_income": "TTM", "net_income": "FY"}
        r = CompanyRun(Fake(REPORTS, s), {"corp_code": "1", "corp_name": "테스트", "stock_code": "000001", "market": "KOSPI"}, TODAY).run(per)
        bad = {"corp_name": "실패사", "stock_code": "000002", "error": "x & <y>", "items": {}}
        data = build_workbook({"searched_at": "2026-11-13T10:00:00", "unit": "원", "results": [r, bad]})
        z = zipfile.ZipFile(io.BytesIO(data))
        for n in z.namelist():
            ET.fromstring(z.read(n))                       # 모든 파트가 올바른 XML
        s1 = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("<v>1760</v>", s1)                   # TTM 매출액 숫자 셀
        self.assertIn("<v>90</v>", s1)                     # 연간 당기순이익 숫자 셀
        self.assertIn("조회 실패", s1)
        self.assertIn("혼합", s1)
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data))
            self.assertEqual(wb.sheetnames, ["재무실적 결과", "분기별 상세", "계산과정"])
        except ImportError:
            pass

if __name__ == "__main__":
    unittest.main()
