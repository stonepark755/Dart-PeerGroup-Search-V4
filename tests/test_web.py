"""스크래핑 파서와 원 단위 환산 테스트 (합성 HTML 사용 - 실제 DART 페이지로는 별도 점검 필요)."""
import os, sys, unittest, tempfile
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dart_web as W
from dart import Store
from engine import CompanyRun

Q3_CIS = """
<p>연결 포괄손익계산서</p><p>제 56 기 3분기</p>
<table><tr><td>(단위 : 백만원)</td></tr></table>
<table>
<tr><td rowspan=2>과목</td><td rowspan=2>주석</td><td colspan=2>제 56 기 3분기</td><td colspan=2>제 55 기 3분기</td></tr>
<tr><td>3개월</td><td>누적</td><td>3개월</td><td>누적</td></tr>
<tr><td>Ⅰ. 매출액</td><td>5</td><td>1,000</td><td>3,000</td><td>900</td><td>2,700</td></tr>
<tr><td>Ⅲ. 영업이익(손실)</td><td></td><td>(100)</td><td>300</td><td>90</td><td>270</td></tr>
<tr><td>Ⅷ. 당기순이익(손실)</td><td></td><td>70</td><td>210</td><td>60</td><td>180</td></tr>
<tr><td>지배기업의 소유주에게 귀속되는 당기순이익</td><td></td><td>60</td><td>200</td><td>50</td><td>170</td></tr>
<tr><td>비지배지분</td><td></td><td>10</td><td>10</td><td>10</td><td>10</td></tr>
</table>"""
ANNUAL_OFS = """
<p>손익계산서</p><table><tr><td>(단위 : 천원)</td></tr></table>
<table><tr><td>과목</td><td>주석</td><td>제 56 기</td><td>제 55 기</td></tr>
<tr><td>매출액</td><td>5</td><td>12,345</td><td>10,000</td></tr>
<tr><td>영업이익</td><td></td><td>1,000</td><td>900</td></tr>
<tr><td>당기순이익</td><td></td><td>-500</td><td>800</td></tr></table>"""
NOUNIT = "<p>손익계산서</p><table><tr><td>과목</td><td>제 1 기</td><td>제 0 기</td></tr><tr><td>매출액</td><td>1,000</td><td>900</td></tr></table>"


