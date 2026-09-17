"""Battle/Damage.py — DamageCalc, _apply_damage_with_shield"""
from __future__ import annotations

from random import randint, uniform

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
            base_evade += defender.effective_dodge_bonus() * 100  # 유령 0.20 → +20%p, 연막 버프 +35%p
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
        # 도적 주사위 패시브: 도적의 크리는 주사위(6)로만 발생.
        #   호출부(Player_Actions/Engine)가 주사위 공격 전에 attacker._suppress_crit=True를
        #   세팅하면 자연 크리를 억제한다. 반격은 플래그 미설정 → 일반 luc 크리 허용.
        # (구 도적 패시브 '크리 시 70% 확률 방어력 50% 무시'는 삭제됨)
        if attacker is not None and getattr(attacker, "_suppress_crit", False):
            is_crit = False
        else:
            crit_chance = min(atk_luc * 0.5, 40)
            is_crit = randint(1, 100) <= crit_chance
        if is_crit:
            base *= 1.5

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
    # 받는 피해 배율(불굴·철벽 의지 경감, 약점 표식 취약, 보스 그림자 경감) — 없으면 1.0이라 그대로
    mult = defender.damage_taken_mult() if hasattr(defender, "damage_taken_mult") else 1.0
    if mult != 1.0:
        dmg = int(dmg * mult)
    actual = dmg
    absorbed = 0
    if defender.shield > 0:
        absorbed = min(defender.shield, actual)
        defender.shield -= absorbed
        actual -= absorbed
    # 마나 장막: 실드 뒤에 남은 피해의 일정 비율을 MP로 대신 낸다 (MP가 모자라면 그만큼만)
    veil = defender.buff_amount("mana_veil") if hasattr(defender, "buff_amount") else 0.0
    if veil > 0 and actual > 0 and defender.mp > 0:
        paid = min(float(defender.mp), actual * veil)
        defender.mp -= paid
        actual = int(round(actual - paid))
    before = defender.hp
    defender.hp = max(0, defender.hp - actual)
    defender.last_damage_taken = actual
    # 표시 전용 장부 (시뮬 경로는 hit_ledger=None이라 비교 한 번으로 끝난다)
    if getattr(defender, "hit_ledger", None) is not None:
        defender._record_hit("absorb", absorbed)
        defender._record_hit("damage", before - defender.hp)
    return actual


# ────────────────────────────────────────────
# 흡혈 (Combat Content Brief 10-4 · 11-1 2차 5번)
#   기준 피해 = 실제 HP 감소량 + 실제 실드 감소량 (초과 피해 불인정, 실드 흡수분 인정)
#   상한 = 타격당 maxHP 4% + 시전당 maxHP 12% (연타 4타·광역 3대상이 각각 회수하면
#          탱커의 무한 회복을 재현하므로 두 겹으로 잠근다)
#   DoT(출혈·점화)·아이템 피해는 흡혈 기준이 아니다 — "공격해서 회복"(딜 의존) 원칙.
#   실전 세션(Player_Actions._player_hit)과 튜너 엔진(Engine._hit)이 같은 함수를 쓴다.
# ────────────────────────────────────────────
LIFESTEAL_HIT_CAP_RATIO = 0.04
LIFESTEAL_CAST_CAP_RATIO = 0.12


class LifestealCast:
    """시전 1회의 흡혈 예산 — 시전(행동)마다 새로 만든다.
    bonus: 이 시전에만 붙는 흡혈 비율(광풍 베기 0.08) — 버프 흡혈에 더한다."""
    __slots__ = ("pool", "bonus")

    def __init__(self, attacker: EntitySnapshot, bonus: float = 0.0):
        self.pool = float(attacker.maxhp) * LIFESTEAL_CAST_CAP_RATIO
        self.bonus = float(bonus or 0.0)


def lifesteal_heal(attacker: EntitySnapshot, basis: float, cast: "LifestealCast | None") -> float:
    """basis(실제 HP+실드 감소량)의 흡혈 비율만큼 회복. 반환: 실제 회복량.
    비율 = effective_lifesteal() + 시전 보너스(광풍 베기) — 흡혈량 가산(철벽 의지)은 시전 보너스에도 곱한다."""
    ratio = attacker.effective_lifesteal()
    if cast is not None and cast.bonus > 0:
        ratio += cast.bonus * (1.0 + attacker.buff_amount("lifesteal_amp"))
    if ratio <= 0 or basis <= 0:
        return 0.0
    heal = attacker.heal_value(min(basis * ratio, attacker.maxhp * LIFESTEAL_HIT_CAP_RATIO))
    if cast is not None:
        heal = min(heal, cast.pool)
    heal = min(heal, max(0.0, attacker.maxhp - attacker.hp))
    if heal <= 0:
        return 0.0
    attacker.hp += heal
    if cast is not None:
        cast.pool -= heal
    if getattr(attacker, "hit_ledger", None) is not None:   # 표시 전용 장부
        attacker._record_hit("heal", heal, via="lifesteal")
    return heal


def deal_damage_with_lifesteal(attacker: EntitySnapshot, defender: EntitySnapshot,
                               dmg: int, cast: "LifestealCast | None") -> tuple:
    """실드 경유 피해 적용 + 공격자 흡혈. 반환 (HP 피해, 흡혈 회복량)."""
    hp_before, sh_before = defender.hp, defender.shield
    hp_dmg = _apply_damage_with_shield(defender, int(dmg))
    basis = (hp_before - defender.hp) + (sh_before - defender.shield)
    return hp_dmg, lifesteal_heal(attacker, basis, cast)


# ────────────────────────────────────────────
# 전투 엔진
# ────────────────────────────────────────────