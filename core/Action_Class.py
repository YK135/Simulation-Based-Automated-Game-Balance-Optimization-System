"""
Action_Class.py
─────────────────────────────────────────────
수동/자동 전투 UI + 판정 처리.

출력 방식:
  - 모든 전투 메시지는 한 줄씩 0.35초 간격으로 자동 출력
  - 행동 후 [Enter] 없이 자동으로 다음 화면으로 넘어감
  - 수동/자동 전투 동일 딜레이 방식 사용

설계 원칙:
  - 모든 데미지/스킬 판정은 Battle_Engine.py 경유
  - 전역 스킬 객체 없음 — player.skill.learned_skills만 참조
"""
from __future__ import annotations
import time

try:
    from ai.Battle_Engine import (
        BattleEngine, EntitySnapshot, DamageCalc,
        execute_skill, SKILL_META, ITEM_META, Action,
    )
    from ai.Auto_AI import PlayerAI, EnemyAI
    from interface.Game_Interface import Battle_interface, show_enemy_status, clear
except ModuleNotFoundError:
    from ai.Battle_Engine import (
        BattleEngine, EntitySnapshot, DamageCalc,
        execute_skill, SKILL_META, ITEM_META, Action,
    )
    from ai.Auto_AI import PlayerAI, EnemyAI
    from interface.Game_Interface import Battle_interface, show_enemy_status, clear


# ────────────────────────────────────────────
# 타이밍 상수
# ────────────────────────────────────────────

LINE_DELAY = 0.35   # 수동 전투 메시지 딜레이
AUTO_DELAY = 0.25   # 자동 전투 로그 딜레이
END_PAUSE  = 1.2    # 전투 종료 후 자동 대기


def _p(msg: str, delay: float = LINE_DELAY):
    """한 줄 출력 후 딜레이 (자동 진행)"""
    print(msg, flush=True)
    time.sleep(delay)


# ────────────────────────────────────────────
# 유틸
# ────────────────────────────────────────────

def _snap_player(player, item_list: list) -> EntitySnapshot:
    return EntitySnapshot.from_player(player)


def _snap_enemy(enemy) -> EntitySnapshot:
    return EntitySnapshot.from_enemy(enemy)


def _sync_back(player, snap: EntitySnapshot):
    player.hp = snap.hp
    player.mp = snap.mp


def _use_item(p_snap: EntitySnapshot, item_list: list, item_name: str) -> str:
    meta = ITEM_META.get(item_name)
    if not meta or item_name not in item_list:
        return "  해당 아이템이 없습니다."
    if meta["stat"] == "hp":
        before = int(p_snap.hp)
        p_snap.hp = min(p_snap.maxhp, p_snap.hp + meta["amount"])
        item_list.remove(item_name)
        return f"  {item_name} 사용 → HP {before} → {int(p_snap.hp)}"
    elif meta["stat"] == "mp":
        before = int(p_snap.mp)
        p_snap.mp = min(p_snap.maxmp, p_snap.mp + meta["amount"])
        item_list.remove(item_name)
        return f"  {item_name} 사용 → MP {before} → {int(p_snap.mp)}"
    return "  사용할 수 없는 아이템입니다."


# ────────────────────────────────────────────
# 자동 전투 로그 — 한 줄씩 자동 출력
# ────────────────────────────────────────────

def _print_auto_log(result, player_name: str, enemy_name: str):
    print("\n" + "=" * 45, flush=True)
    _p("  ◆ 자동 전투 로그", AUTO_DELAY)
    print("=" * 45, flush=True)

    for log in result.logs:
        actor = player_name if log.actor == "player" else enemy_name
        tag   = (" ★크리!" if log.is_crit else "") + (" (회피)" if log.is_dodge else "")

        if log.action == "attack":
            if log.is_dodge:
                _p(f"  턴{log.turn:>2} [{actor}] 공격 → 회피!", AUTO_DELAY)
            else:
                _p(f"  턴{log.turn:>2} [{actor}] 공격 → {log.damage_dealt}의 데미지{tag}", AUTO_DELAY)
        elif log.action == "skill":
            _p(f"  턴{log.turn:>2} [{actor}] {log.action_detail} → {log.damage_dealt}의 데미지{tag}", AUTO_DELAY)
        elif log.action in ("item", "heal"):
            _p(f"  턴{log.turn:>2} [{actor}] {log.action_detail} 사용", AUTO_DELAY)
        elif log.action in ("buff", "debuff"):
            _p(f"  턴{log.turn:>2} [{actor}] {log.action_detail}", AUTO_DELAY)

    winner = player_name if result.winner == "player" else enemy_name
    print("", flush=True)
    _p(f"  결과: {winner} 승리 | 총 {result.total_turns}턴 | 잔여 HP {result.final_player_hp:.0f}", 0)
    print("=" * 45, flush=True)
    time.sleep(END_PAUSE)


