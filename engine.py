"""재무실적 산출 엔진 (업무지시서 4~8, 12장).

핵심 원칙
  * 분기마다 연결/개별을 독립 판정한다 (현재 상태를 과거에 덮어쓰지 않음).
  * 한 분기 안에서는 매출액·영업이익·당기순이익 모두 같은 재무제표 기준을 쓴다.
  * 누적금액 차감은 두 금액이 같은 기준(CFS/OFS)으로 확보된 경우에만 수행한다.
  * 검증 불가 → '검증 필요'/'산출 불가'. 임의 추정·보정 금지. 하나라도 미검증이면 TTM 미확정.
"""
import calendar
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from dart import DartError, DocParseError

ITEMS = ("revenue", "operating_income", "net_income")
ITEM_KO = {"revenue": "매출액", "operating_income": "영업이익", "net_income": "당기순이익"}
REPRT = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
BASIS_KO = {"CFS": "연결", "OFS": "개별"}
DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
MIXED = "혼합(연결·개별)"

MIXED_NOTE = ("혼합 기준으로 계산된 최근 4개 분기 합계는 각 분기에 적용된 공시기준의 단순 합산치이며, "
              "동일한 연결범위를 유지한 12개월 실적과는 회계적 비교가능성에 차이가 있을 수 있음.")

# --------------------------------------------------------------------------- #
# 계정 매칭
# --------------------------------------------------------------------------- #
REV_IDS = {"ifrs-full_Revenue", "ifrs_Revenue"}
REV_NAMES = {"매출액", "수익(매출액)", "영업수익", "매출", "수익", "매출액(영업수익)", "영업수익(매출액)"}
OP_IDS = {"dart_OperatingIncomeLoss"}
OP_NAMES = {"영업이익", "영업이익(손실)", "영업손익", "영업손실", "영업이익(영업손실)", "영업손실(이익)"}
NI_PARENT_IDS = {"ifrs-full_ProfitLossAttributableToOwnersOfParent",
                 "ifrs_ProfitLossAttributableToOwnersOfParent"}
NI_IND_IDS = {"ifrs-full_ProfitLoss", "ifrs_ProfitLoss"}
NI_IND_NAMES = {"당기순이익", "당기순이익(손실)", "당기순손익", "당기순손실", "분기순이익", "분기순이익(손실)",
                "분기순손익", "반기순이익", "반기순이익(손실)", "반기순손익"}


def norm(s):
    return re.sub(r"[\s\u00a0]", "", s or "")


