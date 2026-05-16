from __future__ import annotations
import os
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
    # 모델을 import 해야 Base.metadata에 등록됨
    from DB import Models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print(f"[DB] Initialized → {DATABASE_URL}")


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