# ────────────────────────────────────────────
# 수동 전투 — 행동 처리 함수들
# ────────────────────────────────────────────

def _manual_attack(p_snap: EntitySnapshot, e_snap: EntitySnapshot,
                   player_name: str, enemy_name: str):
    dmg, is_dodge, is_crit = DamageCalc.physical(
        p_snap.effective_stg(), p_snap.luc,
        e_snap.effective_arm(), e_snap.luc,
        role="player",
    )
    if is_dodge:
        _p(f"  {enemy_name}이(가) 공격을 회피했다!")
        return

    actual = dmg
    if e_snap.shield > 0:
        absorbed = min(e_snap.shield, dmg)
        e_snap.shield -= absorbed
        actual = dmg - absorbed
        _p(f"  실드가 {absorbed} 흡수!")
    e_snap.hp -= actual
    tag = " ★크리!" if is_crit else ""
    _p(f"  {player_name} → 공격{tag} | {actual} 데미지")
    _p(f"  {enemy_name} HP: {max(0, int(e_snap.hp))}")


def _manual_skill(p_snap: EntitySnapshot, e_snap: EntitySnapshot,
                  skill_name: str, enemy_name: str, player_name: str) -> bool:
    """처리 성공 여부 반환"""
    meta = SKILL_META.get(skill_name)
    if not meta:
        _p("  알 수 없는 스킬입니다.", 0.6)
        return False

    dmg, mp_lack, detail = execute_skill(skill_name, p_snap, e_snap)
    if mp_lack:
        _p("  MP가 부족합니다!", 0.6)
        return False

    stype = meta.get("type", "")

    if stype == "debuff":
        stat_kor = {"arm": "방어력", "sparm": "마법방어력",
                    "stg": "공격력", "spd": "스피드"}.get(meta.get("debuff_stat", ""), "스탯")
        _p(f"  {skill_name} → {enemy_name} {stat_kor} 감소!")
    elif stype == "buff":
        stat_kor = {"stg": "공격력", "arm": "방어력",
                    "spd": "스피드", "mp_efficiency": "MP 효율"}.get(meta.get("buff_stat", ""), "스탯")
        _p(f"  {skill_name} → {player_name} {stat_kor} 증가! ({meta.get('buff_turns', 0)}턴)")
    elif stype == "heal":
        _p(f"  {skill_name} → HP 회복! (현재 {int(p_snap.hp)}/{int(p_snap.maxhp)})")
    elif stype == "shield":
        _p(f"  {skill_name} → 실드 {int(p_snap.shield)} 생성!")
    else:
        actual = dmg
        if e_snap.shield > 0 and dmg > 0:
            absorbed = min(e_snap.shield, dmg)
            e_snap.shield -= absorbed
            actual = dmg - absorbed
            _p(f"  실드가 {absorbed} 흡수!")
        e_snap.hp -= actual
        _p(f"  {skill_name} → {actual} 데미지")
        _p(f"  {enemy_name} HP: {max(0, int(e_snap.hp))}")

    return True


