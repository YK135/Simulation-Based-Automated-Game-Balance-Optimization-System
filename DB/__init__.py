from __future__ import annotations
import os
import re
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

 
# ─────────────────────────────────────────────
# DB 경로 설정
# ─────────────────────────────────────────────
# 환경변수로 오버라이드 가능 (배포 시 PostgreSQL 등):
#   export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
DEFAULT_DB_URL = "sqlite:///ai_rpg.db"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)


# ─────────────────────────────────────────────
# 운영 환경 가드
# ─────────────────────────────────────────────
# 위 폴백은 로컬 개발에는 편하지만 운영에서는 위험하다 — DATABASE_URL이 빠지거나
# 오타가 나도 서버가 "정상처럼" 뜨면서 컨테이너 로컬 디스크의 SQLite 파일에
# 저장한다. Render의 디스크는 ephemeral이라 재배포 때마다 유저 상태와 학습용
# BattleLog가 통째로 사라지고, 그 사실이 에러 하나 없이 조용히 진행된다.
#
# RENDER는 Render가 서비스에 자동 주입하는 변수다 — app/__init__.py가 MASTER_MODE를
# 끄는 데 쓰는 것과 같은 "여기는 배포 환경"의 신호이고, 같은 패턴을 재사용한다.
# 로컬에는 이 변수가 없으므로 개발 동작은 전과 완전히 동일하다.
def _guard_production_db_url() -> None:
    if not os.environ.get("RENDER"):
        return  # 로컬/테스트 — SQLite 폴백 그대로 허용
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "DATABASE_URL이 없는 채로 배포 환경에서 부팅하려 했습니다. "
            "이대로 뜨면 유저 상태와 BattleLog가 컨테이너의 임시 SQLite 파일에 저장되고 "
            "재배포 때 사라집니다. render.yaml의 fromDatabase 설정 또는 서비스 환경변수를 "
            "확인하세요."
        )
    if DATABASE_URL.startswith("sqlite"):
        raise RuntimeError(
            f"배포 환경인데 DATABASE_URL이 SQLite({_masked_db_url()})를 가리킵니다. "
            "컨테이너 디스크는 ephemeral이라 재배포 때 데이터가 사라집니다. "
            "관리형 PostgreSQL 연결 문자열을 사용하세요."
        )


# ─────────────────────────────────────────────
# SQLAlchemy 엔진 + 세션 팩토리
# ─────────────────────────────────────────────
# SQLite 전용 옵션: check_same_thread=False (Flask 다중 스레드 대응)
_engine_kwargs = {"echo": False}  # echo=True면 모든 SQL 콘솔 출력 (디버그용)
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모든 모델이 상속할 베이스 클래스
Base = declarative_base()


# ─────────────────────────────────────────────
# 초기화 (테이블 자동 생성)
# ─────────────────────────────────────────────
def init_db():
    """
    부팅 시 1회 호출.
    모델에 등록된 모든 테이블을 DB에 생성 (이미 있으면 스킵).
    SQLite는 ai_rpg.db 파일이 자동 생성됨.
    """
    _guard_production_db_url()
    # 모델을 import 해야 Base.metadata에 등록됨
    from DB import Models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print(f"[DB] Initialized → {_masked_db_url()}")


def _masked_db_url() -> str:
    """부팅 로그에 남길 DATABASE_URL — 계정/비밀번호는 가린다.
    ★ postgresql://user:password@host:5432/db 형태를 그대로 찍고 있었는데,
      Render 등에서 발급하는 URL은 실제 DB 접속 비밀번호를 포함한다 —
      서버 로그(대부분 접근 통제가 느슨한 별도 콘솔)에 평문으로 남는 건
      비밀키를 로그에 남기는 것과 같은 급의 노출이다."""
    return re.sub(r"://([^:/@]+)(:[^@/]*)?@", r"://\1:***@", DATABASE_URL)


# ─────────────────────────────────────────────
# 세션 헬퍼
# ─────────────────────────────────────────────
@contextmanager
def get_session():
    """
    컨텍스트 매니저 — 자동 commit / rollback / close.

    사용:
        with get_session() as s:
            user = User(nickname="용사")
            s.add(user)
            # with 블록 끝나면 자동 commit
    
    예외 발생 시 자동 rollback.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