class P(unittest.TestCase):
    def test_4col_million_to_won(self):
        rows, miss, _ = W.extract_statements(W.tokenize(Q3_CIS), "R1")
        self.assertFalse(miss)
        by = {r["account_nm"]: r for r in rows}
        self.assertEqual(by["매출액"]["thstrm_amount"], "1000000000")        # 1,000백만원 → 1,000,000,000원
        self.assertEqual(by["매출액"]["thstrm_add_amount"], "3000000000")
        self.assertEqual(by["매출액"]["frmtrm_add_amount"], "2700000000")
        self.assertEqual(by["영업이익(손실)"]["thstrm_amount"], "-100000000")   # 괄호 = 음수
        self.assertEqual(by["매출액"]["unit"], "백만원")

    def test_2col_thousand_and_negative(self):
        rows, _, _ = W.extract_statements(W.tokenize(ANNUAL_OFS), "R2")
        by = {r["account_nm"]: r for r in rows}
        self.assertEqual(by["매출액"]["thstrm_amount"], "12345000")          # 12,345천원 → 12,345,000원
        self.assertEqual(by["당기순이익"]["thstrm_amount"], "-500000")
        self.assertEqual(by["매출액"]["thstrm_add_amount"], "")

    def test_unit_missing_is_not_guessed(self):
        rows, miss, _ = W.extract_statements(W.tokenize(NOUNIT), "R3")
        self.assertEqual(rows, [])
        self.assertTrue(miss)

    def test_toc_and_node_filter(self):
        main = """node1['text'] = "2. 연결재무제표"; node1['dcmNo'] = "111"; node1['eleId'] = "7"; node1['offset'] = "1"; node1['length'] = "2"; node1['dtd'] = "dart4.xsd";
node2['text'] = "3. 연결재무제표 주석"; node2['dcmNo'] = "111"; node2['eleId'] = "8";
node3['text'] = "4. 재무제표"; node3['dcmNo'] = "111"; node3['eleId'] = "9";
node4['text'] = "1. 요약재무정보"; node4['dcmNo'] = "111"; node4['eleId'] = "6";"""
        t = [n["text"] for n in W.parse_toc(main) if W.is_fs_node(n["text"])]
        self.assertEqual(t, ["2. 연결재무제표", "4. 재무제표"])

    def test_search_parse(self):
        html = '<table><tr><td>1</td><td><a onclick="x">테스트전자</a></td><td><a href="/dsaf001/main.do?rcpNo=20260515000001">분기보고서 (2026.03)</a></td><td>테스트전자</td><td>2026.05.15</td></tr></table>'
        r = W.parse_search(html)
        self.assertEqual((r[0]["rcept_no"], r[0]["report_nm"], r[0]["company"], r[0]["rcept_dt"]),
                         ("20260515000001", "분기보고서 (2026.03)", "테스트전자", "20260515"))

    def test_end_to_end_with_stub(self):
        class Stub(W.WebClient):
            def _get(self, url, data=None, ttl=None, encoding="utf-8", valid=None):
                if "corpList" in url:
                    return ('<table><tr><th>회사명</th><th>시장구분</th><th>종목코드</th><th>결산월</th></tr>'
                            '<tr><td>테스트전자</td><td>유가증권</td><td>000001</td><td>12월</td></tr></table>')
                if "detailSearch" in url:
                    return ('<table><tr><td>1</td><td>테스트전자</td><td><a href="/dsaf001/main.do?rcpNo=20260320000001">사업보고서 (2025.12)</a></td><td>x</td><td>2026.03.20</td></tr></table>')
                if "main.do" in url:
                    return "node1['text'] = \"4. 재무제표\"; node1['dcmNo'] = \"1\"; node1['eleId'] = \"9\"; node1['offset']=\"0\"; node1['length']=\"1\"; node1['dtd']=\"dart4.xsd\";"
                return ANNUAL_OFS
        with tempfile.TemporaryDirectory() as d:
            c = Stub(Store(os.path.join(d, "t.sqlite")), min_interval=0)
            run = CompanyRun(c, {"corp_code": "000001", "corp_name": "테스트전자", "stock_code": "000001"}, date(2026, 11, 13))
            r = run.run({"revenue": "FY", "operating_income": "FY", "net_income": "FY"})
        self.assertEqual(r["items"]["revenue"]["value"], 12345000)      # 원 단위
        self.assertEqual(r["items"]["net_income"]["value"], -500000)
        self.assertEqual(r["items"]["revenue"]["basis"], "개별")
        self.assertEqual(r["items"]["revenue"]["sources"][0]["unit"], "천원")

    def test_title_decides_basis_and_notes_tables_rejected(self):
        # 같은 문서에 연결/별도 손익계산서, 그리고 주석의 부문정보 표(영업이익·순이익 없음)
        doc = ("<p>연결 손익계산서</p><p>(단위 : 원)</p><table><tr><td>과목</td><td>제 1 기</td><td>제 0 기</td></tr>"
               "<tr><td>매출액</td><td>1,000</td><td>900</td></tr><tr><td>영업이익</td><td>100</td><td>90</td></tr>"
               "<tr><td>지배기업 소유주지분</td><td>70</td><td>60</td></tr><tr><td>당기순이익</td><td>80</td><td>70</td></tr></table>"
               "<p>손익계산서</p><p>(단위 : 원)</p><table><tr><td>과목</td><td>제 1 기</td><td>제 0 기</td></tr>"
               "<tr><td>매출액</td><td>500</td><td>400</td></tr><tr><td>영업이익</td><td>50</td><td>40</td></tr>"
               "<tr><td>당기순이익</td><td>45</td><td>35</td></tr></table>"
               "<p>부문별 정보 손익계산서</p><table><tr><td>구분</td><td>A</td><td>B</td></tr><tr><td>매출액</td><td>1,111</td><td>2,222</td></tr></table>")
        rows, _, _ = W.extract_statements(W.tokenize(doc), "R")
        cfs = [r for r in rows if r["fs"] == "CFS"]; ofs = [r for r in rows if r["fs"] == "OFS"]
        self.assertEqual({r["account_nm"] for r in cfs}, {"매출액", "영업이익", "지배기업 소유주지분", "당기순이익"})
        self.assertEqual([r["thstrm_amount"] for r in ofs if r["account_nm"] == "매출액"], ["500"])
        self.assertNotIn("1111", [r["thstrm_amount"] for r in rows])

    def test_title_and_unit_in_same_row(self):
        doc = ("<table><tr><td>연결 포괄손익계산서</td><td>(단위: 백만원)</td></tr></table>"
               "<table><tr><td>과목</td><td>제 1 기</td><td>제 0 기</td></tr>"
               "<tr><td>수익(매출액)</td><td>1,000</td><td>900</td></tr><tr><td>영업이익(손실)</td><td>100</td><td>90</td></tr>"
               "<tr><td>당기순이익(손실)</td><td>80</td><td>70</td></tr></table>")
        rows, _, _ = W.extract_statements(W.tokenize(doc), "R")
        self.assertEqual(rows[0]["fs"], "CFS")
        self.assertEqual(rows[0]["thstrm_amount"], "1000000000")

    def test_toc_variants(self):
        sq = "node1['text'] = '2. 연결재무제표'; node1['dcmNo'] = '5'; node1['eleId'] = '3';"
        self.assertEqual(W.parse_toc(sq)[0]["text"], "2. 연결재무제표")
        esc = 'node1["text"] = "2. \\uc5f0\\uacb0\\uc7ac\\ubb34\\uc81c\\ud45c"; node1["dcmNo"] = "5";'
        self.assertEqual(W.parse_toc(esc)[0]["text"], "2. 연결재무제표")
        vd = '<a href="#" onclick="viewDoc(\'2026\',\'55\',\'7\',\'10\',\'20\',\'dart4.xsd\');">4. 재무제표</a>'
        n = W.parse_viewdoc(vd)[0]
        self.assertEqual((n["text"], n["dcmNo"], n["eleId"]), ("4. 재무제표", "55", "7"))
        self.assertEqual(W.find_dcm_nos("var x = {dcmNo: '8765432'};"), ["8765432"])

    def test_fallback_blind_scan_when_toc_unreadable(self):
        class Stub(W.WebClient):
            def _get(self, url, data=None, ttl=None, encoding="utf-8", valid=None):
                if "main.do" in url:
                    return "<script>var dcmNo = '9999999';</script>"
                if "eleId=3&" in url:
                    return ANNUAL_OFS
                if "eleId=4&" in url:
                    return "<p>재무제표 주석</p><p>1. 일반사항</p>"
                return "<p>" + "내용 " * 100 + "</p>"
        with tempfile.TemporaryDirectory() as d:
            c = Stub(Store(os.path.join(d, "t.sqlite")), min_interval=0)
            doc = c.parse_doc("20260320000001")
        self.assertEqual({r["account_nm"] for r in doc["OFS"]}, {"매출액", "영업이익", "당기순이익"})
        self.assertEqual(doc["CFS"], [])

    def test_unparsable_gives_error_not_zero(self):
        class Stub(W.WebClient):
            def _get(self, url, data=None, ttl=None, encoding="utf-8", valid=None):
                return "<html>blocked</html>"
        from dart import DartError
        with tempfile.TemporaryDirectory() as d:
            c = Stub(Store(os.path.join(d, "t.sqlite")), min_interval=0)
            with self.assertRaises(DartError):
                c.parse_doc("20260320000001")

    # ---- 실제 DART 목차(스크린샷) 구조: node1/node2/node3 숫자는 '깊이'이고 같은 번호가 반복된다
    @staticmethod
    def _toc(items):
        out = []
        for i, (lvl, text) in enumerate(items):
            out.append(f"var node{lvl} = {{}};\nnode{lvl}['text'] = \"{text}\";\nnode{lvl}['id'] = \"{i}\";\n"
                       f"node{lvl}['rcpNo'] = \"20260515000542\";\nnode{lvl}['dcmNo'] = \"9999\";\nnode{lvl}['eleId'] = \"{i + 1}\";\n"
                       f"node{lvl}['offset'] = \"0\";\nnode{lvl}['length'] = \"0\";\nnode{lvl}['dtd'] = \"dart4.xsd\";\nnode{lvl}['tocNo'] = \"{i}\";\n")
        return "<script>" + "\n".join(out) + "</script>"

    TREE_A = [(1, "III. 재무에 관한 사항"), (2, "1. 요약재무정보"), (2, "2. 연결재무제표"), (3, "2-1. 연결 재무상태표"),
              (3, "2-2. 연결 포괄손익계산서"), (3, "2-3. 연결 자본변동표"), (3, "2-4. 연결 현금흐름표"),
              (2, "3. 연결재무제표 주석"), (3, "1. 일반사항 (연결)"), (3, "39. 위험관리"),
              (2, "4. 재무제표"), (3, "4-1. 재무상태표"), (3, "4-2. 포괄손익계산서"), (3, "4-3. 자본변동표"),
              (3, "4-4. 현금흐름표"), (2, "5. 재무제표 주석"), (2, "6. 배당에 관한 사항"), (1, "【 전문가의 확인 】")]
    TREE_B = [(1, "III. 재무에 관한 사항"), (2, "1. 요약재무정보"), (2, "2. 연결재무제표"), (2, "3. 연결재무제표 주석"),
              (2, "4. 재무제표"), (3, "4-1. 재무상태표"), (3, "4-2. 포괄손익계산서"), (3, "4-3. 자본변동표"),
              (2, "5. 재무제표 주석")]

    def test_toc_depth_numbers_not_collapsed(self):
        nodes = W.parse_toc(self._toc(self.TREE_A))
        self.assertEqual(len(nodes), len(self.TREE_A))                      # 예전엔 깊이별 마지막 3개만 남았음
        self.assertEqual(nodes[4]["text"], "2-2. 연결 포괄손익계산서")
        self.assertEqual([n["text"] for n in W.pick_statement_nodes(nodes)],
                         ["2-2. 연결 포괄손익계산서", "4-2. 포괄손익계산서"])

    def test_pick_parent_when_no_pl_child(self):
        nodes = W.parse_toc(self._toc(self.TREE_B))
        self.assertEqual([n["text"] for n in W.pick_statement_nodes(nodes)], ["2. 연결재무제표", "4-2. 포괄손익계산서"])

    def test_end_to_end_titleless_leaf_pages(self):
        cis = ("<table><tr><td>(단위 : 백만원)</td></tr></table><table>"
               "<tr><td>과목</td><td>주석</td><td>제 56 기</td><td>제 55 기</td></tr>"
               "<tr><td>수익(매출액)</td><td></td><td>1,000</td><td>900</td></tr>"
               "<tr><td>영업이익</td><td></td><td>100</td><td>90</td></tr>"
               "<tr><td>당기순이익</td><td></td><td>80</td><td>70</td></tr>"
               "<tr><td>지배기업의 소유주에게 귀속되는 당기순이익</td><td></td><td>70</td><td>60</td></tr>"
               "<tr><td>지배기업의 소유주에게 귀속되는 총포괄이익</td><td></td><td>75</td><td>65</td></tr></table>")
        ofs = cis.replace("백만원", "원").replace("1,000", "500").replace("100", "50")
        class Stub(W.WebClient):
            def _get(self, url, data=None, ttl=None, encoding="utf-8", valid=None):
                if "main.do" in url:
                    return P._toc(P.TREE_A)
                if "eleId=5&" in url:
                    return cis                      # 2-2. 연결 포괄손익계산서 (제목 없는 본문)
                if "eleId=13&" in url:
                    return ofs                      # 4-2. 포괄손익계산서
                return "<p>다른 항목</p>" * 50
        with tempfile.TemporaryDirectory() as d:
            c = Stub(Store(os.path.join(d, "t.sqlite")), min_interval=0)
            doc = c.parse_doc("20260515000542")
        cfs = {r["account_nm"]: r for r in doc["CFS"]}
        self.assertEqual(cfs["수익(매출액)"]["thstrm_amount"], "1000000000")      # 백만원 → 원
        self.assertEqual(doc["OFS"][0]["thstrm_amount"], "500")                    # 원 단위 그대로
        self.assertEqual(doc["CFS"][0]["sj_div"], "CIS")
        from engine import find_item
        self.assertEqual(find_item(doc["CFS"], "net_income", "CFS")["cur"], 70000000)   # 총포괄이익 귀속분 아님
        self.assertEqual(c.last_diag["fetched"], 2)                                # 손익계산서 항목 2곳만 열람


if __name__ == "__main__":
    unittest.main()
