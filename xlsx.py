"""엑셀(.xlsx) 내보내기 - 표준 라이브러리만 사용.

시트 구성 (화면과 동일)
  1. 재무실적 결과 : 화면 2 (종목별 매출액/영업이익/당기순이익, 조회기간, 재무기준)
  2. 분기별 상세   : 화면 3 (최근 4개 분기 + 합계 + 주석)
  3. 계산과정      : 각 수치의 직접추출/계산 여부, 산식, 공시 출처
금액은 모두 원 단위 숫자(#,##0 서식)로 저장한다.
"""
import io
import re
import zipfile
from xml.sax.saxutils import escape

ITEMS = (("revenue", "매출액"), ("operating_income", "영업이익"), ("net_income", "당기순이익"))
ST_KO = {"unavailable": "산출 불가", "unverified": "검증 필요"}
# 스타일 번호: 0 기본, 1 굵게, 2 숫자, 3 굵은 숫자, 4 줄바꿈
S_N, S_B, S_NUM, S_BNUM, S_WRAP = 0, 1, 2, 3, 4


def col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _clean(s):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s))


class Sheet:
    def __init__(self, name, widths):
        self.name, self.widths, self.rows = name[:31], widths, []

    def add(self, cells):
        """cells: 값 또는 (값, 스타일) 목록. 값: None/int/float/str"""
        self.rows.append(cells)

    def xml(self):
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
               "<cols>" + "".join(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>'
                                  for i, w in enumerate(self.widths)) + "</cols><sheetData>"]
        for r, cells in enumerate(self.rows, 1):
            out.append(f'<row r="{r}">')
            for c, cell in enumerate(cells):
                v, st = cell if isinstance(cell, tuple) else (cell, S_N)
                if v is None or v == "":
                    continue
                ref = f"{col_name(c)}{r}"
                if isinstance(v, bool):
                    v = str(v)
                if isinstance(v, (int, float)):
                    out.append(f'<c r="{ref}" s="{S_BNUM if st in (S_B, S_BNUM) else S_NUM}"><v>{v}</v></c>')
                else:
                    out.append(f'<c r="{ref}" s="{st}" t="inlineStr"><is><t xml:space="preserve">'
                               f"{escape(_clean(v))}</t></is></c>")
            out.append("</row>")
        out.append("</sheetData></worksheet>")
        return "".join(out)


STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Malgun Gothic"/></font>'
          '<font><b/><sz val="11"/><name val="Malgun Gothic"/></font></fonts>'
          '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="5">'
          '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
          '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
          '<xf numFmtId="3" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>'
          '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
          '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def write_xlsx(sheets):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1)) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, s in enumerate(sheets, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", STYLES)
        for i, s in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", s.xml())
    return buf.getvalue()


# --------------------------------------------------------------------------- #
def _cell_val(r):
    """결과 셀: 검증된 값이면 숫자, 아니면 상태 문구(0으로 쓰지 않음)."""
    if r and r.get("status") == "verified" and r.get("value") is not None:
        return r["value"]
    return ST_KO.get((r or {}).get("status"), "")


def _ni_label(it):
    if it.get("status") != "verified" or not it.get("ni_basis"):
        return None
    return ("[대체] " if it.get("fallback") else "") + it["ni_basis"] + (f" — {it['fallback_reason']}" if it.get("fallback_reason") else "")