def _enemy_turn(e_snap: EntitySnapshot, p_snap: EntitySnapshot,
                enemy_ai: EnemyAI, enemy_name: str, player_name: str):
    action = enemy_ai(e_snap, p_snap)

    if action.action_type == "watch":
        _p(f"  {enemy_name}이(가) 기회를 엿보고 있다...")
        return

    if action.action_type == "skill":
        dmg, mp_lack, detail = execute_skill(action.detail, e_snap, p_snap)
        if not mp_lack:
            if dmg > 0:
                actual = dmg
                if p_snap.shield > 0:
                    absorbed = min(p_snap.shield, dmg)
                    p_snap.shield -= absorbed
                    actual = dmg - absorbed
                    _p(f"  실드가 {absorbed} 흡수!")
                p_snap.hp -= actual
                p_snap.last_damage_taken = actual
                _p(f"  {enemy_name} → {action.detail} | {actual} 데미지")
                _p(f"  {player_name} HP: {max(0, int(p_snap.hp))}")
            elif detail:
                _p(f"  {enemy_name} → {action.detail} 사용!")
            return

    # 기본 공격
    dmg, is_dodge, is_crit = DamageCalc.physical(
        e_snap.effective_stg(), e_snap.luc,
        p_snap.effective_arm(), p_snap.luc,
        role="monster",
    )
    if is_dodge:
        _p(f"  {player_name}이(가) 공격을 회피했다!")
        return

    actual = dmg
    if p_snap.shield > 0:
        absorbed = min(p_snap.shield, dmg)
        p_snap.shield -= absorbed
        actual = dmg - absorbed
        _p(f"  실드가 {absorbed} 흡수!")
    p_snap.hp -= actual
    p_snap.last_damage_taken = actual
    tag = " ★크리!" if is_crit else ""
    _p(f"  {enemy_name} → 공격{tag} | {actual} 데미지")
    _p(f"  {player_name} HP: {max(0, int(p_snap.hp))}")


# ────────────────────────────────────────────
# Act 클래스
# ────────────────────────────────────────────