def parse_amount(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        n = int(s) if re.fullmatch(r"-?\d+", s) else int(float(s))
    except ValueError:
        return None
    return -n if neg else n


CI_PARENT_IDS = {"ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent",
                 "ifrs_ComprehensiveIncomeAttributableToOwnersOfParent"}
NI_WORD = re.compile(r"순이익|순손익|순손실")

# 연결 당기순이익 추출 순서: 1 → 2 → 3
NI_TIER_LABEL = {
    1: "지배기업 소유주 귀속 당기순이익",
    2: "연결 당기순이익 전체 (대체)",
    3: "지배기업 소유주 귀속 총포괄이익 (대체)",
}
NI_TIER_REASON = {
    2: "연결 손익계산서에 지배기업 소유주 귀속 당기순이익 항목이 없어 연결 당기순이익 전체로 대체",
    3: "연결 손익계산서에 지배기업 소유주 귀속 당기순이익·연결 당기순이익 전체 항목이 없어 지배기업 소유주 귀속 총포괄이익으로 대체",
}
NI_ORDER_TEXT = "지배기업 소유주 귀속 당기순이익 → 연결 당기순이익 전체 → 지배기업 소유주 귀속 총포괄이익"


def _match(rows, item, fs):
    """매출액·영업이익, 그리고 개별 당기순이익."""
    if item == "revenue":
        ids, names = REV_IDS, REV_NAMES
    elif item == "operating_income":
        ids, names = OP_IDS, OP_NAMES
    else:
        ids, names = NI_IND_IDS, NI_IND_NAMES
    for r in rows:
        if r.get("account_id") in ids and parse_amount(r.get("thstrm_amount")) is not None:
            return r
    for r in rows:
        if norm(r.get("account_nm")) in names and parse_amount(r.get("thstrm_amount")) is not None:
            return r
    return None


def _ni_cfs_candidates(srows):
    """연결 손익계산서 한 장에서 순이익 후보를 단계별로 수집: {1: 지배주주 순이익, 2: 연결 순이익 전체, 3: 지배주주 총포괄이익}.
    '당기순이익의 귀속' / '총포괄이익의 귀속' 머리글 행을 따라가며, 이름만으로 구분이 안 되는
    '지배기업 소유주지분' 행이 어느 귀속 항목인지 판정한다. 판정 불가한 행은 쓰지 않는다."""
    found, section = {}, None
    for r in srows:
        nm = norm(r.get("account_nm"))
        aid = r.get("account_id")
        if parse_amount(r.get("thstrm_amount")) is None:
            if "귀속" in nm:                               # 귀속 머리글(금액 없음)
                if "포괄" in nm:
                    section = "CI"
                elif NI_WORD.search(nm):
                    section = "NI"
            continue
        parent = (("지배기업" in nm or "지배회사" in nm or "지배주주" in nm)
                  and ("소유주" in nm or "지분" in nm or "귀속" in nm) and "비지배" not in nm)
        if aid in NI_PARENT_IDS:
            found.setdefault(1, r)
        elif aid in CI_PARENT_IDS:
            found.setdefault(3, r)
        elif parent:
            if "포괄" in nm:
                found.setdefault(3, r)
            elif NI_WORD.search(nm):
                found.setdefault(1, r)
            elif section == "CI":
                found.setdefault(3, r)
            elif section == "NI":
                found.setdefault(1, r)
        if aid in NI_IND_IDS or nm in NI_IND_NAMES:
            found.setdefault(2, r)
    return found


def _fig(hit, sj, tier=None):
    return {
        "account_id": hit.get("account_id"), "account_nm": hit.get("account_nm"),
        "sj_div": sj, "rcept_no": hit.get("rcept_no"),
        "cur": parse_amount(hit.get("thstrm_amount")),
        "add": parse_amount(hit.get("thstrm_add_amount")),
        "prev_add": parse_amount(hit.get("frmtrm_add_amount")),
        "unit": hit.get("unit"), "tier": tier,
    }


def find_item(rows, item, fs, tier=None):
    """tier: 연결 당기순이익에서 특정 단계만 요청할 때(누적 차감 시 동일 기준 유지용)."""
    sjs = [(sj, [r for r in rows if r.get("sj_div") == sj]) for sj in ("IS", "CIS")]
    sjs = [(sj, sr) for sj, sr in sjs if sr]
    if item == "net_income" and fs == "CFS":
        cands = {sj: _ni_cfs_candidates(sr) for sj, sr in sjs}
        for t in ((tier,) if tier else (1, 2, 3)):
            for sj, _ in sjs:
                if cands[sj].get(t):
                    return _fig(cands[sj][t], sj, t)
        return None
    for sj, sr in sjs:
        hit = _match(sr, item, fs)
        if hit:
            return _fig(hit, sj)
    return None


def to_mn(v):
    if v is None:
        return None
    return int((Decimal(v) / Decimal(1000000)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def won(v):
    return f"{v:,}원"


# --------------------------------------------------------------------------- #
# 기간 유틸
# --------------------------------------------------------------------------- #
def month_end(y, m):
    return date(y, m, calendar.monthrange(y, m)[1])


def shift_month_end(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return month_end(y, m)


def period_info(end, fye):
    """(사업연도, 분기번호) - DART bsns_year 규칙(사업연도 개시연도)."""
    off = (end.month - fye) % 12
    q = {3: 1, 6: 2, 9: 3, 0: 4}.get(off)
    fey = end.year if end.month <= fye else end.year + 1
    bsns = fey if fye == 12 else fey - 1
    return bsns, q


REPORT_RE = re.compile(r"(사업보고서|반기보고서|분기보고서)\s*\(\s*(\d{4})\.(\d{1,2})\s*\)")
TYPE_Q = {"사업보고서": (4,), "반기보고서": (2,), "분기보고서": (1, 3)}


class Report:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def public(self):
        return {"report_nm": self.report_nm, "rcept_no": self.rcept_no, "rcept_dt": self.rcept_dt,
                "period_end": self.end.isoformat(), "corrected": self.corrected,
                "url": DART_VIEW + self.rcept_no}


def build_reports(rows, fye):
    best = {}
    for r in rows:
        m = REPORT_RE.search(r.get("report_nm") or "")
        if not m:
            continue
        typ, y, mo = m.group(1), int(m.group(2)), int(m.group(3))
        end = month_end(y, mo)
        bsns, q = period_info(end, fye)
        if q is None or q not in TYPE_Q[typ]:
            continue
        rep = Report(report_nm=r["report_nm"].strip(), rcept_no=r["rcept_no"],
                     rcept_dt=r.get("rcept_dt"), bsns=bsns, q=q, end=end,
                     start=(shift_month_end(end, -12) if q == 4 else shift_month_end(end, -3)) + timedelta(days=1),
                     corrected="정정" in r["report_nm"])
        k = (bsns, q)
        if k not in best or rep.rcept_no > best[k].rcept_no:   # 정정공시가 있으면 최신 접수본 사용
            best[k] = rep
    return best


def prev_quarter(y, q):
    return (y, q - 1) if q > 1 else (y - 1, 4)


def qlabel(y, q):
    return f"{y}년 {q}Q"


# --------------------------------------------------------------------------- #
# 회사 단위 실행
# --------------------------------------------------------------------------- #
class CompanyRun:
    def __init__(self, client, company, today):
        self.client, self.company, self.today = client, company, today
        self.cc = company["corp_code"]
        self._stmt, self._basis, self._err = {}, {}, {}
        info = client.company(self.cc) or {}
        try:
            self.fye = int(info.get("acc_mt") or 12)
        except ValueError:
            self.fye = 12
        bgn = date(today.year - 5, today.month, min(today.day, 28)).strftime("%Y%m%d")
        self.reports = build_reports(client.list_periodic(self.cc, bgn, today.strftime("%Y%m%d")), self.fye)

    # -- 데이터 접근 ----------------------------------------------------------
    def stmt(self, rep, fs):
        k = (rep.bsns, rep.q, fs)
        if k not in self._stmt:
            try:
                self._stmt[k] = self.client.statement(self.cc, rep.bsns, REPRT[rep.q], fs, rcept_no=rep.rcept_no)
            except DocParseError as ex:          # 이 보고서만 검증 필요로 처리하고 계속 진행
                self._stmt[k] = None
                self._err[(rep.bsns, rep.q)] = str(ex)
        return self._stmt[k]

    def fig(self, rep, fs, item, tier=None):
        rows = self.stmt(rep, fs)
        return find_item(rows, item, fs, tier) if rows else None

    @staticmethod
    def ni_info(fs, tier):
        """당기순이익 추출 기준 표시: (라벨, 대체기준 여부, 사유)"""
        if fs != "CFS":
            return "개별 당기순이익", False, None
        return NI_TIER_LABEL.get(tier, ""), bool(tier and tier > 1), NI_TIER_REASON.get(tier)

    def basis(self, rep):
        """해당 보고서(기간)의 연결/개별 판정. API 조회 실패만으로 '연결 미작성' 단정 금지."""
        k = (rep.bsns, rep.q)
        if k in self._basis:
            return self._basis[k]
        if self.stmt(rep, "CFS"):
            r = {"fs": "CFS", "evidence": "연결재무제표 조회됨(OpenDART CFS)", "message": None}
        elif not self.stmt(rep, "OFS"):
            r = {"fs": None, "evidence": None,
                 "message": "연결·별도 재무제표를 모두 읽지 못함 — 공시원문 확인 필요"
                            + (f" [{self._err[k]}]" if k in self._err else "")}
        else:
            try:
                has = self.client.doc_has_consolidated(rep.rcept_no)
            except DartError:
                has = None
            if has is False:
                r = {"fs": "OFS", "evidence": "연결재무제표 API 없음 + 공시원문에 연결재무제표 없음 확인", "message": None}
            elif has is True:
                r = {"fs": None, "evidence": None,
                     "message": "공시원문에는 연결재무제표가 있으나 API로 연결 수치를 가져오지 못함 — 개별로 간주하지 않음(검증 필요)"}
            else:
                r = {"fs": None, "evidence": None,
                     "message": "공시원문 확인에 실패하여 연결 작성 여부를 판정하지 못함(검증 필요)"}
        self._basis[k] = r
        return r

    # -- 공통 포맷 ------------------------------------------------------------
    @staticmethod
    def _src(rep, fs, f, role, amount):
        rn = f.get("rcept_no") or rep.rcept_no
        return {"role": role, "report_nm": rep.report_nm, "period_end": rep.end.isoformat(),
                "fs_div": fs, "fs_label": BASIS_KO[fs], "sj_div": f["sj_div"],
                "account_id": f["account_id"], "account_nm": f["account_nm"], "amount": amount, "unit": f.get("unit"), "tier": f.get("tier"),
                "rcept_no": rn, "rcept_dt": rep.rcept_dt, "url": DART_VIEW + rn}

    @staticmethod
    def _ok(value, method, sources, formula=None, note=None):
        return {"value": value, "status": "verified", "method": method, "formula": formula,
                "sources": sources, "message": note}

    @staticmethod
    def _fail(status, msg, sources=None):
        return {"value": None, "status": status, "method": None, "formula": None,
                "sources": sources or [], "message": msg}

    # -- 분기 실적 ------------------------------------------------------------
    def quarter_item(self, item, y, q):
        self._tier_used = None
        res = self._quarter_item(item, y, q)
        if item == "net_income" and res["status"] == "verified":
            fs = res["sources"][0]["fs_div"]
            label, fb, why = self.ni_info(fs, self._tier_used)
            res.update(ni_basis=label, fallback=fb, fallback_reason=why, tier=self._tier_used)
        return res

    def _quarter_item(self, item, y, q):
        nm = ITEM_KO[item]
        rep = self.reports.get((y, q))
        if not rep:
            return self._fail("unavailable", f"{qlabel(y, q)} 정기보고서가 DART에서 확인되지 않음")
        b = self.basis(rep)
        if not b["fs"]:
            return self._fail("unverified", b["message"])
        fs = b["fs"]
        lab = BASIS_KO[fs]
        f = self.fig(rep, fs, item)
        if not f or f["cur"] is None:
            return self._fail("unverified", f"{lab}손익계산서에서 {nm} 계정을 찾지 못함(표준 계정 불일치) — 원문 확인 필요")
        tier = f.get("tier")
        self._tier_used = tier

        if q == 1:
            return self._ok(f["cur"], "direct", [self._src(rep, fs, f, "1분기 3개월", f["cur"])])

        if q in (2, 3):
            if f["add"] is not None:   # 보고서에 당분기 3개월 금액이 별도로 공시됨 → 직접 추출
                return self._ok(f["cur"], "direct", [self._src(rep, fs, f, "당분기 3개월", f["cur"])])
            prev = self.reports.get((y, q - 1))
            pf = self.fig(prev, fs, item, tier) if prev else None
            if not pf or pf["cur"] is None:
                return self._fail(
                    "unverified",
                    f"{qlabel(y, q)} 단독 {lab} 금액이 공시되지 않았고, 직전 누적 {lab} 금액도 같은 추출기준으로 확보되지 않음 "
                    f"(기준이 다른 누적금액은 차감하지 않음)")
            prev_cum = pf["cur"] if q - 1 == 1 else (pf["add"] if pf["add"] is not None else pf["cur"])
            val = f["cur"] - prev_cum
            pl = "1분기 누적" if q == 2 else "반기 누적"
            cl = "반기 누적" if q == 2 else "3분기 누적"
            formula = f"{cl}({lab}) {won(f['cur'])} − {pl}({lab}) {won(prev_cum)} = {won(val)}"
            return self._ok(val, "calc",
                            [self._src(rep, fs, f, cl, f["cur"]), self._src(prev, fs, pf, pl, prev_cum)],
                            formula, "당분기 단독 금액 미공시 → 동일 기준 누적금액 차감")

        # q == 4 : 연간 − 3분기 누적 (동일 기준 확보 시에만)
        r3 = self.reports.get((y, 3))
        f3, cum3, s3, note = (self.fig(r3, fs, item, tier) if r3 else None), None, None, None
        if f3 and (f3["add"] is not None or f3["cur"] is not None):
            cum3 = f3["add"] if f3["add"] is not None else f3["cur"]
            s3 = self._src(r3, fs, f3, "3분기 누적", cum3)
        else:
            rn = self.reports.get((y + 1, 3))
            fn = self.fig(rn, fs, item, tier) if rn else None
            if fn and fn["prev_add"] is not None:
                cum3 = fn["prev_add"]
                s3 = self._src(rn, fs, fn, "다음 사업연도 3분기보고서의 전기 3분기 누적 비교정보", cum3)
                note = f"{y}년 3분기보고서에 {lab} 기준 누적금액이 없어 동일 기준의 비교정보를 사용"
        if cum3 is None:
            return self._fail(
                "unverified",
                f"{y}년 사업보고서({lab})와 동일 기준의 3분기 누적 금액을 확보하지 못함 — "
                f"주석/XBRL 원문에서 4분기 단독 실적 확인 필요 (다른 기준 수치는 차감하지 않음)",
                [self._src(rep, fs, f, "연간", f["cur"])])
        val = f["cur"] - cum3
        formula = f"{y}년 연간({lab}) {won(f['cur'])} − 3분기 누적({lab}) {won(cum3)} = {won(val)}"
        return self._ok(val, "calc", [self._src(rep, fs, f, "연간", f["cur"]), s3], formula, note)

    def quarter_keys(self):
        latest = max(self.reports)
        seq = [latest]
        for _ in range(3):
            seq.append(prev_quarter(*seq[-1]))
        return list(reversed(seq))

    def compute_quarters(self):
        out = []
        for (y, q) in self.quarter_keys():
            rep = self.reports.get((y, q))
            qd = {"bsns_year": y, "quarter": q, "label": qlabel(y, q),
                  "period_start": None, "period_end": None, "report": None,
                  "fs_div": None, "basis_label": None, "basis_evidence": None,
                  "basis_message": None, "items": {}}
            if rep:
                b = self.basis(rep)
                qd.update(period_start=rep.start.isoformat(), period_end=rep.end.isoformat(),
                          report=rep.public(), fs_div=b["fs"],
                          basis_label=BASIS_KO.get(b["fs"]), basis_evidence=b.get("evidence"),
                          basis_message=b.get("message"))
            for item in ITEMS:
                qd["items"][item] = self.quarter_item(item, y, q)
            out.append(qd)
        return out

    # -- TTM -----------------------------------------------------------------
    def compute_ttm(self, quarters):
        bases = {q["fs_div"] for q in quarters}
        if None in bases:
            basis = None
        elif len(bases) == 1:
            basis = BASIS_KO[next(iter(bases))]
        else:
            basis = MIXED
        period = f"{quarters[0]['label']}~{quarters[-1]['label']}"
        ttm = {}
        for item in ITEMS:
            rs = [q["items"][item] for q in quarters]
            bad = [(q["label"], r) for q, r in zip(quarters, rs) if r["status"] != "verified"]
            t = {"period_label": period, "basis": basis, "mixed": basis == MIXED, "mode": "TTM"}
            if bad:
                worst = "unavailable" if all(r["status"] == "unavailable" for _, r in bad) else "unverified"
                t.update(status=worst, value=None,
                         message="검증되지 않은 분기가 있어 TTM을 확정하지 않음: "
                                 + "; ".join(f"{lb}({r['message']})" for lb, r in bad))
            else:
                total = sum(r["value"] for r in rs)
                assert total == sum(q["items"][item]["value"] for q in quarters)   # 분기 합계 = TTM 검증
                t.update(status="verified", value=total, message=None)
                if item == "net_income":
                    fq = [q["label"] for q, r in zip(quarters, rs) if r.get("fallback")]
                    t.update(fallback=bool(fq), fallback_quarters=fq)
            ttm[item] = t
        return ttm

    # -- 최근 사업연도 -------------------------------------------------------
    def compute_annual(self):
        keys = [k for k in self.reports if k[1] == 4]
        if not keys:
            return None, {i: self._fail("unavailable", "사업보고서가 DART에서 확인되지 않음") for i in ITEMS}
        rep = self.reports[max(keys)]
        b = self.basis(rep)
        res = {}
        for item in ITEMS:
            if not b["fs"]:
                r = self._fail("unverified", b["message"])
            else:
                f = self.fig(rep, b["fs"], item)
                if not f or f["cur"] is None:
                    r = self._fail("unverified", f"{ITEM_KO[item]} 계정을 찾지 못함 — 원문 확인 필요")
                else:
                    r = self._ok(f["cur"], "direct", [self._src(rep, b["fs"], f, "연간", f["cur"])])
                    if item == "net_income":
                        label, fb, why = self.ni_info(b["fs"], f.get("tier"))
                        r.update(ni_basis=label, fallback=fb, fallback_reason=why, tier=f.get("tier"))
            res[item] = r
        return {"rep": rep, "basis": b}, res

    # -- 연결·개별 변경 ------------------------------------------------------
    def basis_changes(self, quarters):
        out = []
        for a, b in zip(quarters, quarters[1:]):
            if a["fs_div"] and b["fs_div"] and a["fs_div"] != b["fs_div"]:
                cands = []
                try:
                    bgn = (date.fromisoformat(a["period_end"]) - timedelta(days=90)).strftime("%Y%m%d")
                    end = (date.fromisoformat(b["period_end"]) + timedelta(days=45)).strftime("%Y%m%d")
                    pat = re.compile(r"타법인|출자증권|종속|합병|분할|영업양[수도]|주식교환|지배")
                    for r in self.client.list_major(self.cc, bgn, min(end, self.today.strftime("%Y%m%d"))):
                        if pat.search(r.get("report_nm", "")):
                            cands.append({"report_nm": r["report_nm"].strip(), "rcept_dt": r.get("rcept_dt"),
                                          "rcept_no": r["rcept_no"], "url": DART_VIEW + r["rcept_no"]})
                except DartError:
                    pass
                out.append({"from": a["fs_div"], "to": b["fs_div"],
                            "from_label": BASIS_KO[a["fs_div"]], "to_label": BASIS_KO[b["fs_div"]],
                            "first_quarter": b["label"], "exact_date": None, "reason": None,
                            "related_disclosures": cands[:8],
                            "evidence_report": b["report"]})
        return out

    def basis_notes(self, quarters, changes):
        if not changes:
            return []
        notes = []
        for c in changes:
            if c["to"] == "CFS":
                s = f"{c['first_quarter']}부터 연결재무제표 작성이 확인됨."
            else:
                s = f"{c['first_quarter']}부터 연결재무제표가 아닌 개별재무제표 기준 공시가 확인됨."
            notes.append(s)
        groups = {}
        for q in quarters:
            if q["fs_div"]:
                groups.setdefault(q["fs_div"], []).append(q["label"])
        parts = [f"{' 및 '.join(v)}는 {BASIS_KO[k]}재무제표 기준" for k, v in groups.items()]
        txt = " ".join(notes) + f" 이에 따라 {', '.join(parts)}으로 재무실적을 집계함. " \
            "연결 분기의 당기순이익은 지배기업 소유주 귀속 순이익, 개별 분기는 개별 당기순이익을 사용함. " \
            "최근 4개 분기 합산 실적에는 연결 및 개별 기준이 혼재되어 있음."
        out = [txt]
        for c in changes:
            if c["exact_date"] or c["reason"]:
                out.append("변경일/사유: " + " / ".join(x for x in (c["exact_date"], c["reason"]) if x))
            else:
                n = len(c["related_disclosures"])
                out.append(f"{c['first_quarter']} 변경의 정확한 일자와 사유는 공시에서 자동 확인되지 않음"
                           + (f" (참고: 같은 기간의 주요사항 관련 공시 {n}건 — 사유를 확정하는 것은 아님)." if n else "."))
        out.append(MIXED_NOTE)
        return out

    def ni_fallback_notes(self, quarters):
        out = []
        for tier in (2, 3):
            qs = [q["label"] for q in quarters
                  if q["items"]["net_income"].get("tier") == tier and q["items"]["net_income"].get("fallback")]
            if qs:
                out.append(f"당기순이익 대체기준: {', '.join(qs)} — {NI_TIER_REASON[tier]}함. "
                           f"(연결 당기순이익 추출 순서: {NI_ORDER_TEXT})")
        return out

    # -- 전체 ----------------------------------------------------------------
    def run(self, periods):
        res = {"corp_code": self.cc, "corp_name": self.company.get("corp_name"),
               "stock_code": self.company.get("stock_code"), "market": self.company.get("market"),
               "fye_month": self.fye, "items": {}, "quarters": None, "ttm": None,
               "basis_changes": [], "notes": [], "basis_display": None, "mixed_flag": False,
               "has_ttm": False, "error": None}
        if not self.reports:
            res["error"] = "DART에서 정기보고서(사업·반기·분기)를 찾지 못함"
            return res
        if any(periods.get(i) == "TTM" for i in ITEMS):
            qs = self.compute_quarters()
            ttm = self.compute_ttm(qs)
            ch = self.basis_changes(qs)
            res.update(quarters=qs, ttm=ttm, basis_changes=ch, has_ttm=True,
                       notes=self.basis_notes(qs, ch) + self.ni_fallback_notes(qs))
            res["basis_display"] = qs[-1]["basis_label"]
            res["mixed_flag"] = any(ttm[i]["mixed"] for i in ITEMS if periods.get(i) == "TTM")
        annual = None
        if any(periods.get(i) == "FY" for i in ITEMS):
            meta, ann = self.compute_annual()
            if meta:
                annual = (meta, ann)
                if res["basis_display"] is None:
                    res["basis_display"] = BASIS_KO.get(meta["basis"]["fs"])
        for i in ITEMS:
            if periods.get(i) == "TTM":
                res["items"][i] = res["ttm"][i]
            else:
                meta, ann = annual if annual else (None, {i: self._fail("unavailable", "사업보고서 없음")})
                r = dict(ann[i])
                rep = meta["rep"] if meta else None
                fs = meta["basis"]["fs"] if meta else None
                r.update(mode="FY", basis=BASIS_KO.get(fs), mixed=False,
                         period_label=(f"{rep.bsns}년 연간" if rep else None),
                         period_range=(f"{rep.start.isoformat()} ~ {rep.end.isoformat()}" if rep else None))
                res["items"][i] = r
        return res