def build_workbook(payload):
    results = payload.get("results") or []
    s1 = Sheet("재무실적 결과", [16, 10, 9, 18, 18, 22, 12, 18, 22, 12, 18, 22, 12, 60])
    s1.add([("재무실적 조회 결과", S_B)])
    s1.add([f"검색 시점 {str(payload.get('searched_at', '')).replace('T', ' ')}", f"단위: {payload.get('unit', '원')}"])
    s1.add([])
    head = [("종목명", S_B), ("종목코드", S_B), ("시장", S_B), ("재무구분", S_B)]
    for _, nm in ITEMS:
        head += [(f"{nm}(원)", S_B), (f"{nm} 조회기간", S_B), (f"{nm} 재무기준", S_B)]
    head.append(("비고", S_B))
    s1.add(head)
    for r in results:
        if r.get("error"):
            s1.add([r.get("corp_name"), r.get("stock_code"), r.get("market"), "조회 실패"] + [None] * 9 + [r["error"]])
            continue
        bd = r.get("basis_display") or ""
        if r.get("mixed_flag"):
            bd = (bd + " " if bd else "") + "(혼합기간 포함)"
        row = [r.get("corp_name"), r.get("stock_code"), r.get("market"), bd]
        notes = []
        for k, nm in ITEMS:
            it = (r.get("items") or {}).get(k) or {}
            ok = it.get("status") == "verified"
            row += [_cell_val(it), it.get("period_label") if ok else None,
                    ("혼합기준" if it.get("mixed") else it.get("basis")) if ok else None]
            if not ok and it.get("message"):
                notes.append(f"{nm}: {it['message']}")
            if ok and it.get("fallback"):
                fqs = it.get("fallback_quarters")
                notes.append(f"{nm}: 대체기준 사용" + (f"({', '.join(fqs)})" if fqs else "") + " — 분기별 상세/계산과정 시트 참조")
        if r.get("has_ttm") and r.get("basis_changes"):
            notes.insert(0, "연결·개별 변경 있음(분기별 상세 시트 참조)")
        row.append(" / ".join(notes))
        s1.add(row)
    if any(r.get("mixed_flag") for r in results):
        s1.add([])
        s1.add(["※ 혼합기준 TTM은 각 분기에 적용된 공시기준의 단순 합산치로 동일 연결범위 12개월 실적과 비교가능성에 차이가 있을 수 있음."])

    s2 = Sheet("분기별 상세", [22, 24, 12, 18, 18, 18, 40])
    s3 = Sheet("계산과정", [16, 12, 10, 12, 10, 18, 50, 12, 36, 18, 10, 28, 16, 18, 44, 40])
    s3.add([(h, S_B) for h in ["종목명", "회계분기", "항목", "상태", "방법", "금액(원)", "산식/메시지", "근거 역할",
                                "공시 보고서", "접수번호", "구분", "계정명", "공시단위", "근거 금액(원)", "DART 링크", "당기순이익 추출기준"]])
    for r in results:
        qs = r.get("quarters")
        if not qs:
            continue
        s2.add([(f"{r['corp_name']} ({r['stock_code']}, {r.get('market') or ''})", S_B)])
        s2.add([(h, S_B) for h in ["회계분기", "기간", "재무구분", "매출액(원)", "영업이익(원)", "당기순이익(원)", "당기순이익 추출기준"]])
        prev = None
        for q in qs:
            tag = q.get("basis_label") or "판정 불가"
            if prev and q.get("fs_div") and prev != q["fs_div"]:
                tag += " ← 변경"
            prev = q.get("fs_div") or prev
            s2.add([q["label"], f"{q.get('period_start') or ''} ~ {q.get('period_end') or ''}", tag]
                   + [_cell_val(q["items"][k]) for k, _ in ITEMS]
                   + [_ni_label(q["items"]["net_income"])])
        t = r.get("ttm") or {}
        fq = (t.get("net_income") or {}).get("fallback_quarters") or []
        s2.add([("최근 4개 분기 합계", S_B), None, ((t.get("revenue") or {}).get("basis") or "", S_B)]
               + [(_cell_val(t.get(k)), S_B) for k, _ in ITEMS]
               + [("대체기준 포함: " + ", ".join(fq)) if fq else None])
        for i, n in enumerate(r.get("notes") or []):
            s2.add([(("주1) " if i == 0 else "") + n, S_WRAP)])
        for k, nm in ITEMS:
            if (t.get(k) or {}).get("status") != "verified" and (t.get(k) or {}).get("message"):
                s2.add([f"※ {nm}: {t[k]['message']}"])
        s2.add(["당기순이익: 연결 분기는 지배기업 소유주 귀속 순이익, 개별 분기는 개별 당기순이익."])
        s2.add([])
        for q in qs:
            for k, nm in ITEMS:
                it = q["items"][k]
                base = [r["corp_name"], q["label"], nm]
                if it.get("status") != "verified":
                    s3.add(base + [ST_KO.get(it.get("status"), ""), None, None, it.get("message")])
                    continue
                srcs = it.get("sources") or [{}]
                for j, sc in enumerate(srcs):
                    first = j == 0
                    s3.add(base + ["확정" if first else None,
                                   ("직접 추출" if it["method"] == "direct" else "계산") if first else None,
                                   it["value"] if first else None,
                                   (it.get("formula") or it.get("message")) if first else None,
                                   sc.get("role"), sc.get("report_nm"), sc.get("rcept_no"), sc.get("fs_label"),
                                   sc.get("account_nm"), sc.get("unit"), sc.get("amount"), sc.get("url"),
                                   _ni_label(it) if (first and k == "net_income") else None])
    if not s2.rows:
        s2.add(["최근 4개 분기를 조회한 종목이 없습니다."])
    return write_xlsx([s1, s2, s3])
