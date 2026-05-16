from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, Index
)
from sqlalchemy.orm import relationship
from DB import Base


# ═══════════════════════════════════════════════════════════
# users 테이블
# ───────────────────────────────────────────────────────────
# 게스트와 이메일 인증 사용자 모두 여기에.
# auth_type='guest':  닉네임만, email=NULL
# auth_type='email':  닉네임 + 이메일 인증 완료
# ═══════════════════════════════════════════════════════════
class User(Base):
    __tablename__ = "users"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    auth_type   = Column(String(16), nullable=False, default="guest")
    nickname    = Column(String(32), nullable=False)
    email       = Column(String(128), nullable=True, unique=True)
    is_active   = Column(Boolean, default=True, nullable=False)

    # 관계: User 1 ─ N Battle
    battles = relationship("Battle", back_populates="user", cascade="all, delete-orphan")

    # 인덱스: 이메일로 자주 조회
    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_nickname", "nickname"),
    )

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "auth_type":  self.auth_type,
            "nickname":   self.nickname,
            "email":      self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active":  self.is_active,
        }

    def __repr__(self):
        return f"<User id={self.id} {self.auth_type}:{self.nickname}>"


# ═══════════════════════════════════════════════════════════
# battles 테이블
# ───────────────────────────────────────────────────────────
# 전투 1회당 1 레코드. 랭킹/통계 산출 원천.
#
# 랭킹 쿼리 예시:
#   SELECT user_id, COUNT(*) AS boss_clears
#   FROM battles
#   WHERE is_boss = 1 AND result = 'win'
#   GROUP BY user_id ORDER BY boss_clears DESC
# ═══════════════════════════════════════════════════════════
class Battle(Base):
    __tablename__ = "battles"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 전투 메타
    explore_turn  = Column(Integer, nullable=False, default=0)   # 몇 번째 탐험에서
    enemies       = Column(Text, nullable=True)                  # JSON: ["고블린(중)", "박쥐(상)"]
    is_boss       = Column(Boolean, default=False, nullable=False)
    is_multi      = Column(Boolean, default=False, nullable=False)  # 다대일 여부

    # 결과
    result        = Column(String(16), nullable=False)  # 'win' | 'lose' | 'escape'
    turns         = Column(Integer, nullable=False, default=0)  # 전투 진행 턴 수

    # 플레이어 스냅샷 (전투 시작 시점)
    player_job    = Column(String(16), nullable=False)
    player_lv     = Column(Integer, nullable=False)
    hp_remaining  = Column(Float, nullable=False, default=0.0)  # 종료 시 남은 HP
    exp_gained    = Column(Integer, nullable=False, default=0)

    # 행동 통계 (분석용)
    skills_used   = Column(Integer, default=0)  # 사용한 스킬 수
    items_used    = Column(Integer, default=0)

    # 관계
    user = relationship("User", back_populates="battles")

    # 인덱스: 랭킹/통계 쿼리 가속
    __table_args__ = (
        Index("ix_battles_user_id", "user_id"),
        Index("ix_battles_is_boss_result", "is_boss", "result"),
        Index("ix_battles_created_at", "created_at"),
    )

    def to_dict(self) -> dict:
        import json
        return {
            "id":           self.id,
            "user_id":      self.user_id,
            "created_at":   self.created_at.isoformat() if self.created_at else None,
            "explore_turn": self.explore_turn,
            "enemies":      json.loads(self.enemies) if self.enemies else [],
            "is_boss":      self.is_boss,
            "is_multi":     self.is_multi,
            "result":       self.result,
            "turns":        self.turns,
            "player_job":   self.player_job,
            "player_lv":    self.player_lv,
            "hp_remaining": self.hp_remaining,
            "exp_gained":   self.exp_gained,
            "skills_used":  self.skills_used,
            "items_used":   self.items_used,
        }

    def __repr__(self):
        return f"<Battle id={self.id} user={self.user_id} {self.result} turns={self.turns}>"
