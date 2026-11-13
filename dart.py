"""OpenDART 클라이언트 + SQLite 저장소.

저장 계층 (업무지시서 11.4)
  raw_cache      : DART API 원본 응답 (Raw Data)
  quarterly_data : 분기별 추출/계산 결과 (Quarterly Data)  - 조회 때마다 append, 덮어쓰지 않음
  ttm_data       : 검증된 TTM 결과 (TTM Data)
  basis_history  : 연결·개별 구분 이력 (Basis Change History) - 최초 확인값을 보존(INSERT OR IGNORE)

외부 라이브러리 없이 표준 라이브러리만 사용한다.
"""
import io
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

BASE = "https://opendart.fss.or.kr/api/"
DAY = 86400


class DartError(Exception):
    """DART API 오류 (키 오류, 한도 초과, 네트워크 오류 등)."""


class DocParseError(DartError):
    """공시원문에서 재무제표를 읽지 못함 (해당 보고서만 '검증 필요'로 처리, 전체 조회는 계속)."""


# --------------------------------------------------------------------------- #
# 저장소
# --------------------------------------------------------------------------- #
class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw_cache(
                    k TEXT PRIMARY KEY, fetched_at REAL, body BLOB);
                CREATE TABLE IF NOT EXISTS quarterly_data(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, searched_at TEXT,
                    corp_code TEXT, corp_name TEXT, stock_code TEXT,
                    bsns_year INTEGER, quarter INTEGER,
                    period_start TEXT, period_end TEXT, fs_div TEXT,
                    item TEXT, value INTEGER, account_id TEXT, account_nm TEXT,
                    rcept_no TEXT, rcept_dt TEXT, method TEXT, formula TEXT,
                    status TEXT, payload TEXT);
                CREATE TABLE IF NOT EXISTS ttm_data(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, searched_at TEXT,
                    corp_code TEXT, item TEXT, value INTEGER, status TEXT,
                    basis TEXT, period_label TEXT);
                CREATE TABLE IF NOT EXISTS basis_history(
                    corp_code TEXT, bsns_year INTEGER, quarter INTEGER,
                    rcept_no TEXT, fs_div TEXT, evidence TEXT, first_seen_at TEXT,
                    PRIMARY KEY(corp_code, bsns_year, quarter, rcept_no));
                """
            )
            self.db.commit()

    # raw cache -------------------------------------------------------------
    def cache_get(self, key, ttl):
        with self.lock:
            row = self.db.execute(
                "SELECT fetched_at, body FROM raw_cache WHERE k=?", (key,)
            ).fetchone()
        if not row:
            return None
        if ttl is not None and time.time() - row[0] > ttl:
            return None
        return row[1]

    def cache_put(self, key, body):
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO raw_cache VALUES(?,?,?)",
                (key, time.time(), body),
            )
            self.db.commit()

    # 분기/TTM/이력 -----------------------------------------------------------
    def save_run(self, company, searched_at, quarters, ttm):
        with self.lock:
            for q in quarters or []:
                rep = q.get("report") or {}
                if q.get("fs_div") and rep.get("rcept_no"):
                    self.db.execute(
                        "INSERT OR IGNORE INTO basis_history VALUES(?,?,?,?,?,?,?)",
                        (company["corp_code"], q["bsns_year"], q["quarter"],
                         rep["rcept_no"], q["fs_div"], q.get("basis_evidence"), searched_at),
                    )
                for item, r in (q.get("items") or {}).items():
                    src = (r.get("sources") or [{}])[0]
                    self.db.execute(
                        "INSERT INTO quarterly_data(searched_at,corp_code,corp_name,stock_code,"
                        "bsns_year,quarter,period_start,period_end,fs_div,item,value,account_id,"
                        "account_nm,rcept_no,rcept_dt,method,formula,status,payload) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (searched_at, company["corp_code"], company.get("corp_name"),
                         company.get("stock_code"), q["bsns_year"], q["quarter"],
                         q["period_start"], q["period_end"], q.get("fs_div"), item,
                         r.get("value"), src.get("account_id"), src.get("account_nm"),
                         src.get("rcept_no"), src.get("rcept_dt"), r.get("method"),
                         r.get("formula"), r.get("status"), json.dumps(r, ensure_ascii=False)),
                    )
            for item, t in (ttm or {}).items():
                self.db.execute(
                    "INSERT INTO ttm_data(searched_at,corp_code,item,value,status,basis,period_label)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (searched_at, company["corp_code"], item, t.get("value"),
                     t.get("status"), t.get("basis"), t.get("period_label")),
                )
            self.db.commit()


# --------------------------------------------------------------------------- #
# 클라이언트
# --------------------------------------------------------------------------- #
class DartClient:
    def __init__(self, key_getter, store):
        self.key_getter = key_getter
        self.store = store
        self.sem = threading.Semaphore(6)
        self._corps = None
        self._corps_at = 0
        self._corps_lock = threading.Lock()

    # low level ---------------------------------------------------------------
    def _http(self, endpoint, params):
        key = self.key_getter()
        if not key:
            raise DartError("DART API 키가 설정되지 않았습니다.")
        q = dict(params)
        q["crtfc_key"] = key
        url = BASE + endpoint + "?" + urllib.parse.urlencode(q)
        last = None
        for attempt in range(3):
            try:
                with self.sem:
                    with urllib.request.urlopen(url, timeout=60) as r:
                        return r.read()
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
                time.sleep(1.2 * (attempt + 1))
        raise DartError(f"DART 서버 통신 실패: {last}")

    def _json(self, endpoint, params, ttl):
        ck = endpoint + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        raw = self.store.cache_get(ck, ttl) if self.store else None
        if raw is None:
            raw = self._http(endpoint, params)
            try:
                data = json.loads(raw.decode("utf-8"))
            except ValueError:
                raise DartError("DART 응답을 해석할 수 없습니다.")
            if data.get("status") in ("000", "013") and self.store:
                self.store.cache_put(ck, raw)
        else:
            data = json.loads(raw.decode("utf-8"))
        st = data.get("status")
        if st not in ("000", "013"):
            raise DartError(f"DART 오류 {st}: {data.get('message')}")
        return data

    # 기업 목록 ---------------------------------------------------------------
    def corp_list(self):
        """상장(종목코드 보유) 기업 목록: corpCode.xml"""
        with self._corps_lock:
            if self._corps is not None and time.time() - self._corps_at < DAY:
                return self._corps
            ck = "corpCode.xml"
            raw = self.store.cache_get(ck, 7 * DAY)
            if raw is None:
                raw = self._http("corpCode.xml", {})
                if not raw.startswith(b"PK"):
                    raise DartError("corpCode.xml 수신 실패: API 키를 확인하세요.")
                self.store.cache_put(ck, raw)
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                xml = z.read(z.namelist()[0])
            out = []
            for el in ET.fromstring(xml).iter("list"):
                sc = (el.findtext("stock_code") or "").strip()
                if sc:
                    out.append({
                        "corp_code": el.findtext("corp_code").strip(),
                        "corp_name": (el.findtext("corp_name") or "").strip(),
                        "stock_code": sc,
                    })
            self._corps, self._corps_at = out, time.time()
            return out

    def company(self, corp_code):
        d = self._json("company.json", {"corp_code": corp_code}, 7 * DAY)
        return d if d.get("status") == "000" else {}

    # 공시 목록 ---------------------------------------------------------------
    def _list(self, corp_code, bgn, end, pblntf_ty, ttl):
        rows, page = [], 1
        while True:
            d = self._json("list.json", {
                "corp_code": corp_code, "bgn_de": bgn, "end_de": end,
                "pblntf_ty": pblntf_ty, "last_reprt_at": "N",
                "page_no": page, "page_count": 100}, ttl)
            rows += d.get("list") or []
            if page >= int(d.get("total_page") or 1):
                return rows
            page += 1

    def list_periodic(self, corp_code, bgn, end):
        return self._list(corp_code, bgn, end, "A", 3600)

    def list_major(self, corp_code, bgn, end):
        return self._list(corp_code, bgn, end, "B", 3600)

    # 재무제표 ----------------------------------------------------------------
    def statement(self, corp_code, bsns_year, reprt_code, fs_div, rcept_no=None):
        d = self._json("fnlttSinglAcntAll.json", {
            "corp_code": corp_code, "bsns_year": bsns_year,
            "reprt_code": reprt_code, "fs_div": fs_div}, DAY)
        return d.get("list") if d.get("status") == "000" else None

    # 공시원문 확인 -----------------------------------------------------------
    _CONS = re.compile(r"연결\s*(재무상태표|손익계산서|포괄손익계산서)")

    def doc_has_consolidated(self, rcept_no):
        """공시원문(document.xml)에 연결재무제표가 실제로 있는지 확인한다."""
        ck = "doc_has_consolidated:" + rcept_no
        raw = self.store.cache_get(ck, None)
        if raw is not None:
            return json.loads(raw)["has"]
        body = self._http("document.xml", {"rcept_no": rcept_no})
        if not body.startswith(b"PK"):
            raise DartError("공시원문 수신 실패")
        has = False
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            for name in z.namelist():
                data = z.read(name)
                for enc in ("utf-8", "cp949"):
                    try:
                        text = data.decode(enc)
                    except UnicodeDecodeError:
                        continue
                    if "재무상태표" in text or "손익계산서" in text:
                        has = has or bool(self._CONS.search(text))
                        break
                if has:
                    break
        self.store.cache_put(ck, json.dumps({"has": has}).encode())
        return has
