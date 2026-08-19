"""
Battle/MonsterKit.py — 몬스터별 행동 확률 + 스킬 세트 (챕터 기준)
─────────────────────────────────────────────
몬스터별 "일반 공격 / 스킬 사용 / 대기" 확률과 스킬 후보 목록을 데이터로 정의한다.
사제는 서포터 전용 로직(BattleSession._priest_action)이 따로 있어 여기 없음.

키: (enemy_type, chapter) → {"attack_prob", "skill_prob", "watch_prob", "skills"}
  - 세 확률의 합은 1.0.
  - "skills"는 균등 가중치 후보 목록 — MP가 부족한 스킬은 자동 제외.
  - 플레이어 전용기(강화1/연속공격1/저주1/난사2/급소찌르기1/추진력/
    몸통박치기2/수비태세2/실드)를 재사용하는 항목은 표시 스킬명은 같지만
    실제 수치는 Skills.MONSTER_SKILL_META가 우선 적용된다.
"""
from __future__ import annotations

MONSTER_KITS: dict[tuple[str, int], dict] = {
    ("고블린", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["강타1"],
    },

    ("박쥐", 1): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["파이어볼1", "약화1", "미약화1"],
    },
    ("박쥐", 2): {
        "attack_prob": 0.65, "skill_prob": 0.35, "watch_prob": 0.0,
        "skills": ["파이어볼2", "약화1", "미약화1"],
    },

    ("슬라임", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["둔화1"],
    },

    ("화염 슬라임", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["파이어볼1"],
    },
    ("화염 슬라임", 2): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["파이어볼2", "둔화1"],
    },

    ("빙결 슬라임", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["아이스볼릿1"],
    },
    ("빙결 슬라임", 2): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["아이스볼릿2", "둔화1"],
    },

    ("번개 슬라임", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["라이트닝1"],
    },
    ("번개 슬라임", 2): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["라이트닝2", "둔화1"],
    },

    ("골렘", 2): {
        "attack_prob": 0.70, "skill_prob": 0.25, "watch_prob": 0.05,
        "skills": ["몸통박치기2", "수비태세2", "실드"],
    },

    ("유령", 2): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["강화1", "연속공격1", "저주1"],
    },

    ("암살자", 2): {
        "attack_prob": 0.65, "skill_prob": 0.35, "watch_prob": 0.0,
        "skills": ["난사2", "급소찌르기1", "추진력"],
    },
}


def get_monster_kit(enemy_type: str, chapter: int = 1) -> dict | None:
    """(enemy_type, chapter) → 없으면 챕터2 → 챕터1 순으로 폴백.
    정의 자체가 없는 타입(보스 등)은 None → 호출부가 기존 휴리스틱으로 폴백."""
    kit = MONSTER_KITS.get((enemy_type, chapter))
    if kit is not None:
        return kit
    kit = MONSTER_KITS.get((enemy_type, 2))
    if kit is not None:
        return kit
    return MONSTER_KITS.get((enemy_type, 1))
