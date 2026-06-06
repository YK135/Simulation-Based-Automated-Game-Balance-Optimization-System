"""Battle/Damage.py — DamageCalc, _apply_damage_with_shield"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from random import randint, random, uniform

from .Entity import EntitySnapshot

class DamageCalc:
    """
    데미지 계산 통합 클래스 (Phase 1 — 역할 기반 메커니즘 통합).

    기본 공식 (v2):
      base = atk_stat * 200 / (100 + def_stat)
      base = max(base, atk_stat * 0.4)         # 최소 데미지 보장
      base *= skill_mult * role_mult * uniform(0.9, 1.1)
      crit (luc * 0.5%, 상한 40%) → +50%

    역할 기반 추가 (Phase 1):
      - 회피: def_luc * 0.4 + dodge_bonus*100 - dodge_penalty_per_extra_hit
              (유령: dodge_bonus=0.20, 다단히트시 hit당 회피 감소)
      - 첫 공격 보너스: attacker.has_attacked == False 면 first_attack_bonus 적용
              (암살자: first_attack_bonus=1.15)
      - 상성: defender의 physical_resist / magical_resist
              (슬라임: 물리 0.65 / 마법 1.10, 골렘: 반대)
      - 최종 최소 데미지 보장: atk_stat * 0.20
              (상성으로 깎여도 공격력의 20% 이상은 보장)

    호출 흐름:
      physical(): 물리 데미지 → _calc(damage_type="physical")
      magical():  마법 데미지 → _calc(damage_type="magical")
      _calc():    회피 → 기본 → 첫공 → 상성 → 크리 → 최소 보장 → 정수화

    호출 시 attacker / defender 스냅샷을 넘겨야 역할 메커니즘 적용됨.
    옛 호출 (attacker/defender 인자 없음)도 후방 호환 — 기본값은 1.0/0.0.
    """

    ROLE_MULT = {
        "player": 1.0,
        "monster": 1.0,
    }

    @staticmethod
    def _calc(
        atk_stat: float,
        def_stat: float,
        atk_luc: float,
        def_luc: float,
        skill_mult: float,
        role_mult: float,
        # ── Phase 1 신규 인자 (모두 옵셔널, 후방 호환) ──
        damage_type: str = "physical",   # "physical" | "magical"
        defender = None,                 # EntitySnapshot — 상성/회피보너스 적용
        attacker = None,                 # EntitySnapshot — 첫공격 보너스 / has_attacked 갱신
        hit_count: int = 1,              # 다단히트 (회피 페널티 적용)
    ) -> tuple[int, bool, bool]:
        # ── 회피 판정 (다단히트 + dodge_bonus 반영) ──
        # 기본: def_luc × 0.4, 상한 25
        # +dodge_bonus(유령 +20), -다단히트 페널티(다단히트시 회피율 감소)
        base_evade = min(def_luc * 0.4, 25)
        if defender is not None:
            base_evade += defender.dodge_bonus * 100  # 0.20 → +20%p
            if hit_count > 1:
                penalty = defender.dodge_penalty_per_extra_hit * 100 * (hit_count - 1)
                base_evade -= penalty
        base_evade = max(0.0, min(base_evade, 60.0))  # 상하한 가드

        if randint(1, 100) <= base_evade:
            return 0, True, False

        # ── 기본 데미지 공식 (v2) ──
        base = atk_stat * 200 / (100 + def_stat)
        base = max(base, atk_stat * 0.4)
        base *= skill_mult
        base *= role_mult
        base *= uniform(0.9, 1.1)

        # ── 첫공격 보너스 (암살자) ──
        if attacker is not None and not attacker.has_attacked:
            base *= attacker.first_attack_bonus
            attacker.has_attacked = True

        # ── 상성 적용 (defender의 저항/약점) ──
        if defender is not None:
            if damage_type == "physical":
                base *= defender.physical_resist
            elif damage_type == "magical":
                base *= defender.magical_resist

        # ── 크리티컬 ──
        crit_chance = min(atk_luc * 0.5, 40)
        is_crit = randint(1, 100) <= crit_chance
        if is_crit:
            base *= 1.5

            # ── 도적 패시브: 크리 시 70% 확률로 방어력 50% 무시 ──
            # 효과 = 원래 base를 def_stat 절반으로 다시 계산한 값으로 보정.
            #   원래: atk * 200 / (100 + def)
            #   무시: atk * 200 / (100 + def * 0.5)
            #   비율: (100 + def) / (100 + def * 0.5)
            # def가 높을수록 효과가 큼 → 일격 특화 정체성과 일치.
            if attacker is not None and attacker.job == "도적":
                if randint(1, 100) <= 70:
                    pen_ratio = (100 + def_stat) / (100 + def_stat * 0.5)
                    base *= pen_ratio

        # ── 최소 데미지 보장 (atk_stat × 0.20) ──
        # 상성으로 깎여도 공격력의 20% 이상은 보장 (Phase 1 디자인 원칙)
        # 단 회피로 0이 된 경우는 위에서 이미 return 됨
        min_dmg = atk_stat * 0.20
        if base < min_dmg:
            base = min_dmg

        return int(base), False, is_crit

    @staticmethod
    def physical(
        atk_stg: float,
        atk_luc: float,
        def_arm: float,
        def_luc: float,
        skill_mult: float = 1.0,
        role: str = "player",
        defender = None,
        attacker = None,
        hit_count: int = 1,
    ) -> tuple[int, bool, bool]:
        role_mult = DamageCalc.ROLE_MULT.get(role, 1.0)
        return DamageCalc._calc(
            atk_stg, def_arm, atk_luc, def_luc,
            skill_mult, role_mult,
            damage_type="physical",
            defender=defender,
            attacker=attacker,
            hit_count=hit_count,
        )

    @staticmethod
    def magical(
        atk_sp: float,
        atk_luc: float,
        def_sparm: float,
        def_luc: float,
        skill_mult: float = 1.0,
        role: str = "player",
        defender = None,
        attacker = None,
        hit_count: int = 1,
    ) -> tuple[int, bool, bool]:
        role_mult = DamageCalc.ROLE_MULT.get(role, 1.0)
        return DamageCalc._calc(
            atk_sp, def_sparm, atk_luc, def_luc,
            skill_mult, role_mult,
            damage_type="magical",
            defender=defender,
            attacker=attacker,
            hit_count=hit_count,
        )


# ────────────────────────────────────────────
# 스킬 메타데이터
# ────────────────────────────────────────────


def _apply_damage_with_shield(defender: EntitySnapshot, dmg: int) -> int:
    actual = dmg
    if defender.shield > 0:
        absorbed = min(defender.shield, actual)
        defender.shield -= absorbed
        actual -= absorbed
    defender.hp = max(0, defender.hp - actual)
    defender.last_damage_taken = actual
    return actual


# ────────────────────────────────────────────
# 전투 엔진
# ────────────────────────────────────────────