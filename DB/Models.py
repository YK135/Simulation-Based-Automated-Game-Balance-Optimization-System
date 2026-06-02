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

# ═══════════════════════════════════════════════════════════
# runs 테이블
# ───────────────────────────────────────────────────────────
# 플레이어의 런(챕터 시작~보스 클리어 or 사망) 1회 = 1 레코드.
# ═══════════════════════════════════════════════════════════
class Run(Base):
    __tablename__ = "runs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    chapter      = Column(Integer, nullable=False, default=1)   # 1 or 2
    player_job   = Column(String(16), nullable=False)
    player_lv_start = Column(Integer, nullable=False, default=1)
    player_lv_end   = Column(Integer, nullable=True)

    result       = Column(String(16), nullable=True)  # 'clear' | 'dead' | 'abandon'
    total_nodes  = Column(Integer, default=0)          # 방문한 노드 수
    boss_cleared = Column(Boolean, default=False)

    # 관계
    choices = relationship("NodeChoice", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_runs_user_id", "user_id"),
        Index("ix_runs_chapter_result", "chapter", "result"),
    )

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "user_id":         self.user_id,
            "chapter":         self.chapter,
            "player_job":      self.player_job,
            "player_lv_start": self.player_lv_start,
            "player_lv_end":   self.player_lv_end,
            "result":          self.result,
            "total_nodes":     self.total_nodes,
            "boss_cleared":    self.boss_cleared,
            "created_at":      self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Run id={self.id} user={self.user_id} ch={self.chapter} {self.result}>"


# ═══════════════════════════════════════════════════════════
# node_choices 테이블
# ───────────────────────────────────────────────────────────
# 플레이어가 노드를 선택할 때마다 1 레코드.
# 분석: 어떤 노드 타입 선택이 승률에 영향을 주는지.
# ═══════════════════════════════════════════════════════════
class NodeChoice(Base):
    __tablename__ = "node_choices"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    run_id       = Column(Integer, ForeignKey("runs.id"), nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    turn         = Column(Integer, nullable=False)        # 몇 번째 선택 (1부터)
    layer        = Column(Integer, nullable=False)        # 맵의 층 번호
    node_id      = Column(String(16), nullable=False)     # "3_1" 형식
    node_type    = Column(String(16), nullable=False)     # "battle" | "rest" | ...

    # 선택 당시 플레이어 상태 스냅샷 (분석용)
    player_hp_ratio  = Column(Float, nullable=True)       # hp / maxhp
    player_lv        = Column(Integer, nullable=True)

    # 전투 노드일 때 추가 정보
    battle_result    = Column(String(16), nullable=True)  # 'win' | 'lose' | 'escape'
    battle_turns     = Column(Integer, nullable=True)

    # 관계
    run = relationship("Run", back_populates="choices")

    __table_args__ = (
        Index("ix_nc_run_id", "run_id"),
        Index("ix_nc_node_type", "node_type"),
    )

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "run_id":         self.run_id,
            "turn":           self.turn,
            "layer":          self.layer,
            "node_id":        self.node_id,
            "node_type":      self.node_type,
            "player_hp_ratio":self.player_hp_ratio,
            "player_lv":      self.player_lv,
            "battle_result":  self.battle_result,
            "battle_turns":   self.battle_turns,
        }

    def __repr__(self):
        return f"<NodeChoice run={self.run_id} turn={self.turn} {self.node_type}>"


# ─────────────────────────────────────────────
# User 클래스에 추가할 relationship (Models.py의 User 클래스 내부에 넣기)
# ─────────────────────────────────────────────
# runs = relationship("Run", back_populates="user", cascade="all, delete-orphan")
# Run 클래스에도 추가:
# user = relationship("User", back_populates="runs")