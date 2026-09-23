# -*- coding: utf-8 -*-
"""
test_db_guard.py — 운영 환경에서 DB 연결 설정이 빠졌을 때 부팅이 멈추는지

왜 필요한가: `DB/__init__.py`는 `DATABASE_URL`이 없으면 조용히 `sqlite:///ai_rpg.db`로
떨어진다. 로컬 개발에는 편하지만 배포에서는 위험하다 — 설정이 빠져도 서버가 "정상처럼"
뜨면서 컨테이너 로컬 디스크에 저장하고, Render의 디스크는 ephemeral이라 재배포마다
유저 상태와 학습용 `BattleLog`가 에러 하나 없이 사라진다.

가드는 `RENDER`(Render가 자동 주입) 유무로 배포를 판별한다 — `app/__init__.py`가
MASTER_MODE를 끄는 데 쓰는 것과 같은 신호를 재사용한다. 로컬에는 그 변수가 없으므로
개발 동작은 이 변경 전과 완전히 동일하다.

로컬 ai_rpg.db는 건드리지 않는다(DATABASE_URL을 임시 파일로).

실행: python3 TestFile/test_db_guard.py
"""
import sys, os, importlib, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}" + (f"  → {extra}" if extra != "" else ""))


_saved = {k: os.environ.get(k) for k in ("RENDER", "DATABASE_URL")}
_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)


def _reload(render, url):
    for k, v in (("RENDER", render), ("DATABASE_URL", url)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    import DB
    return importlib.reload(DB)


def _boot(render, url):
    """(예외 or None, 모듈) — init_db()가 터지면 그 예외를 돌려준다."""
    mod = _reload(render, url)
    try:
        mod.init_db()
        return None, mod
    except Exception as e:
        return e, mod


try:
    print("[1] 로컬(RENDER 없음) — 이 변경 전과 동일하게 동작해야 한다")
    err, mod = _boot(None, "sqlite:///" + _db)
    check("DATABASE_URL이 SQLite여도 정상 부팅", err is None, err)
    # ★ 이 칸은 init_db()를 부르지 않는다 — 폴백 경로가 바로 로컬 ai_rpg.db라서
    #   부팅까지 시키면 이 테스트가 실제 개발용 DB 파일에 테이블을 만든다.
    mod = _reload(None, None)
    check("DATABASE_URL이 없으면 기본 sqlite:///ai_rpg.db로 폴백 (전과 동일)",
          mod.DATABASE_URL == mod.DEFAULT_DB_URL, mod.DATABASE_URL)
    check("로컬에서는 가드가 아무것도 막지 않는다",
          mod._guard_production_db_url() is None)

    print("\n[2] 배포(RENDER 있음) — 설정이 빠지면 멈춰야 한다")
    err, _ = _boot("1", None)
    check("DATABASE_URL 누락 → RuntimeError", isinstance(err, RuntimeError), type(err).__name__)
    check("메시지가 원인을 말한다 (DATABASE_URL)", "DATABASE_URL" in str(err), str(err)[:60])
    check("메시지가 결과를 말한다 (데이터 유실)",
          "사라" in str(err) or "유실" in str(err), str(err)[:60])

    err, _ = _boot("1", "sqlite:///oops.db")
    check("SQLite를 가리켜도 → RuntimeError", isinstance(err, RuntimeError), type(err).__name__)

    err, _ = _boot("1", "postgresql://u:p@h:5432/d")
    # 진짜 접속은 안 한다 — create_all()에서 접속 실패가 나더라도 가드는 통과해야 한다.
    check("PostgreSQL이면 가드는 통과한다 (실패하더라도 가드 때문이 아니다)",
          not (isinstance(err, RuntimeError) and "DATABASE_URL" in str(err)
               and ("SQLite" in str(err) or "없는 채로" in str(err))),
          repr(err)[:80])

    print("\n[3] 비밀값 노출 — 부팅 로그의 URL은 가려져야 한다")
    mod = _reload("1", "postgresql://user:supersecret@host:5432/db")
    masked = mod._masked_db_url()
    check("비밀번호가 로그에 안 남는다", "supersecret" not in masked, masked)
    check("나머지는 알아볼 수 있다", "user" in masked and "host" in masked, masked)

    print("\n[4] .gitignore가 .env를 막는다")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, ".gitignore"), encoding="utf-8") as f:
        gi = [ln.strip() for ln in f]
    check(".env 규칙이 있다", ".env" in gi, [g for g in gi if "env" in g])
    check(".env.example은 예외로 남긴다", "!.env.example" in gi, [g for g in gi if "env" in g])

finally:
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    import DB
    importlib.reload(DB)
    os.remove(_db)

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