class Act:
    """
    Main.py: Act(player, enemy, item_list, is_boss=False).action()
    반환값: "win" | "lose" | "escaped"
    """

    def __init__(self, player, enemy, item_list: list, is_boss: bool = False):
        self.player    = player
        self.enemy     = enemy
        self.item_list = item_list
        self.is_boss   = is_boss
        self.enemy_ai  = EnemyAI()

    def action(self) -> str:
        p_snap = _snap_player(self.player, self.item_list)
        e_snap = _snap_enemy(self.enemy)

        while True:
            Battle_interface(p_snap, e_snap)

            if p_snap.hp <= 0:
                _sync_back(self.player, p_snap)
                return "lose"
            if e_snap.hp <= 0:
                _sync_back(self.player, p_snap)
                return "win"

            key = input("입력: ").strip().lower()
            print()

            # ── 1. 기본 공격 ────────────────────
            if key == "1":
                _manual_attack(p_snap, e_snap, self.player.name, self.enemy.name)
                if e_snap.hp <= 0:
                    _sync_back(self.player, p_snap)
                    time.sleep(END_PAUSE)
                    return "win"
                _enemy_turn(e_snap, p_snap, self.enemy_ai, self.enemy.name, self.player.name)
                p_snap.tick_debuffs(); p_snap.tick_buffs()
                e_snap.tick_debuffs(); e_snap.tick_buffs()
                time.sleep(0.6)

            # ── 2. 스킬 ─────────────────────────
            elif key == "2":
                skills = p_snap.learned_skills
                if not skills:
                    _p("  사용 가능한 스킬이 없습니다.", 0.8)
                    continue

                print("  ── 스킬 목록 ──")
                for i, sk in enumerate(skills, 1):
                    meta    = SKILL_META.get(sk, {})
                    mp_cost = meta.get("mp", 0)
                    usable  = "O" if p_snap.mp >= mp_cost else "X"
                    print(f"  {i}. {sk}  (MP {mp_cost})  [{usable}]")
                print("  0. 취소\n")

                sk_key = input("  선택: ").strip()
                print()
                if sk_key == "0":
                    continue
                try:
                    idx = int(sk_key) - 1
                    if not (0 <= idx < len(skills)):
                        _p("  잘못된 번호입니다.", 0.6)
                        continue
                    ok = _manual_skill(p_snap, e_snap, skills[idx],
                                       self.enemy.name, self.player.name)
                    if not ok:
                        continue
                    if e_snap.hp <= 0:
                        _sync_back(self.player, p_snap)
                        time.sleep(END_PAUSE)
                        return "win"
                    _enemy_turn(e_snap, p_snap, self.enemy_ai, self.enemy.name, self.player.name)
                    p_snap.tick_debuffs(); p_snap.tick_buffs()
                    e_snap.tick_debuffs(); e_snap.tick_buffs()
                    time.sleep(0.6)
                except ValueError:
                    _p("  숫자를 입력하세요.", 0.6)
                    continue

            # ── 3. 아이템 ────────────────────────
            elif key == "3":
                if not self.item_list:
                    _p("  아이템이 없습니다.", 0.8)
                    continue

                from collections import Counter
                cnt   = Counter(self.item_list)
                items = list(cnt.keys())
                print("  ── 아이템 목록 ──")
                for i, it in enumerate(items, 1):
                    print(f"  {i}. {it}  ×{cnt[it]}")
                print("  0. 취소\n")

                it_key = input("  선택: ").strip()
                print()
                if it_key == "0":
                    continue
                try:
                    idx = int(it_key) - 1
                    if not (0 <= idx < len(items)):
                        _p("  잘못된 번호입니다.", 0.6)
                        continue
                    msg = _use_item(p_snap, self.item_list, items[idx])
                    _p(msg, 0.8)
                except ValueError:
                    _p("  숫자를 입력하세요.", 0.6)
                    continue

            # ── 4. 내 상태 ───────────────────────
            elif key == "4":
                clear()
                print(f"  ── {self.player.name} 상태 ──")
                print(f"  HP : {int(p_snap.hp)} / {int(p_snap.maxhp)}")
                print(f"  MP : {int(p_snap.mp)} / {int(p_snap.maxmp)}")
                print(f"  STG: {round(p_snap.effective_stg(), 1)}  "
                      f"ARM: {round(p_snap.effective_arm(), 1)}")
                print(f"  SPD: {round(p_snap.effective_spd(), 1)}  LUC: {p_snap.luc}")
                if p_snap.buffs:
                    print(f"  버프: {[b.name for b in p_snap.buffs]}")
                if p_snap.debuffs:
                    print(f"  디버프: {[d.name for d in p_snap.debuffs]}")
                input("\n  [Enter] 계속...")
                continue

            # ── 5. 적 상태 ───────────────────────
            elif key == "5":
                show_enemy_status(e_snap)
                input("\n  [Enter] 계속...")
                continue

            # ── 6. 도망 ──────────────────────────
            elif key == "6":
                if self.is_boss:
                    _p("  ...도망칠 수 없다!", 0.8)
                    continue
                from random import random as _rnd
                ratio = p_snap.effective_spd() / max(e_snap.effective_spd(), 1.0)
                if   ratio >= 2.0: chance = 0.95
                elif ratio >= 1.5: chance = 0.80
                elif ratio >= 1.0: chance = 0.60
                elif ratio >= 0.7: chance = 0.35
                else:              chance = 0.15

                if _rnd() <= chance:
                    _p("  도망에 성공했다!")
                    time.sleep(END_PAUSE)
                    _sync_back(self.player, p_snap)
                    return "escaped"
                else:
                    _p(f"  도망에 실패했다! (성공률 {int(chance*100)}%)")
                    _enemy_turn(e_snap, p_snap, self.enemy_ai,
                                self.enemy.name, self.player.name)
                    p_snap.tick_debuffs(); p_snap.tick_buffs()
                    e_snap.tick_debuffs(); e_snap.tick_buffs()
                    time.sleep(0.6)

            # ── a. 자동 전투 ─────────────────────
            elif key == "a":
                _p("  [자동 전투 시작...]", 0.5)
                clear()

                engine = BattleEngine(p_snap, e_snap)
                result = engine.run(PlayerAI("balanced"), EnemyAI())

                _print_auto_log(result, self.player.name, self.enemy.name)

                if result.winner == "player":
                    p_snap.hp = result.final_player_hp
                    _sync_back(self.player, p_snap)
                    return "win"
                elif result.winner == "enemy":
                    self.player.hp = 0
                    return "lose"
                else:
                    _sync_back(self.player, p_snap)
                    return "win"

            else:
                _p("  1~6, a 중 입력하세요.", 0.5)
                continue

            # 턴 종료 후 사망 체크
            if p_snap.hp <= 0:
                _sync_back(self.player, p_snap)
                time.sleep(END_PAUSE)
                return "lose"
            if e_snap.hp <= 0:
                _sync_back(self.player, p_snap)
                time.sleep(END_PAUSE)
                return "win"