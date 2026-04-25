"""
BattleSession.py
─────────────────────────────────────────────
Flask용 전투 세션 클래스.

기존 Act 클래스와 차이:
  - while True / input() / print() 없음
  - 상태를 객체가 들고 있음
  - step(action) 하나 받으면 결과 dict 하나 반환
  - Flask에서 POST /battle/action → step() → JSON 응답 구조

사용 예시:
  session = BattleSession(player_snap, enemy_snap, items)
  result  = session.step("1")          # 공격
  result  = session.step("skill:셰이드 1")
  result  = session.step("item:HP_M_potion")
  result  = session.step("escape")
"""
from __future__ import annotations
import copy
from random import randint, random as _random

from Battle_Engine import (
    EntitySnapshot, DamageCalc, execute_skill,
    SKILL_META, BattleEngine, Action, BattleResult
)
from Auto_AI import PlayerAI, EnemyAI


class BattleSession:
    """
    Flask용 1:1 전투 세션.
    상태를 들고 있다가 step() 한 번에 행동 하나 처리.
    """

    def __init__(
        self,
        player: EntitySnapshot,
        enemy:  EntitySnapshot,
        items:  list = None,
        is_boss: bool = False,
    ):
        self.player  = copy.deepcopy(player)
        self.enemy   = copy.deepcopy(enemy)
        self.items   = list(items or [])
        self.is_boss = is_boss
        self.turn    = 0
        self.done    = False   # 전투 종료 여부
        self.winner  = None    # "player" | "enemy" | "escaped"

        # 적 ATB용 (간단히 매 플레이어 행동마다 적도 행동)
        self._enemy_ai = EnemyAI()

    # ── 외부에서 호출하는 메서드 ─────────────

    def step(self, action: str) -> dict:
        """
        행동 하나 처리 후 결과 반환.

        action 형식:
          "attack"              — 기본 공격
          "skill:셰이드 1"      — 스킬 사용
          "item:HP_M_potion"    — 아이템 사용
          "escape"              — 도망
          "status"              — 상태 확인 (턴 소모 없음)

        반환 dict:
          {
            "turn":         int,
            "player_action": {...},   # 플레이어 행동 결과
            "enemy_action":  {...},   # 적 행동 결과 (없으면 None)
            "player_hp":    float,
            "player_mp":    float,
            "enemy_hp":     float,
            "items":        list,
            "done":         bool,
            "winner":       str | None,
            "message":      list[str],   # 화면에 보여줄 메시지
          }
        """
        if self.done:
            return self._state(messages=["전투가 이미 종료되었습니다."])

        msgs = []

        # ── 상태 확인 (턴 소모 없음) ──────────
        if action == "status":
            return self._state(messages=["현재 상태를 확인합니다."])

        self.turn += 1

        # ── 플레이어 행동 ──────────────────────
        p_result = self._player_action(action, msgs)

        if p_result == "escaped":
            self.done   = True
            self.winner = "escaped"
            msgs.append("도망에 성공했다!")
            return self._state(messages=msgs)

        # 적 사망 체크
        if self.enemy.hp <= 0:
            self.done   = True
            self.winner = "player"
            msgs.append(f"{self.enemy.name}을(를) 처치했다!")
            return self._state(messages=msgs)

        # ── 적 행동 ───────────────────────────
        # 콘솔 전투(Act.action)와 동일하게 아이템 사용 후에도 적 턴 진행.
        # Digital Twin 원칙: UI가 달라도 전투 룰은 동일해야 함.
        self._enemy_action(msgs)

        # 플레이어 사망 체크
        if self.player.hp <= 0:
            self.done   = True
            self.winner = "enemy"
            msgs.append(f"{self.player.name}이(가) 쓰러졌다...")
            return self._state(messages=msgs)

        return self._state(messages=msgs)

    def get_skills(self) -> list:
        """사용 가능한 스킬 목록 반환"""
        result = []
        for sk in self.player.learned_skills:
            meta = SKILL_META.get(sk, {})
            result.append({
                "name":   sk,
                "mp":     meta.get("mp", 0),
                "type":   meta.get("type", ""),
                "usable": self.player.mp >= meta.get("mp", 0),
            })
        return result

    def get_items(self) -> list:
        """보유 아이템 목록 반환 (중복 제거)"""
        from collections import Counter
        cnt = Counter(self.items)
        return [{"name": k, "count": v} for k, v in cnt.items()]

    def to_battle_result(self) -> BattleResult:
        """
        전투 종료 후 BattleResult로 변환.
        BalanceHook.after_battle()이 이 타입을 요구함 →
        LOG_Manager.save_player_log()가 data/Player_LOG/에 JSON 저장.

        주의: BattleSession은 현재 상세 action log를 수집하지 않으므로
              logs=[] 빈 리스트로 반환. 상세 로그 필요 시 _enemy_action /
              _player_action에서 BattleLog를 append 하도록 추후 확장.
              (최소 요건 — 승패/턴수/최종HP — 는 로그 분석에 충분)
        """
        winner = self.winner or "unknown"
        return BattleResult(
            winner=winner,
            total_turns=self.turn,
            logs=[],
            final_player_hp=self.player.hp,
            final_enemy_hp=self.enemy.hp,
            player_name=self.player.name,
            enemy_name=self.enemy.name,
            final_player_items=list(self.items),
        )

    # ── 내부: 플레이어 행동 처리 ─────────────

    def _player_action(self, action: str, msgs: list) -> str:
        """처리 후 "ok" | "escaped" 반환"""

        # 기본 공격
        if action == "attack":
            dmg, dodge, crit = DamageCalc.physical(
                self.player.effective_stg(), self.player.luc,
                self.enemy.effective_arm(),  self.enemy.luc,
                skill_mult=1.0,
                role="player",
            )
            if dodge:
                msgs.append(f"{self.enemy.name}이(가) 공격을 회피했다!")
            else:
                self.enemy.hp -= dmg
                tag = " (치명타!)" if crit else ""
                msgs.append(f"{self.player.name} → 공격{tag} | {dmg} 데미지")
                msgs.append(f"{self.enemy.name} HP: {max(0, int(self.enemy.hp))}")

        # 스킬
        elif action.startswith("skill:"):
            skill_name = action[6:]
            dmg, mp_lack, debuff_name = execute_skill(
                skill_name, self.player, self.enemy
            )
            if mp_lack:
                msgs.append("MP가 부족합니다!")
            else:
                meta = SKILL_META.get(skill_name, {})
                if meta.get("type") == "debuff":
                    stat_kor = {"arm":"방어력","sparm":"마법방어력",
                                "stg":"공격력","spd":"스피드"}.get(
                        meta.get("debuff_stat",""), "스탯")
                    msgs.append(f"{skill_name} 사용 → {self.enemy.name} {stat_kor} 감소!")
                else:
                    self.enemy.hp -= dmg
                    msgs.append(f"{skill_name} 사용 → {dmg} 데미지")
                    msgs.append(f"{self.enemy.name} HP: {max(0, int(self.enemy.hp))}")

        # 아이템
        elif action.startswith("item:"):
            item_name = action[5:]
            if item_name not in self.items:
                msgs.append("해당 아이템이 없습니다.")
            else:
                from Battle_Engine import ITEM_META
                meta = ITEM_META.get(item_name, {})
                if meta.get("stat") == "hp":
                    before = int(self.player.hp)
                    self.player.hp = min(self.player.maxhp, self.player.hp + meta["amount"])
                    msgs.append(f"{item_name} 사용 → HP {before} → {int(self.player.hp)}")
                elif meta.get("stat") == "mp":
                    before = int(self.player.mp)
                    self.player.mp = min(self.player.maxmp, self.player.mp + meta["amount"])
                    msgs.append(f"{item_name} 사용 → MP {before} → {int(self.player.mp)}")
                self.items.remove(item_name)

        # 도망
        elif action == "escape":
            if self.is_boss:
                msgs.append("...도망칠 수 없다!")
                return "ok"
            p_spd = self.player.effective_spd()
            e_spd = self.enemy.effective_spd()
            ratio = p_spd / max(e_spd, 1.0)
            if   ratio >= 2.0: chance = 0.95
            elif ratio >= 1.5: chance = 0.80
            elif ratio >= 1.0: chance = 0.60
            elif ratio >= 0.7: chance = 0.35
            else:              chance = 0.15
            if _random() <= chance:
                return "escaped"
            else:
                msgs.append(f"도망에 실패했다! (성공률 {int(chance*100)}%)")

        else:
            msgs.append("알 수 없는 행동입니다.")

        return "ok"

    # ── 내부: 적 행동 처리 ───────────────────

    def _enemy_action(self, msgs: list):
        action = self._enemy_ai(self.enemy, self.player)

        if action.action_type == "attack":
            dmg, dodge, crit = DamageCalc.physical(
                self.enemy.effective_stg(), self.enemy.luc,
                self.player.effective_arm(), self.player.luc,
                skill_mult=1.0,
                role="monster",
            )
            if dodge:
                msgs.append(f"{self.player.name}이(가) 공격을 회피했다!")
            else:
                self.player.hp -= dmg
                tag = " (치명타!)" if crit else ""
                msgs.append(f"{self.enemy.name} → 공격{tag} | {dmg} 데미지")
                msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

        elif action.action_type == "skill":
            dmg, mp_lack, debuff_name = execute_skill(
                action.detail, self.enemy, self.player
            )
            if not mp_lack:
                if dmg > 0:
                    self.player.hp -= dmg
                    msgs.append(f"{self.enemy.name} → {action.detail} | {dmg} 데미지")
                    msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")
                elif debuff_name:
                    msgs.append(f"{self.enemy.name} → {action.detail} 사용!")

        elif action.action_type == "watch":
            msgs.append(f"{self.enemy.name}이(가) 기회를 엿보고 있다...")

    # ── 내부: 현재 상태 dict 반환 ────────────

    _DIFF_LABEL = {
        "hard":   "강함",
        "normal": "중간",
        "easy":   "약함",
        "":       "",
    }

    def _state(self, messages: list = None) -> dict:
        e = self.enemy
        diff_raw = getattr(e, "difficulty", "")
        return {
            "turn":       self.turn,
            "is_boss":    self.is_boss,   # UI: 보스전이면 도망 버튼 숨김
            "player_hp":  round(self.player.hp, 1),
            "player_mp":  round(self.player.mp, 1),
            "player_maxhp": self.player.maxhp,
            "player_maxmp": self.player.maxmp,
            "enemy_hp":   max(0.0, round(e.hp, 1)),
            "enemy_maxhp": e.maxhp,
            "enemy_name": e.name,
            # ── 몬스터 상세 정보 (UI 표시용) ──
            "enemy_info": {
                "name":             e.name,
                "lv":               e.lv,
                "difficulty":       diff_raw,
                "difficulty_label": self._DIFF_LABEL.get(diff_raw, diff_raw),
                "hp":               max(0.0, round(e.hp, 1)),
                "maxhp":            round(e.maxhp, 1),
                "mp":               round(e.mp, 1),
                "maxmp":            round(e.maxmp, 1),
                "stg":              round(e.stg, 1),
                "arm":              round(e.arm, 1),
                "sparm":            round(e.sparm, 1),
                "sp":               round(e.sp, 1),
                "spd":              round(e.spd, 1),
                "luc":              round(e.luc, 1),
            },
            "items":      self.get_items(),
            "skills":     self.get_skills(),
            "done":       self.done,
            "winner":     self.winner,
            "messages":   messages or [],
        }