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
    ITEM_META, Debuff, Buff,
    _current_element,
    SKILL_META as _SKILL_META_REF,
    EntitySnapshot, DamageCalc, execute_skill,
    SKILL_META, BattleEngine, Action, BattleResult, TurnLog
)
from ai.Auto_AI import PlayerAI, EnemyAI


class BattleSession:
    """
    Flask용 1:1 전투 세션.
    상태를 들고 있다가 step() 한 번에 행동 하나 처리.
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
                e.maxhp = e.maxhp * mult
                e.hp = e.maxhp * hp_ratio
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
 
        # 전사 패시브용 행동 카운터 — 공격 3회마다 발동
        # (이전 v2 패치에서 추가된 필드 — 유지)
        self._warrior_action_count = 0

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

    def _alive_enemies(self) -> list:
        """살아있는 적 리스트"""
        return [e for e in self.enemies if e.hp > 0]

    def _current_target(self):
        """플레이어 공격 대상 — 인덱스가 죽었으면 살아있는 첫 번째로 자동 변경"""
        if 0 <= self._target_idx < len(self.enemies):
            t = self.enemies[self._target_idx]
            if t.hp > 0:
                return t
        # 자동 폴백
        for e in self.enemies:
            if e.hp > 0:
                return e
        return None

    # ── 외부에서 호출하는 메서드 ─────────────

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

            # 전사 패시브: 행동 3회마다 maxhp 10% 회복
            self._warrior_action_count += 1
            if (self.player.job == "전사" and
                self._warrior_action_count % 3 == 0 and
                self.player.hp > 0):
                warrior_msg = self.player.passive_on_turn_start()
                if warrior_msg:
                    msgs.append(warrior_msg)

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
                return self._state(messages=["적이 행동 중입니다."],
                                   next_actor="enemy",
                                   acting_enemy_idx=idx)

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

    def _build_round_queue(self):
        """
        라운드 시작 — 살아있는 entity를 SPD 내림차순으로 큐 채우기.

        큐 형식: [(actor_type, idx), ...]
          actor_type: "player" 또는 "enemy"
          idx: enemy의 경우 self.enemies 인덱스, player는 -1
        """
        entities = []
        # 플레이어
        if self.player.hp > 0:
            entities.append(("player", -1, self.player.effective_spd()))
        # 적
        for i, e in enumerate(self.enemies):
            if e.hp > 0:
                entities.append(("enemy", i, e.effective_spd()))

        # SPD 내림차순 정렬 (같으면 플레이어 우선, 그 다음 슬롯 번호 빠른 적)
        entities.sort(key=lambda x: (-x[2], 0 if x[0] == "player" else 1, x[1]))

        # 큐에 (actor_type, idx) 형태로 저장
        self.action_queue = [(t, i) for t, i, _ in entities]

    def _cleanup_dead_from_queue(self):
        """죽은 적 큐에서 제거."""
        self.action_queue = [
            (t, i) for t, i in self.action_queue
            if t == "player" or (i < len(self.enemies) and self.enemies[i].hp > 0)
        ]

    def _peek_next_actor(self):
        """
        큐 맨 앞 행동자가 누구인지 반환 (큐 변경 X).
        반환: (next_actor: str, enemy_idx: int)
        """
        # 큐 비면 새 라운드
        if not self.action_queue:
            self._build_round_queue()
            self._cleanup_dead_from_queue()

        if not self.action_queue:
            return ("done", -1)

        actor_type, idx = self.action_queue[0]
        if actor_type == "player":
            return ("player", -1)
        else:
            return ("enemy", idx)

    def _accumulate_atb_all(self):
        """
        모든 살아있는 entity에 자기 SPD 만큼 ATB 누적.
        한 행동이 끝날 때마다 호출. 죽은 적은 누적 안 함.
        """
        # 플레이어
        if self.player.hp > 0:
            self.player_atb += float(self.player.effective_spd())
        # 적
        for i, e in enumerate(self.enemies):
            if e.hp > 0:
                self.enemy_atbs[i] += float(e.effective_spd())


    def _collect_defeated_origins(self):
        # 이미 수집된 인덱스 집합 (한 번만 추가)
        existing_origin_ids = {id(o) for o in self.defeated_origins if o is not None}

        for i, snap in enumerate(self.enemies):
            if snap.hp <= 0:
                # 이 인덱스의 origin
                origin = self._origins[i] if i < len(self._origins) else None
                if origin is None:
                    # origin이 없으면 스냅샷 자체 추가 (App.py가 폴백 처리)
                    # 단, 중복은 막아야 하니 EntitySnapshot으로 id 비교
                    if id(snap) not in existing_origin_ids:
                        self.defeated_origins.append(snap)
                        existing_origin_ids.add(id(snap))
                else:
                    if id(origin) not in existing_origin_ids:
                        self.defeated_origins.append(origin)
                        existing_origin_ids.add(id(origin))

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

        self.logs에는 매 행동마다 추가된 TurnLog가 들어있음:
          - 플레이어: attack, skill, item, escape, *_failed
          - 적: attack, skill, watch, *_failed
        BehaviorAnalyzer가 이 데이터로 행동 패턴 분석.
        """
        winner = self.winner or "unknown"
        return BattleResult(
            winner=winner,
            total_turns=self.turn,
            logs=list(self.logs),
            final_player_hp=self.player.hp,
            final_enemy_hp=self.enemy.hp,
            player_name=self.player.name,
            enemy_name=self.enemy.name,
            final_player_items=list(self.items),
        )

    # ── 내부: 플레이어 행동 처리 ─────────────

    def _player_action(self, action: str, msgs: list) -> str:
        """처리 후 "ok" | "escaped" 반환. 모든 분기에서 TurnLog를 self.logs에 추가.

        action 형식:
          - "attack"          → 현재 타깃 공격 (UI에서 슬롯 클릭으로 선택된 적)
          - "attack:0"        → 슬롯 인덱스 0 적 공격 (다대일)
          - "skill:이름"        → 현재 타깃에게 스킬
          - "skill:이름:0"      → 슬롯 0 적에게 스킬
          - "item:이름"         → 아이템 사용 (대상 무관)
          - "escape"          → 도망
        """
        # 타깃 인덱스 파싱 (있으면 적용)
        # "attack:1" 또는 "skill:파이어볼1:2" 같은 형식 지원.
        target_idx = None
        if action.startswith("attack:"):
            try:
                target_idx = int(action.split(":", 1)[1])
                action = "attack"
            except (ValueError, IndexError):
                pass
        elif action.startswith("skill:"):
            parts = action.split(":")
            # skill:이름 또는 skill:이름:인덱스
            if len(parts) == 3:
                try:
                    target_idx = int(parts[2])
                    action = f"skill:{parts[1]}"
                except ValueError:
                    pass

        # 타깃 인덱스 적용 (살아있고 유효한 경우만)
        if target_idx is not None and 0 <= target_idx < len(self.enemies):
            if self.enemies[target_idx].hp > 0:
                self._target_idx = target_idx

        # 현재 타깃 결정 (자동 폴백 포함)
        target = self._current_target()
        if target is None:
            # 모든 적 사망 (이론상 도달 불가 - step에서 먼저 체크)
            return "ok"

        # ═══════════════════════════════════════════════════════════
        # 기본 공격
        # ═══════════════════════════════════════════════════════════
        if action == "attack":
            dmg, dodge, crit = DamageCalc.physical(
                self.player.effective_stg(), self.player.luc,
                target.effective_arm(),       target.luc,
                skill_mult=1.0,
                role="player",
                attacker=self.player,
                defender=target,
            )
            actual = 0 if dodge else int(dmg)
            if dodge:
                msgs.append(f"{target.name}이(가) 공격을 회피했다!")
            else:
                # ── 물리 원소 반응 (빙결+물리=깨짐 등) ──
                actual = apply_element_and_react(self.player, target, "physical", actual, msgs)
                target.hp -= actual
                dmg = actual
                tag = " (치명타!)" if crit else ""
                msgs.append(f"{self.player.name} → 공격{tag} | {dmg} 데미지")
                msgs.append(f"{target.name} HP: {max(0, int(target.hp))}")

            self.logs.append(TurnLog(
                turn=self.turn,
                actor="player",
                action="attack",
                action_detail="basic_attack",
                damage_dealt=actual,
                hp_after=max(0, target.hp),
                mp_after=self.player.mp,
                is_dodge=dodge,
                is_crit=crit,
            ))
            # 일반 공격은 카운트 안 함 (DB skills_used 대상 X)

        # ═══════════════════════════════════════════════════════════
        # 스킬
        # ═══════════════════════════════════════════════════════════
        elif action.startswith("skill:"):
            skill_name = action[6:]
            meta = SKILL_META.get(skill_name, {})
            is_aoe = bool(meta.get("aoe", False))

            # ── AoE 스킬: 살아있는 모든 적에게 적용 ────────────
            # 슬래시1/2, 난사1/2가 해당. SKILL_META의 "aoe": True 플래그.
            # MP는 한 번만 차감, 두 번째 대상부터는 DamageCalc 직접 호출.
            # 적별로 상성·회피·크리·랜덤계수 모두 독립 판정.
            if is_aoe:
                alive_targets = self._alive_enemies()
                if not alive_targets:
                    return "ok"

                # 1) 첫 대상 — execute_skill로 MP 정상 차감
                first = alive_targets[0]
                dmg, mp_lack, _info = execute_skill(skill_name, self.player, first)
                if self._next_skill_bonus > 1.0 and dmg > 0:
                    dmg = int(dmg * self._next_skill_bonus)
                if mp_lack:
                    msgs.append("MP가 부족합니다!")
                    self.logs.append(TurnLog(
                        turn=self.turn, actor="player",
                        action="skill_failed",
                        action_detail=f"{skill_name}(mp_lack)",
                        damage_dealt=0,
                        hp_after=first.hp,
                        mp_after=self.player.mp,
                    ))
                    return "ok"

                first.hp -= dmg
                msgs.append(f"{skill_name} (전체 공격!) → {first.name}에게 {dmg} 데미지")
                msgs.append(f"{first.name} HP: {max(0, int(first.hp))}")
                total_dmg = dmg

                # 2) 나머지 대상 — DamageCalc 직접 호출 (MP 차감 X)
                stype = meta.get("type", "physical")
                skill_mult = meta.get("mult", 1.0)
                hits = meta.get("hits", 1)

                for tgt in alive_targets[1:]:
                    raw = 0
                    for _ in range(hits):
                        if stype == "physical":
                            r, dodge, _crit = DamageCalc.physical(
                                self.player.effective_stg(),
                                self.player.luc,
                                tgt.effective_arm(),
                                tgt.luc,
                                skill_mult=skill_mult,
                                role="player",
                                attacker=self.player,
                                defender=tgt,
                                hit_count=hits,
                            )
                        elif stype == "magical":
                            r, dodge, _crit = DamageCalc.magical(
                                self.player.sp,
                                self.player.luc,
                                tgt.effective_sparm(),
                                tgt.luc,
                                skill_mult=skill_mult,
                                role="player",
                                attacker=self.player,
                                defender=tgt,
                                hit_count=hits,
                            )
                        else:
                            r, dodge = 0, False
                        if not dodge:
                            raw += int(r)
                    if raw > 0:
                        # AoE 원소 반응
                        elem = meta.get("element", "")
                        raw = apply_element_and_react(self.player, tgt, elem, raw, msgs)
                        tgt.hp -= raw
                        msgs.append(f"  └ {tgt.name}에게 {raw} 데미지")
                        msgs.append(f"     {tgt.name} HP: {max(0, int(tgt.hp))}")
                        total_dmg += raw
                    else:
                        msgs.append(f"  └ {tgt.name}이(가) 회피!")

                self.logs.append(TurnLog(
                    turn=self.turn, actor="player",
                    action="skill",
                    action_detail=f"{skill_name}(aoe)",
                    damage_dealt=int(total_dmg),
                    hp_after=max(0, first.hp),
                    mp_after=self.player.mp,
                ))
                if self._next_skill_bonus > 1.0:
                    msgs.append(f"✨ 집중 효과 적용됨!")
                    self._next_skill_bonus = 1.0
                self.skills_used += 1   # ★ AoE 스킬 사용 성공 (Phase 3)
                return "ok"

            # ── 단일 타깃 스킬 (기존 로직 + buff/heal/shield 메시지 보강) ──
            mp_before = self.player.mp
            dmg, mp_lack, debuff_name = execute_skill(
                skill_name, self.player, target
            )
            if mp_lack:
                msgs.append("MP가 부족합니다!")
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="player",
                    action="skill_failed",
                    action_detail=f"{skill_name}(mp_lack)",
                    damage_dealt=0,
                    hp_after=target.hp,
                    mp_after=self.player.mp,
                ))
            else:
                stype = meta.get("type")
                if stype == "debuff":
                    stat_kor = {"arm":"방어력","sparm":"마법방어력",
                                "stg":"공격력","spd":"스피드"}.get(
                        meta.get("debuff_stat",""), "스탯")
                    msgs.append(f"{skill_name} 사용 → {target.name} {stat_kor} 감소!")
                    self.logs.append(TurnLog(
                        turn=self.turn,
                        actor="player",
                        action="skill",
                        action_detail=skill_name,
                        damage_dealt=0,
                        hp_after=target.hp,
                        mp_after=self.player.mp,
                        debuff_applied=debuff_name or meta.get("debuff_stat", ""),
                    ))
                elif stype in ("buff", "heal", "shield"):
                    if stype == "buff":
                        msgs.append(f"{skill_name} 사용 → 능력치 강화!")
                    elif stype == "heal":
                        msgs.append(f"{skill_name} 사용 → HP {int(self.player.hp)}/{int(self.player.maxhp)}")
                    elif stype == "shield":
                        msgs.append(f"{skill_name} 사용 → 실드 {int(self.player.shield)} 생성!")
                    self.logs.append(TurnLog(
                        turn=self.turn,
                        actor="player",
                        action="skill",
                        action_detail=skill_name,
                        damage_dealt=0,
                        hp_after=self.player.hp,
                        mp_after=self.player.mp,
                    ))
                else:
                    # ── 원소 반응 메시지 파싱 (execute_skill 반환값) ──
                    if debuff_name and "|" in debuff_name:
                        parts = [p for p in debuff_name.split("|") if p]
                        extra_msgs = [p for p in parts[1:] if p]
                        msgs.extend(extra_msgs)
                    # 집중물약 보너스 적용
                    if self._next_skill_bonus > 1.0 and dmg > 0:
                        dmg = int(dmg * self._next_skill_bonus)
                        msgs.append(f"✨ 집중 효과! 데미지 {int((self._next_skill_bonus-1)*100)}% 증가")
                        self._next_skill_bonus = 1.0
                    target.hp -= dmg
                    msgs.append(f"{skill_name} 사용 → {dmg} 데미지")
                    msgs.append(f"{target.name} HP: {max(0, int(target.hp))}")
                    self.logs.append(TurnLog(
                        turn=self.turn,
                        actor="player",
                        action="skill",
                        action_detail=skill_name,
                        damage_dealt=int(dmg),
                        hp_after=max(0, target.hp),
                        mp_after=self.player.mp,
                    ))

                # ★ 단일 스킬 사용 성공 (Phase 3) — else 블록 맨 끝
                # debuff / buff / heal / shield / 일반 데미지 모두 카운트
                self.skills_used += 1

        # ═══════════════════════════════════════════════════════════
        # 아이템
        # ═══════════════════════════════════════════════════════════
        elif action.startswith("item:"):
            # "item:이름" 또는 "item:이름:타깃idx" 형식 모두 지원
            _parts = action.split(":")
            item_name = _parts[1]
            target_idx = int(_parts[2]) if len(_parts) > 2 and _parts[2].isdigit() else 0

            if item_name not in self.items:
                msgs.append("해당 아이템이 없습니다.")
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="player",
                    action="item_failed",
                    action_detail=f"{item_name}(not_in_inventory)",
                ))
            else:
                meta = ITEM_META.get(item_name, {})
                category = meta.get("category", "")

                # ── 포션 (HP/MP 회복) ──
                if meta.get("stat") == "hp":
                    before = int(self.player.hp)
                    amount = meta["amount"](self.player)
                    self.player.hp = min(self.player.maxhp, self.player.hp + amount)
                    msgs.append(f"{item_name} 사용 → HP {before} → {int(self.player.hp)} (+{amount})")
                elif meta.get("stat") == "mp":
                    before = int(self.player.mp)
                    amount = meta["amount"](self.player)
                    self.player.mp = min(self.player.maxmp, self.player.mp + amount)
                    msgs.append(f"{item_name} 사용 → MP {before} → {int(self.player.mp)} (+{amount})")

                # ── AoE 데미지 (폭탄/거미줄폭탄) ──
                elif category == "aoe_damage":
                    ratio = meta.get("damage_ratio", 0.2)
                    alive = self._alive_enemies()
                    msgs.append(f"💣 {item_name} 사용!")
                    for tgt in alive:
                        dmg = max(1, int(tgt.maxhp * ratio))
                        tgt.hp = max(0, tgt.hp - dmg)
                        msgs.append(f"  └ {tgt.name}에게 {dmg} 피해")
                        # 속도 디버프 (거미줄 폭탄)
                        if meta.get("debuff_stat"):
                            tgt.apply_debuff(Debuff(
                                stat=meta["debuff_stat"],
                                amount=meta["debuff_amount"],
                                turns=meta["debuff_turns"],
                                name=item_name,
                            ))
                    if meta.get("debuff_stat"):
                        msgs.append(f"  적 전체 속도 {int(meta['debuff_amount']*100)}% 감소 ({meta['debuff_turns']}T)")

                # ── 원소 부착 (화염병/냉기병/전격수정) ──
                elif category == "element":
                    alive = self._alive_enemies()
                    if not alive:
                        msgs.append("대상이 없습니다.")
                    else:
                        idx = target_idx if target_idx < len(alive) else 0
                        tgt = alive[idx]
                        elem = meta.get("element", "")
                        ratio = meta.get("damage_ratio", 0.1)
                        dmg = max(1, int(tgt.maxhp * ratio))
                        msgs.append(f"🧪 {item_name} → {tgt.name}")
                        # 직접 피해 + 원소 반응/부착
                        dmg = apply_element_and_react(self.player, tgt, elem, dmg, msgs)
                        tgt.hp = max(0, tgt.hp - dmg)
                        msgs.append(f"  └ {tgt.name}에게 {dmg} 피해")

                # ── 버프 (집중물약/신속물약) ──
                elif category == "buff":
                    btype = meta.get("buff_type", "")
                    if btype == "next_skill_bonus":
                        self._next_skill_bonus = meta.get("bonus_mult", 1.5)
                        msgs.append(f"✨ {item_name} 사용 — 다음 스킬 {int((meta.get('bonus_mult',1.5)-1)*100)}% 추가 피해!")
                    elif btype == "atb_gain":
                        self._pending_atb_bonus = meta.get("atb_bonus", 50)
                        msgs.append(f"💨 {item_name} 사용 — 다음 행동 후 ATB +{meta.get('atb_bonus',50)}!")

                self.items.remove(item_name)
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="player",
                    action="item",
                    action_detail=item_name,
                    hp_after=self.player.hp,
                    mp_after=self.player.mp,
                ))
                self.items_used += 1

        # ═══════════════════════════════════════════════════════════
        # 도망
        # ═══════════════════════════════════════════════════════════
        elif action == "escape":
            if self.is_boss:
                msgs.append("...도망칠 수 없다!")
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="player",
                    action="escape_blocked",
                    action_detail="boss_battle",
                    escaped=False,
                ))
                return "ok"
            p_spd = self.player.effective_spd()
            # 다대일 도망: 살아있는 모든 적의 평균 SPD 기준 (한 명만 빠르면 곤란하니까 평균)
            alive = self._alive_enemies()
            if alive:
                e_spd = sum(e.effective_spd() for e in alive) / len(alive)
            else:
                e_spd = 1.0
            ratio = p_spd / max(e_spd, 1.0)
            if   ratio >= 2.0: chance = 0.95
            elif ratio >= 1.5: chance = 0.80
            elif ratio >= 1.0: chance = 0.60
            elif ratio >= 0.7: chance = 0.35
            else:              chance = 0.15
            success = _random() <= chance
            self.logs.append(TurnLog(
                turn=self.turn,
                actor="player",
                action="escape",
                action_detail=f"chance={chance:.2f}",
                escaped=success,
            ))
            if success:
                return "escaped"
            else:
                msgs.append(f"도망에 실패했다! (성공률 {int(chance*100)}%)")

        else:
            msgs.append("알 수 없는 행동입니다.")

        return "ok"
    
    # ── 내부: 적 행동 처리 ───────────────────

    def _enemy_action(self, msgs: list):
        """
        다대일: 살아있는 모든 적이 SPD 내림차순으로 한 번씩 행동.
        각 적이 행동할 때마다 플레이어 사망 체크 — 죽으면 즉시 종료.
        """
        # SPD 내림차순 정렬 (빠른 적 먼저)
        alive = sorted(
            self._alive_enemies(),
            key=lambda e: e.effective_spd(),
            reverse=True
        )
        for e in alive:
            if self.player.hp <= 0:
                break  # 플레이어 사망 시 남은 적 행동 스킵
            self._single_enemy_action(e, msgs)

    def _single_enemy_action(self, enemy, msgs: list):
        """단일 적의 1회 행동 처리. 기존 _enemy_action 로직을 적 1마리 단위로 분리."""
        # ── 사제 전용 행동 (다른 아군 회복/버프) ──
        # enemy_type이 "사제"면 별도 로직 사용. 일반 EnemyAI 안 거침.
        # ⚠ return 제거 — 메서드 끝의 tick 처리(buff/debuff 1턴 감소)를
        #    사제도 동일하게 거쳐야 함 (Codex 지적 반영).
        if getattr(enemy, "enemy_type", "") == "사제":
            self._priest_action(enemy, msgs)
        else:
            # ── 일반 몬스터 행동 (기존 로직) ──
            action = self._enemy_ai(enemy, self.player)

            if action.action_type == "attack":
                dmg, dodge, crit = DamageCalc.physical(
                    enemy.effective_stg(), enemy.luc,
                    self.player.effective_arm(), self.player.luc,
                    skill_mult=1.0,
                    role="monster",
                    attacker=enemy,
                    defender=self.player,
                )
                actual = 0 if dodge else int(dmg)
                if dodge:
                    msgs.append(f"{self.player.name}이(가) {enemy.name}의 공격을 회피했다!")
                else:
                    # ── 물리 원소 반응 (적 기본공격) ──
                    atk_elem = getattr(enemy, "attack_element", "")
                    actual = apply_element_and_react(enemy, self.player, atk_elem or "physical", actual, msgs)
                    self.player.hp -= actual
                    dmg = actual
                    tag = " (치명타!)" if crit else ""
                    msgs.append(f"{enemy.name} → 공격{tag} | {dmg} 데미지")
                    msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

                    # ── 탱커 패시브: 물리 피격 시 MP 회복 ──
                    tanker_msg = self.player.passive_on_hit_received("physical")
                    if tanker_msg:
                        msgs.append(tanker_msg)
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="enemy",
                    action="attack",
                    action_detail="basic_attack",
                    damage_dealt=actual,
                    hp_after=max(0, self.player.hp),
                    mp_after=enemy.mp,
                    is_dodge=dodge,
                    is_crit=crit,
                ))

            elif action.action_type == "skill":
                dmg, mp_lack, debuff_name = execute_skill(
                    action.detail, enemy, self.player
                )
                if mp_lack:
                    self.logs.append(TurnLog(
                        turn=self.turn,
                        actor="enemy",
                        action="skill_failed",
                        action_detail=f"{action.detail}(mp_lack)",
                        damage_dealt=0,
                        hp_after=self.player.hp,
                        mp_after=enemy.mp,
                    ))
                else:
                    if dmg > 0:
                        self.player.hp -= dmg
                        msgs.append(f"{enemy.name} → {action.detail} | {dmg} 데미지")
                        msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

                        # ── 탱커 패시브: 스킬 피격 시 회복 (스킬 타입 따라) ──
                        skill_meta = SKILL_META.get(action.detail, {})
                        skill_type = skill_meta.get("type", "physical")
                        tanker_msg = self.player.passive_on_hit_received(skill_type)
                        if tanker_msg:
                            msgs.append(tanker_msg)
                    elif debuff_name:
                        msgs.append(f"{enemy.name} → {action.detail} 사용!")

                    self.logs.append(TurnLog(
                        turn=self.turn,
                        actor="enemy",
                        action="skill",
                        action_detail=action.detail,
                        damage_dealt=int(dmg) if dmg > 0 else 0,
                        hp_after=max(0, self.player.hp),
                        mp_after=enemy.mp,
                        debuff_applied=debuff_name or "",
                    ))

            elif action.action_type == "watch":
                msgs.append(f"{enemy.name}이(가) 기회를 엿보고 있다...")
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="enemy",
                    action="watch",
                    action_detail="watching",
                    hp_after=self.player.hp,
                    mp_after=enemy.mp,
                ))

        # ── 이 적의 행동 1회 처리 후 turn 감소 ──
        # · 적 본인의 버프/디버프 1턴 소진
        # · 플레이어 디버프도 적 행동 단위로 1턴 소진
        #   (다대일이면 적 N마리가 행동 → 디버프가 N번 빨리 풀림 — 의도된 동작)
        # ⚠ 이 블록은 사제/일반 모든 경로에서 반드시 실행됨 (위 if/else 밖에 있음).
        enemy.tick_buffs()
        enemy.tick_debuffs()
        self.player.tick_debuffs()


    # ─────────────────────────────────────────────
    # 사제 전용 행동 (서포터형)
    # ─────────────────────────────────────────────
    def _priest_action(self, priest, msgs: list):
        """
        사제 행동 우선순위:
          1) 다른 아군 중 HP ≤ 70%면 → 사제힐 (가장 비율 낮은 아군)
          2) 30% 확률로 사제축복 (가장 STG 높은 아군 STG 버프)
          3) 그 외 → 홀리볼트 (마법 공격)
          4) MP 부족 → 기본 물리 공격
        """
        # 자기 제외 살아있는 아군
        allies = [e for e in self.enemies if e is not priest and e.hp > 0]

        # ── 1) 사제힐 우선 ──
        if priest.mp >= 14 and allies:
            wounded = [a for a in allies if a.hp / max(a.maxhp, 1) <= 0.70]
            if wounded:
                target_ally = min(wounded, key=lambda a: a.hp / max(a.maxhp, 1))
                meta = SKILL_META["사제힐"]
                priest.mp -= meta["mp"]
                heal = meta["base_heal"] + priest.sp * meta["sp_mult"]
                heal = min(heal, target_ally.maxhp * meta["cap"])
                before = int(target_ally.hp)
                target_ally.hp = min(target_ally.maxhp, target_ally.hp + int(heal))
                gained = int(target_ally.hp) - before
                msgs.append(f"{priest.name} → 사제힐! {target_ally.name} HP +{gained}")
                self.logs.append(TurnLog(
                    turn=self.turn, actor="enemy",
                    action="skill", action_detail="사제힐",
                    damage_dealt=-gained,
                    hp_after=target_ally.hp,
                    mp_after=priest.mp,
                ))
                return

        # ── 2) 사제축복 (30% 확률) ──
        if priest.mp >= 12 and allies and _random() < 0.30:
            target_ally = max(allies, key=lambda a: a.effective_stg())
            meta = SKILL_META["사제축복"]
            priest.mp -= meta["mp"]
            target_ally.apply_buff(Buff(
                stat=meta["buff_stat"],
                amount=meta["buff_amount"],
                turns=meta["buff_turns"],
                name="사제축복",
            ))
            msgs.append(f"{priest.name} → 사제축복! {target_ally.name}의 공격력 강화!")
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy",
                action="skill", action_detail="사제축복",
                damage_dealt=0,
                hp_after=target_ally.hp,
                mp_after=priest.mp,
            ))
            return

        # ── 3) 홀리볼트 (마법 공격) ──
        if priest.mp >= 8:
            meta = SKILL_META["홀리볼트"]
            priest.mp -= meta["mp"]
            dmg, dodge, crit = DamageCalc.magical(
                priest.sp, priest.luc,
                self.player.effective_sparm(), self.player.luc,
                skill_mult=meta["mult"],
                role="monster",
                attacker=priest,
                defender=self.player,
            )
            if dodge:
                msgs.append(f"{self.player.name}이(가) {priest.name}의 홀리볼트를 회피!")
                self.logs.append(TurnLog(
                    turn=self.turn, actor="enemy",
                    action="skill", action_detail="홀리볼트",
                    damage_dealt=0,
                    hp_after=self.player.hp,
                    mp_after=priest.mp,
                    is_dodge=True,
                ))
                return

            actual = int(dmg)
            if self.player.shield > 0:
                absorbed = min(self.player.shield, actual)
                self.player.shield -= absorbed
                actual -= absorbed
                msgs.append(f"실드가 {absorbed} 흡수!")
            self.player.hp -= actual
            self.player.last_damage_taken = actual
            tag = " (치명타!)" if crit else ""
            msgs.append(f"{priest.name} → 홀리볼트{tag} | {actual} 데미지")
            msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

            # 탱커 패시브: 마법 피격 시 HP 회복
            tanker_msg = self.player.passive_on_hit_received("magical")
            if tanker_msg:
                msgs.append(tanker_msg)

            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy",
                action="skill", action_detail="홀리볼트",
                damage_dealt=actual,
                hp_after=max(0, self.player.hp),
                mp_after=priest.mp,
                is_crit=crit,
            ))
            return

        # ── 4) MP 부족 → 기본 물리 공격 ──
        dmg, dodge, crit = DamageCalc.physical(
            priest.effective_stg(), priest.luc,
            self.player.effective_arm(), self.player.luc,
            skill_mult=1.0,
            role="monster",
            attacker=priest,
            defender=self.player,
        )
        if dodge:
            msgs.append(f"{self.player.name}이(가) {priest.name}의 공격을 회피!")
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy",
                action="attack", action_detail="basic_attack",
                damage_dealt=0,
                hp_after=self.player.hp,
                mp_after=priest.mp,
                is_dodge=True,
            ))
            return

        actual = int(dmg)
        if self.player.shield > 0:
            absorbed = min(self.player.shield, actual)
            self.player.shield -= absorbed
            actual -= absorbed
            msgs.append(f"실드가 {absorbed} 흡수!")
        self.player.hp -= actual
        self.player.last_damage_taken = actual
        tag = " (치명타!)" if crit else ""
        msgs.append(f"{priest.name} → 공격{tag} | {actual} 데미지")
        msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

        # 탱커 패시브: 물리 피격 시 MP 회복
        tanker_msg = self.player.passive_on_hit_received("physical")
        if tanker_msg:
            msgs.append(tanker_msg)

        self.logs.append(TurnLog(
            turn=self.turn, actor="enemy",
            action="attack", action_detail="basic_attack",
            damage_dealt=actual,
            hp_after=max(0, self.player.hp),
            mp_after=priest.mp,
            is_crit=crit,
        ))
    # ── 내부: 현재 상태 dict 반환 ────────────

    _DIFF_LABEL = {
        "hard":   "강함",
        "normal": "중간",
        "easy":   "약함",
        "":       "",
    }

    def _pack_status_list(self, entity) -> dict:
        """
        엔티티의 buffs / debuffs / 원소 상태 를 JSON 직렬화 가능 dict로.
        """
        return {
            "buffs": [
                {"stat": b.stat, "amount": round(b.amount, 3),
                 "turns": b.turns, "name": b.name}
                for b in getattr(entity, "buffs", [])
            ],
            "debuffs": [
                {"stat": d.stat, "amount": round(d.amount, 3),
                 "turns": d.turns, "name": d.name}
                for d in getattr(entity, "debuffs", [])
            ],
            "element_aura": _current_element(entity),
            "element_queue": list(getattr(entity, "element_queue", [])),
            "status_effects": [
                {"type": s.effect_type, "name": s.name, "turns": s.turns}
                for s in getattr(entity, "status_effects", [])
            ],
        }

    def _state(self, messages: list = None,
               next_actor: str = "player",
               acting_enemy_idx: int = -1) -> dict:
        # 첫 번째 살아있는 적 또는 마지막 적 (호환성 — 1대1 UI는 enemy_* 필드 사용)
        e = self.enemy
        diff_raw = getattr(e, "difficulty", "")

        # 플레이어 / 적 상태이상
        p_status = self._pack_status_list(self.player)
        e_status = self._pack_status_list(e)
        # 원소 상태 (UI 연동)
        player_element_aura   = p_status.get("element_aura", "")
        player_status_effects = p_status.get("status_effects", [])
        enemy_element_aura    = e_status.get("element_aura", "")
        enemy_status_effects  = e_status.get("status_effects", [])

        # 모든 적의 정보 — 다대일용 (UI는 이 배열을 받아서 슬롯 3·4·5에 매핑)
        # 각 적도 본인의 effective_* + buffs/debuffs 포함
        enemies_payload = []
        for i, en in enumerate(self.enemies):
            en_diff = getattr(en, "difficulty", "")
            en_status = self._pack_status_list(en)
            enemies_payload.append({
                "slot_index":       i,                        # UI 슬롯 매핑 (0=슬롯3, 1=슬롯4, 2=슬롯5)
                "atb":              round(self.enemy_atbs[i], 1), # 턴 순서 결정용 ATB (실효값)
                "name":             en.name,
                "lv":               en.lv,
                "alive":            en.hp > 0,
                "hp":               max(0.0, round(en.hp, 1)),
                "maxhp":            round(en.maxhp, 1),
                "mp":               round(en.mp, 1),
                "maxmp":            round(en.maxmp, 1),
                # 원본 스탯 (참고용)
                "stg":              round(en.stg, 1),
                "arm":              round(en.arm, 1),
                "sparm":            round(en.sparm, 1),
                "sp":               round(en.sp, 1),
                "spd":              round(en.spd, 1),
                "luc":              round(en.luc, 1),
                # ── 실효 스탯 (버프/디버프 반영) ──
                "effective_stg":    round(en.effective_stg(), 1),
                "effective_arm":    round(en.effective_arm(), 1),
                "effective_sparm":  round(en.effective_sparm(), 1),
                "effective_spd":    round(en.effective_spd(), 1),
                # ── 상태이상 ──
                "buffs":            en_status["buffs"],
                "debuffs":          en_status["debuffs"],
                "element_aura":     en_status["element_aura"],
                "status_effects":   en_status["status_effects"],
                "difficulty":       en_diff,
                "difficulty_label": self._DIFF_LABEL.get(en_diff, en_diff),
            })

        return {
            "turn":       self.turn,
            "is_boss":    self.is_boss,   # UI: 보스전이면 도망 버튼 숨김
            "player_hp":  round(self.player.hp, 1),
            "player_mp":  round(self.player.mp, 1),
            "player_maxhp": self.player.maxhp,
            "player_maxmp": self.player.maxmp,
            "player_atb": round(self.player_atb, 1),
            # ── 플레이어 실효 스탯 (UI 좌측 패널이 전투 중에 이걸로 갱신) ──
            "player_effective_stg":   round(self.player.effective_stg(), 1),
            "player_effective_arm":   round(self.player.effective_arm(), 1),
            "player_effective_sparm": round(self.player.effective_sparm(), 1),
            "player_effective_spd":   round(self.player.effective_spd(), 1),
            # ── 플레이어 상태이상 ──
            "player_buffs":   p_status["buffs"],
            "player_debuffs": p_status["debuffs"],
            "player_element_aura":   player_element_aura,
            "player_status_effects": player_status_effects,
            "enemy_element_aura":    enemy_element_aura,
            "enemy_status_effects":  enemy_status_effects,
            # ── 1대1 호환 (단수) — 기존 UI는 이 필드들 사용 ──
            "enemy_hp":   max(0.0, round(e.hp, 1)),
            "enemy_maxhp": e.maxhp,
            "enemy_name": e.name,
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
            # ── 적 (단수) 실효 스탯 + 상태이상 ──
            "enemy_effective_stg":   round(e.effective_stg(), 1),
            "enemy_effective_arm":   round(e.effective_arm(), 1),
            "enemy_effective_sparm": round(e.effective_sparm(), 1),
            "enemy_effective_spd":   round(e.effective_spd(), 1),
            "enemy_buffs":           e_status["buffs"],
            "enemy_debuffs":         e_status["debuffs"],
            # ── 다대일 (배열) — UI는 enemies.length > 1 이면 다대일 모드로 전환 ──
            "enemies":          enemies_payload,
            "enemy_count":      len(self.enemies),
            "target_idx":       self._target_idx,  # 현재 선택된 타깃 슬롯
            # ── 공통 ──
            "items":      self.get_items(),
            "skills":     self.get_skills(),
            "done":       self.done,
            "winner":     self.winner,
            "messages":   messages or [],
            # ★ A1 응답 분리 — 다음 행동자 정보
            "next_actor":         next_actor,
            "acting_enemy_idx":   acting_enemy_idx,
        }