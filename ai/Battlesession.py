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
    SKILL_META, BattleEngine, Action, BattleResult, TurnLog
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
        enemy:  EntitySnapshot = None,
        items:  list = None,
        is_boss: bool = False,
        enemies: list = None,  # ★ 다대일 전투용: enemy 대신 enemies (리스트) 전달 가능
    ):
        """
        BattleSession — 1대1 또는 1대N 전투 세션.

        호환성:
          - 기존 코드는 enemy=... 단수로 호출 (1대1 전투).
          - 다대일은 enemies=[e1, e2, e3] 리스트로 호출 (Phase 2).
          - 내부에서는 항상 self.enemies 리스트로 관리.
          - self.enemy는 첫 번째 살아있는 적을 가리키는 동적 프로퍼티 (구 코드 호환).
        """
        self.player  = copy.deepcopy(player)

        # ── enemies 리스트로 통일 ──
        # 단수 enemy로 호출되면 자동으로 [enemy]로 변환.
        if enemies is not None:
            self.enemies = [copy.deepcopy(e) for e in enemies]
        elif enemy is not None:
            self.enemies = [copy.deepcopy(enemy)]
        else:
            raise ValueError("BattleSession은 enemy 또는 enemies 중 하나를 받아야 합니다")

        # 각 적에게 인덱스 부여 (UI 슬롯 매핑용: 0=슬롯3, 1=슬롯4, 2=슬롯5)
        for i, e in enumerate(self.enemies):
            e._slot_index = i

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
        # 기본값: 첫 번째 살아있는 적
        self._target_idx = 0

        # 전사 패시브용 행동 카운터 — 공격 3회마다 발동
        # self.turn은 다른 곳에서도 쓰여서 별도로 관리.
        # 플레이어가 실제로 행동한 횟수 (item, escape도 포함 — step과 1:1).
        self._warrior_action_count = 0
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

        # ── 전사 패시브: 공격 3회마다 maxhp 10% 회복 ──
        # 시뮬(BattleEngine.run)과 동일 룰 — Digital Twin 원칙.
        # 발동 시점: 행동 카운터 증가 직후 (이번 행동 전에 회복).
        # 빈도 변경 이력: 2턴 → 3턴 (시뮬 결과 +76.5%p 과강 → 적정화)
        if self.player.job == "전사" and self.player.hp > 0:
            self._warrior_action_count += 1
            if self._warrior_action_count % 3 == 0:
                warrior_msg = self.player.passive_on_turn_start()
                if warrior_msg:
                    msgs.append(warrior_msg)

        # ── 첫 턴 + first_strike 처리 (암살자) ──
        # 적이 first_strike=True 이면 플레이어 행동 전에 적이 먼저 공격.
        # SPD 무관하게 강제 선공. 이후 턴부터는 정상 흐름.
        if self.turn == 1 and getattr(self.enemy, "first_strike", False):
            msgs.append(f"{self.enemy.name}이(가) 먼저 기습한다!")
            self._enemy_action(msgs)
            # 플레이어 사망 체크 (선공으로 한방 가능)
            if self.player.hp <= 0:
                self.done   = True
                self.winner = "enemy"
                msgs.append(f"{self.player.name}이(가) 쓰러졌다...")
                return self._state(messages=msgs)

        # ── 플레이어 행동 ──────────────────────
        # 행동 전 기존 버프 ID 집합 스냅샷.
        # _player_action 안에서 새로 적용되는 버프는 이 스냅샷에 없으므로
        # 아래 tick 시 제외 — 사용 즉시 1턴 차감되는 문제 방지.
        pre_action_buff_ids = {id(b) for b in self.player.buffs}

        p_result = self._player_action(action, msgs)

        # ── 플레이어 본인 버프 turn -1 (행동 전에 있던 것만) ──
        # 새로 적용된 버프(이번 _player_action에서 생성)는 tick에서 제외.
        # 같은 stat의 기존 버프를 덮어쓴 경우엔 id가 새 객체 → 자연스럽게 제외됨.
        #
        # 이번 행동에서 새로 추가/갱신된 버프를 임시로 빼두고, 기존 버프만 tick.
        new_buffs = [b for b in self.player.buffs if id(b) not in pre_action_buff_ids]
        old_buffs = [b for b in self.player.buffs if id(b) in pre_action_buff_ids]
        self.player.buffs = old_buffs
        self.player.tick_buffs()
        # 새 버프 다시 합치기 (turn 그대로 유지)
        self.player.buffs.extend(new_buffs)

        if p_result == "escaped":
            self.done   = True
            self.winner = "escaped"
            msgs.append("도망에 성공했다!")
            return self._state(messages=msgs)

        # ── 모든 적 사망 체크 (다대일) ──
        # 한 마리 죽어도 다른 적이 살아있으면 전투 계속.
        # 살아있는 적이 한 명도 없을 때만 승리.
        if not self._alive_enemies():
            self.done   = True
            self.winner = "player"
            if len(self.enemies) > 1:
                msgs.append(f"모든 적을 처치했다!")
            else:
                msgs.append(f"{self.enemies[0].name}을(를) 처치했다!")
            return self._state(messages=msgs)

        # ── 적 행동 ───────────────────────────
        # 다대일: 모든 살아있는 적이 SPD 내림차순으로 한 번씩 행동.
        # 콘솔 전투(Act.action)와 동일하게 아이템 사용 후에도 적 턴 진행.
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

        # 기본 공격
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
                target.hp -= dmg
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

            """
            ═══════════════════════════════════════════════════════════════════
            ai/Battlesession.py  핵심 패치 ★
            ═══════════════════════════════════════════════════════════════════

            ✅ 작업 내용:
            [수정 1] _player_action() 안의 스킬 분기 → AoE 처리 추가
            [수정 2] _single_enemy_action() 시작부에 사제 분기 추가
            [추가 3] _priest_action() 메서드 신규 추가
            """
            # ═══════════════════════════════════════════════════════════════════
            # [수정 1]  _player_action() 의 스킬 분기 통째로 교체
            # ═══════════════════════════════════════════════════════════════════
            #
            #   _player_action 메서드 안에서 elif action.startswith("skill:"):
            #   로 시작하는 블록 전체를 아래 코드로 교체.
            #   (그 위의 if action == "attack": 블록은 그대로 유지,
            #    그 아래의 elif action.startswith("item:"): 블록도 그대로 유지)

        # 스킬
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

        # 아이템
        elif action.startswith("item:"):
            item_name = action[5:]
            if item_name not in self.items:
                msgs.append("해당 아이템이 없습니다.")
                # 실패한 아이템도 기록 (행동 의도 분석용)
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="player",
                    action="item_failed",
                    action_detail=f"{item_name}(not_in_inventory)",
                ))
            else:
                from Battle_Engine import ITEM_META
                meta = ITEM_META.get(item_name, {})
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
                self.items.remove(item_name)
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="player",
                    action="item",
                    action_detail=item_name,
                    hp_after=self.enemy.hp,  # 적 HP는 변화 없음
                    mp_after=self.player.mp,
                ))

        # 도망
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
                    self.player.hp -= dmg
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
            from Battle_Engine import Buff
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
        엔티티의 buffs / debuffs 를 JSON 직렬화 가능 dict 리스트로.
        UI는 stat / amount / turns / name 4필드를 사용.
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
        }

    def _state(self, messages: list = None) -> dict:
        # 첫 번째 살아있는 적 또는 마지막 적 (호환성 — 1대1 UI는 enemy_* 필드 사용)
        e = self.enemy
        diff_raw = getattr(e, "difficulty", "")

        # 플레이어 / 적 상태이상
        p_status = self._pack_status_list(self.player)
        e_status = self._pack_status_list(e)

        # 모든 적의 정보 — 다대일용 (UI는 이 배열을 받아서 슬롯 3·4·5에 매핑)
        # 각 적도 본인의 effective_* + buffs/debuffs 포함
        enemies_payload = []
        for i, en in enumerate(self.enemies):
            en_diff = getattr(en, "difficulty", "")
            en_status = self._pack_status_list(en)
            enemies_payload.append({
                "slot_index":       i,                        # UI 슬롯 매핑 (0=슬롯3, 1=슬롯4, 2=슬롯5)
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
            # ── 플레이어 실효 스탯 (UI 좌측 패널이 전투 중에 이걸로 갱신) ──
            "player_effective_stg":   round(self.player.effective_stg(), 1),
            "player_effective_arm":   round(self.player.effective_arm(), 1),
            "player_effective_sparm": round(self.player.effective_sparm(), 1),
            "player_effective_spd":   round(self.player.effective_spd(), 1),
            # ── 플레이어 상태이상 ──
            "player_buffs":   p_status["buffs"],
            "player_debuffs": p_status["debuffs"],
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
        }