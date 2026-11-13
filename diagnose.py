"""실제 DART/KIND 사이트 대비 단계별 점검.  사용법: python diagnose.py 005930
각 단계가 실패하면 dart_web.py 의 해당 파서를 수정하면 됩니다."""
import os, sys
from datetime import date
from dart import Store
from dart_web import WebClient
from engine import build_reports

code = sys.argv[1] if len(sys.argv) > 1 else "005930"
c = WebClient(Store(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "diag.sqlite")))
def step(n, f):
    try:
        r = f(); print(f"[OK ] {n}"); return r
    except Exception as e:
        print(f"[FAIL] {n}: {e}"); sys.exit(1)
corps = step("1. KRX 상장법인 목록", c.corp_list); print("   종목 수:", len(corps))
info = step("2. 종목/결산월", lambda: c._entry(code)); print("  ", info)
today = date.today()
rows = step("3. DART 공시검색(정기보고서 목록)", lambda: c.list_periodic(code, f"{today.year-5}{today:%m%d}", f"{today:%Y%m%d}"))
reps = build_reports(rows, int(info["acc_mt"])); print("   보고서 수:", len(rows), "/ 기간 인식:", len(reps))
latest = reps[max(reps)]; print("   최신:", latest.report_nm, latest.rcept_no)
try:
    doc = c.parse_doc(latest.rcept_no); print("[OK ] 4. 공시원문 목차·재무제표 파싱")
except Exception as e:
    print("[FAIL] 4. 공시원문 목차·재무제표 파싱:", e); print("   진단:", c.last_diag); sys.exit(1)
print("   진단:", c.last_diag)
for fs in ("CFS", "OFS"):
    print(f"   {fs}: {len(doc[fs])}행", "(단위 미확인 있음)" if doc["unit_missing"][fs] else "")
    for r in doc[fs][:60]:
        if r["account_nm"].replace(" ", "") in ("매출액", "영업이익", "영업이익(손실)", "수익(매출액)", "영업수익") or "소유주" in r["account_nm"] or r["account_nm"].startswith("당기순"):
            print("     ", r["sj_div"], r["account_nm"], r["thstrm_amount"], r["thstrm_add_amount"], r["unit"])
