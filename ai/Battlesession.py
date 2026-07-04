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

from ai.battle import (
    apply_element_and_react, check_element_reaction, try_apply_element_aura_and_status,
    ITEM_META, Debuff, Buff, _current_element,
    SKILL_META as _SKILL_META_REF,
    EntitySnapshot, DamageCalc, execute_skill,
    SKILL_META, BattleEngine, Action, BattleResult, TurnLog,
)
from ai.Auto_AI import PlayerAI, EnemyAI

from ai.battle_session.Targeting      import TargetingMixin
from ai.battle_session.ATB_Flow       import ATBFlowMixin
from ai.battle_session.Rewards        import RewardsMixin
from ai.battle_session.Player_Actions import PlayerActionsMixin
from ai.battle_session.Enemy_Actions  import EnemyActionsMixin
from ai.battle_session.State          import StateMixin


class BattleSession(
    TargetingMixin,
    ATBFlowMixin,
    RewardsMixin,
    PlayerActionsMixin,
    EnemyActionsMixin,
    StateMixin,
):
    """
    Flask용 1:1/다대일 전투 세션.
    step() 한 번에 행동 하나 처리. 세부 기능은 battle_session 패키지 mixin이 담당.
    본체는 흐름 제어만: __init__, step, enemy, get_skills, get_items.
    """

    def __init__(
        self,
        player: EntitySnapshot,
        enemy:  EntitySnapshot = None,
        items:  list = None,
        is_boss: bool = False,
        enemies: list = None,
        enemy_origins: list = None,   # ★ 원본 적 객체 (exp_reward용)
        player_original = None,       # ★ 원본 Player 객체 (atb_remainder 이월용)
    ):
        """
        BattleSession — 1대1 또는 1대N 전투 세션.
 
        호환성:
          - 기존 코드는 enemy=... 단수로 호출 (1대1 전투).
          - 다대일은 enemies=[e1, e2, e3] 리스트로 호출 (Phase 2).
          - 내부에서는 항상 self.enemies 리스트로 관리.
          - self.enemy는 첫 번째 살아있는 적을 가리키는 동적 프로퍼티 (구 코드 호환).
 
        enemy_origins (신규):
          - self.enemies가 EntitySnapshot이라 exp_reward() 호출 불가.
          - 원본(Unit/_SnapUnit) 객체를 같은 인덱스로 보존해서 전투 종료 시 사용.
          - None이면 [] — App.py가 폴백 경험치 처리.
        """
        self.player  = copy.deepcopy(player)
        # ★ 원본 Player 참조 (atb_remainder 이월용, 없을 수도 있음)
        self.player_original = player_original
 
         # ── enemies 리스트로 통일 ──
        # 단수 enemy로 호출되면 자동으로 [enemy]로 변환.
        if enemies is not None:
            self.enemies = [copy.deepcopy(e) for e in enemies]
        elif enemy is not None:
            self.enemies = [copy.deepcopy(enemy)]
        else:
            raise ValueError("BattleSession은 enemy 또는 enemies 중 하나를 받아야 합니다")

        # ── ★ 다중 몹 스탯 배율 (#2) ──
        # 다대일 전투 시 적 스탯을 약화 (도전성 + 공정성).
        # 1대1: 100%, 1대2: 90%, 1대3: 80%
        # 적용 스탯: HP/STG/SP/ARM/SPARM (SPD 제외 — ATB 행동 횟수에 영향 X)
        # 보스 전투는 제외 (단일 전투이므로 자동으로 100%).
        if len(self.enemies) >= 2 and not is_boss:
            mult = {2: 0.9, 3: 0.8}.get(len(self.enemies), 0.8)
            for e in self.enemies:
                # HP 비율 유지 (현재 HP도 비례 감소)
                hp_ratio = e.hp / e.maxhp if e.maxhp > 0 else 1.0
                e.maxhp = int(e.maxhp * mult)   # 정수화 — 몬스터 HP 소수점 버그 방지
                e.hp = int(e.maxhp * hp_ratio)
                # 공격/방어 스탯 약화
                e.stg = e.stg * mult
                e.sp = e.sp * mult
                e.arm = e.arm * mult
                e.sparm = e.sparm * mult
                # SPD는 변경 안 함 — ATB 누적/행동 횟수 동일 유지

        # 각 적에게 인덱스 부여 (UI 슬롯 매핑용: 0=슬롯3, 1=슬롯4, 2=슬롯5)
        for i, e in enumerate(self.enemies):
            e._slot_index = i
 
        # ── 원본 적 객체 보존 (★ 신규) ──
        # self.enemies[i] (EntitySnapshot) ↔ self._origins[i] (Unit/_SnapUnit)
        # 길이는 self.enemies와 동일해야 함. 부족하면 None으로 패딩.
        self._origins = list(enemy_origins or [])
        while len(self._origins) < len(self.enemies):
            self._origins.append(None)
 
        # ── 기본 전투 상태 필드 ──
        self.items   = list(items or [])
        self.is_boss = is_boss
        self.turn    = 0
        self.done    = False   # 전투 종료 여부
        self.winner  = None    # "player" | "enemy" | "escaped"
 
        # 행동 로그 — BehaviorAnalyzer 입력용.
        self.logs: list = []
 
       # 적 AI
        self._enemy_ai = EnemyAI()

        # 현재 타깃 인덱스 (플레이어가 슬롯 클릭으로 변경)
        self._target_idx = 0

        # DB 저장용 액션 카운터 (Phase 3)
        self.skills_used = 0
        self.items_used  = 0
        # 특수 아이템 버프 상태
        self._next_skill_bonus  = 1.0   # 집중물약: 다음 스킬 데미지 배율
        self._pending_atb_bonus = 0     # 신속물약: 다음 행동 후 ATB 추가

        # ★ ATB 시스템 (사용자 모델 — 큐 기반 턴제 + 추가 행동권):
        # 시작값: 이전 전투 atb_remainder 그대로 (SPD 안 더함)
        #   1번 전투 종료 시 잔여값 그대로 다음 전투 시작 ATB로 사용 (SPD 더하지 않음)
        #   ex) 1번 전투 끝 잔여 5 → 2번 전투 시작 ATB = 5
        #   행동마다 +SPD 누적, 100 도달 시 추가 행동권 발동
        # ※ atb_remainder는 원본 Player 객체에 있음 (snap엔 없음)
        if self.player_original is not None:
            self.player_atb: float = float(getattr(self.player_original, "atb_remainder", 0.0))
            try:
                self.player_original.atb_remainder = 0.0
            except Exception:
                pass
        else:
            # 폴백 (시뮬레이션 등 player_original 없는 경우)
            self.player_atb: float = float(getattr(self.player, "atb_remainder", 0.0))
            try:
                self.player.atb_remainder = 0.0
            except Exception:
                pass

        # 적은 매 전투마다 0에서 시작 (이월 없음, first_strike만 100)
        self.enemy_atbs: list  = [0.0 for _ in self.enemies]

        # 적 first_strike 처리 (암살자) — 첫 tick부터 적이 100을 갖고 시작.
        for i, e in enumerate(self.enemies):
            if getattr(e, "first_strike", False):
                self.enemy_atbs[i] = 100.0
 
        # 전사 패시브용 '공격 행동' 카운터 — 적 공격(일반공격/공격형 스킬) 3회마다 발동
        # 카운트는 Player_Actions._count_warrior_attack()에서만 증가 (아이템/버프/힐 제외)
        # 새 전투(BattleSession 생성)마다 0으로 초기화
        self._warrior_attack_count = 0

        # ★ 행동 큐 (SPD 내림차순 턴제) — 라운드 시작 시 채워짐
        # 큐 형식: [(actor_type, idx), ...]  actor_type: "player" | "enemy"
        self.action_queue: list = []
        self._build_round_queue()
 
        # ── 처치된 적 원본 리스트 (★ 신규) ──
        # 적이 죽을 때 self._origins[i] 를 여기에 추가.
        # 형식: [Unit | _SnapUnit | None, ...]
        # None인 경우는 호출 측이 origins를 안 줬을 때 — App.py가 폴백 처리.
        self.defeated_origins = []

    # 기존 1대1 코드는 self.enemy 직접 접근. 살아있는 첫 번째 적 반환.

    @property
    def enemy(self):
        for e in self.enemies:
            if e.hp > 0:
                return e
        # 모두 죽었으면 마지막 적 (메시지 표시용)
        return self.enemies[-1] if self.enemies else None

    def step(self, action: str) -> dict:
        """
        ATB 기반 step (★ 큐 기반 턴제 + 추가 행동권).

        시스템 핵심:
          - 기본은 턴제: 라운드 시작 시 SPD 내림차순 큐 생성
          - 행동 후 모든 살아있는 entity ATB += 자기 SPD
          - 본인 ATB ≥ 100이면 차례 직후 추가 행동 1회 (보너스)
          - 추가 행동 후 ATB -= 100, ATB 누적은 추가 행동에서도 발생

        action:
          - "attack" / "skill:이름" / "item:이름" / "escape" → 플레이어 행동
          - "attack:N" / "skill:이름:N" → 타깃 인덱스 지정
          - "auto" → 적 1마리 자동 행동 (UI가 next_actor='enemy'일 때 호출)
          - "status" → 상태만 반환 (행동 없음)
        """
        if self.done:
            return self._state(messages=["전투가 이미 종료되었습니다."],
                               next_actor="done")

        msgs = []

        # ── 상태 확인 (행동 없음) ──
        if action == "status":
            next_actor, idx = self._peek_next_actor()
            return self._state(messages=["현재 상태를 확인합니다."],
                               next_actor=next_actor, acting_enemy_idx=idx)

        # 큐 비었으면 새 라운드 시작
        if not self.action_queue:
            self._build_round_queue()

        # 죽은 적 큐에서 정리
        self._cleanup_dead_from_queue()

        # 큐 다 비면 — 모든 적 죽은 상태 (이론상 _alive_enemies 체크가 먼저)
        if not self.action_queue:
            self.done = True
            self.winner = "player"
            try:
                self.player.atb_remainder = float(self.player_atb)
                # ★ 원본에도 동기화 (이월값 유지)
                if self.player_original is not None:
                    self.player_original.atb_remainder = float(self.player_atb)
            except Exception:
                pass
            msgs.append("모든 적을 처치했다!")
            return self._state(messages=msgs, next_actor="done")

        actor_type, idx = self.action_queue[0]   # peek (pop은 행동 후)

        # ════════════════════════════════════════════════════════
        # 케이스 A: 플레이어 차례
        # ════════════════════════════════════════════════════════
        if actor_type == "player":
            if action == "auto":
                # 잘못 호출 — 플레이어 차례인데 auto 옴 (적 차례 자동 호출 실수)
                return self._state(messages=["플레이어 차례입니다."],
                                   next_actor="player", acting_enemy_idx=-1)

            self.turn += 1

            # ── 원소 상태이상 틱 (점화 데미지 등) ──
            if hasattr(self.player, "tick_status_effects"):
                for m in self.player.tick_status_effects():
                    msgs.append(m)
            # 점화로 사망
            if self.player.hp <= 0:
                self.done = True
                self.winner = "enemy"
                msgs.append(f"🔥 {self.player.name}이(가) 점화 데미지로 쓰러졌다...")
                return self._state(messages=msgs, next_actor="done")

            # ── 마비 행동 실패 ──
            if hasattr(self.player, "is_paralyzed") and self.player.is_paralyzed():
                msgs.append(f"⚡ {self.player.name}이(가) 마비로 행동에 실패했다!")
                self.player.tick_buffs()
                self.action_queue.pop(0)
                self._accumulate_atb_all()
                self._cleanup_dead_from_queue()
                if not self.action_queue:
                    self._build_round_queue()
                    self._cleanup_dead_from_queue()
                next_actor, next_idx = self._peek_next_actor()
                return self._state(messages=msgs, next_actor=next_actor, acting_enemy_idx=next_idx)

            # (전사 패시브 카운트는 Player_Actions._count_warrior_attack에서
            #  '적 공격 행동'만 카운트 — 여기서 행동마다 세던 구규칙은 제거됨)

            # 플레이어 행동 처리
            p_result = self._player_action(action, msgs)
            # 신속물약: 행동 후 ATB 추가 획득
            if self._pending_atb_bonus > 0:
                self.player_atb += float(self._pending_atb_bonus)
                self._pending_atb_bonus = 0
            self.player.tick_buffs()

            # 큐에서 자신 제거
            self.action_queue.pop(0)

            # 도망 성공
            if p_result == "escaped":
                self.done = True
                self.winner = "escaped"
                try:
                    self.player.atb_remainder = float(self.player_atb)
                    # ★ 원본에도 동기화 (이월값 유지)
                    if self.player_original is not None:
                        self.player_original.atb_remainder = float(self.player_atb)
                except Exception:
                    pass
                msgs.append("도망에 성공했다!")
                return self._state(messages=msgs, next_actor="done")

            # 모든 적 사망 체크
            if not self._alive_enemies():
                self.done = True
                self.winner = "player"
                try:
                    self.player.atb_remainder = float(self.player_atb)
                    # ★ 원본에도 동기화 (이월값 유지)
                    if self.player_original is not None:
                        self.player_original.atb_remainder = float(self.player_atb)
                except Exception:
                    pass
                if len(self.enemies) > 1:
                    msgs.append("모든 적을 처치했다!")
                else:
                    msgs.append(f"{self.enemies[0].name}을(를) 처치했다!")
                return self._state(messages=msgs, next_actor="done")

            # ── ★ 모든 살아있는 entity ATB += 자기 SPD ──
            self._accumulate_atb_all()

            # ── ATB ≥ 100 → 추가 행동권 (BONUS) ──
            if self.player_atb >= 100.0:
                self.player_atb -= 100.0
                # 큐 맨 앞에 자신 다시 삽입
                self.action_queue.insert(0, ("player", -1))
                msgs.append(f"⚡ {self.player.name} 추가 행동! (BONUS)")

            # 다음 행동자 결정 (큐 정리 후 peek)
            self._cleanup_dead_from_queue()
            if not self.action_queue:
                self._build_round_queue()
                self._cleanup_dead_from_queue()
            next_actor, next_idx = self._peek_next_actor()
            return self._state(messages=msgs,
                               next_actor=next_actor,
                               acting_enemy_idx=next_idx)

        # ════════════════════════════════════════════════════════
        # 케이스 B: 적 차례 (action == "auto" 호출이 와야 정상)
        # ════════════════════════════════════════════════════════
        elif actor_type == "enemy":
            # auto가 아닌 액션이 왔는데 적 차례 — 사용자가 입력한 거니 무시
            # (UI가 적 차례엔 버튼 비활성화해야 정상)
            if action != "auto":
                # ★ 플레이어가 적 차례에 미리 입력한 행동 — 프론트가 예약 처리할 수 있게
                #   action_ignored 플래그를 내려준다 (Actions.js가 보관 후 플레이어 차례에 재전송).
                st = self._state(messages=["적이 행동 중입니다."],
                                 next_actor="enemy",
                                 acting_enemy_idx=idx)
                st["action_ignored"] = True
                return st

            enemy = self.enemies[idx]

            # 이미 죽은 적이면 큐에서 제거 후 다음으로 (재귀 1회만)
            if enemy.hp <= 0:
                self.action_queue.pop(0)
                self._cleanup_dead_from_queue()
                if not self.action_queue:
                    self._build_round_queue()
                next_actor, next_idx = self._peek_next_actor()
                return self._state(messages=msgs,
                                   next_actor=next_actor,
                                   acting_enemy_idx=next_idx)

            # ── 원소 상태이상 틱 (점화 데미지 등) ──
            if hasattr(enemy, "tick_status_effects"):
                for m in enemy.tick_status_effects():
                    msgs.append(m)
            # 점화로 사망
            if enemy.hp <= 0:
                self.action_queue.pop(0)
                self._cleanup_dead_from_queue()
                msgs.append(f"🔥 {enemy.name}이(가) 점화 데미지로 쓰러졌다!")
                if not self._alive_enemies():
                    self.done = True
                    self.winner = "player"
                    msgs.append("모든 적을 처치했다!")
                    return self._state(messages=msgs, next_actor="done")
                if not self.action_queue:
                    self._build_round_queue()
                    self._cleanup_dead_from_queue()
                next_actor, next_idx = self._peek_next_actor()
                return self._state(messages=msgs, next_actor=next_actor, acting_enemy_idx=next_idx)

            # ── 적 마비 행동 실패 ──
            if hasattr(enemy, "is_paralyzed") and enemy.is_paralyzed():
                msgs.append(f"⚡ {enemy.name}이(가) 마비로 행동에 실패했다!")
                self.action_queue.pop(0)
                self._accumulate_atb_all()
                self._cleanup_dead_from_queue()
                if not self.action_queue:
                    self._build_round_queue()
                    self._cleanup_dead_from_queue()
                next_actor, next_idx = self._peek_next_actor()
                return self._state(messages=msgs, next_actor=next_actor, acting_enemy_idx=next_idx)

            # 적 행동
            self._single_enemy_action(enemy, msgs)
            self.action_queue.pop(0)

            # 플레이어 사망 체크
            if self.player.hp <= 0:
                self.done = True
                self.winner = "enemy"
                try:
                    self.player.atb_remainder = float(self.player_atb)
                    # ★ 원본에도 동기화 (이월값 유지)
                    if self.player_original is not None:
                        self.player_original.atb_remainder = float(self.player_atb)
                except Exception:
                    pass
                msgs.append(f"{self.player.name}이(가) 쓰러졌다...")
                return self._state(messages=msgs, next_actor="done")

            # ── 모든 살아있는 entity ATB += 자기 SPD ──
            self._accumulate_atb_all()

            # ── 적 ATB ≥ 100 → 추가 행동권 (BONUS) ──
            if self.enemy_atbs[idx] >= 100.0:
                self.enemy_atbs[idx] -= 100.0
                self.action_queue.insert(0, ("enemy", idx))
                msgs.append(f"⚡ {enemy.name} 추가 행동! (BONUS)")

            # 다음 행동자
            self._cleanup_dead_from_queue()
            if not self.action_queue:
                self._build_round_queue()
                self._cleanup_dead_from_queue()
            next_actor, next_idx = self._peek_next_actor()
            return self._state(messages=msgs,
                               next_actor=next_actor,
                               acting_enemy_idx=next_idx)

        # 폴백 (도달 X)
        return self._state(messages=msgs, next_actor="player")

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