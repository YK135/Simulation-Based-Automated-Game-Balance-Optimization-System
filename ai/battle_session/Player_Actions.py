"""
battle_session/player_actions.py — 플레이어 행동
"""
from __future__ import annotations
import copy
from random import randint, random as _random

from ai.battle import (
    apply_element_and_react, check_element_reaction, try_apply_element_aura_and_status,
    ITEM_META, Debuff, Buff, _current_element,
    EntitySnapshot, DamageCalc, execute_skill,
    SKILL_META, BattleEngine, Action, BattleResult, TurnLog,
    execute_single_hit, consume_skill_mp,
)


class PlayerActionsMixin:
    """BattleSession에 플레이어 행동 기능을 제공하는 mixin."""

    # ═══════════════════════════════════════════════════════
    # 직업 패시브 helper (도적 주사위 / 전사 공격 카운트)
    # ═══════════════════════════════════════════════════════

    # 주사위 배율 테이블 (6은 배율 1.0 + 크리 확정 1.5x)
    _ROGUE_DICE_MULT = {1: 0.75, 2: 0.90, 3: 1.00, 4: 1.15, 5: 1.25, 6: 1.00}

    def _roll_rogue_dice(self, msgs: list):
        """
        도적 주사위 패시브 — 공격/공격형 스킬 입력 시 굴림 (이모션 전).
        반환: dict {mult, force_crit, bleed} 또는 None(도적 아님).
        굴리는 동안 자연 크리 억제(_suppress_crit) — 도적 크리는 주사위 6으로만.
        """
        if getattr(self.player, "job", "") != "도적":
            return None
        dice = randint(1, 6)
        self.player._suppress_crit = True
        info = {
            "dice":       dice,
            "mult":       self._ROGUE_DICE_MULT[dice],
            "force_crit": dice == 6,
            "bleed":      dice in (3, 6),
        }
        msgs.append(f"🎲 주사위: {dice}!")
        return info

    def _apply_rogue_dice(self, dmg: int, dice_info, target, msgs: list) -> int:
        """
        주사위 결과를 최종 데미지에 적용.
        - 배율 곱 (0.75~1.25)
        - 6: 크리티컬 확정(1.5x) + ATB 20 추가
        - 3/6: 대상에게 출혈 (3턴, 매턴 maxhp 4~7%)
        회피 등으로 dmg<=0이면 배율/출혈 미적용 (맞지 않았으므로).
        """
        if not dice_info or dmg <= 0:
            return dmg
        dmg = int(round(dmg * dice_info["mult"]))
        if dice_info["force_crit"]:
            dmg = int(dmg * 1.5)
            msgs.append("💥 주사위 6 — 치명타 확정!")
            # 크리 발생 시 ATB 추가 20
            self.player_atb += 20.0
            msgs.append("⚡ ATB +20!")
        if dice_info["bleed"] and target is not None and hasattr(target, "apply_status_effect"):
            from ai.battle.Entity import StatusEffect
            target.apply_status_effect(StatusEffect(
                effect_type="bleed", turns=3, name="출혈"))
            msgs.append(f"🩸 {target.name}에게 출혈! (3턴, 매턴 최대체력 4~7%)")
        return dmg

    def _end_rogue_dice(self):
        """주사위 공격 종료 — 자연 크리 억제 해제 (반격은 일반 크리 허용)."""
        if getattr(self.player, "job", "") == "도적":
            self.player._suppress_crit = False

    _ATTACK_SKILL_TYPES = ("physical", "magical", "tank_attack", "counter", "multi_hit")

    # ─────────────────────────────────────────
    # 공통: 실드 경유 피해 적용 (Player/Enemy_Actions 공용 — mixin이라 self 공유)
    #   실드 정의: HP 대신 먼저 피해를 받는 추가 체력.
    #   예) shield 50, dmg 40 → shield 10, hp 그대로
    #       shield 20, dmg 30 → shield 0,  hp -10
    #   반환: HP에 실제로 들어간 피해 (BattleEngine과 동일 기준 — 로그/메시지용)
    # ─────────────────────────────────────────
    def _apply_dmg_shielded(self, target, dmg, msgs):
        from ai.battle import _apply_damage_with_shield
        before_shield = getattr(target, "shield", 0.0)
        hp_damage = _apply_damage_with_shield(target, int(dmg))
        absorbed = max(0.0, before_shield - getattr(target, "shield", 0.0))
        if absorbed > 0:
            msgs.append(f"🛡 실드가 {int(absorbed)} 피해를 흡수!")
            if getattr(target, "shield", 0.0) <= 0:
                msgs.append("🛡 실드가 깨졌다!")
        return hp_damage

    def _exec_multi_hit_skill(self, skill_name: str, meta: dict, target, msgs: list,
                              dice_info) -> str:
        """
        연속공격류(hits>1, physical/magical) — 타격 횟수만큼 개별 공격 판정.
          · MP는 스킬당 1회만 소모
          · 각 타격: 대상 확인(사망 시 살아있는 적 중 랜덤 재타겟) → 회피/크리 →
                    원소 부착/반응 → 실드 흡수 → HP 적용 → 사망 확인 → 로그
          · 도적 주사위: 스킬 전체 1회 굴림, 배율/강제크리는 각 타에, 출혈은 1회
          · 전사 공격 카운트: 시도된 타격 수만큼 (+살아있는 적 없어 중단된 타는 제외)
          · multi_shield(다대일 보정): 스킬 1회당 1번만
          · skills_used +1 (타격 수 아님)
        """
        from random import choice as _choice

        if consume_skill_mp(skill_name, self.player):
            self._end_rogue_dice()
            msgs.append("MP가 부족합니다!")
            self.logs.append(TurnLog(
                turn=self.turn, actor="player", action="skill_failed",
                action_detail=f"{skill_name}(mp_lack)",
                damage_dealt=0, hp_after=target.hp, mp_after=self.player.mp,
            ))
            return "ok"

        hits = meta.get("hits", 1)
        msgs.append(f"{skill_name}!")

        total_hp_dmg = 0
        total_shield_dmg = 0
        attempted = 0
        retargeted = False
        bleed_done = False
        hits_detail = []
        cur = target

        for hi in range(1, hits + 1):
            # ── 대상 확인: 죽었으면 살아있는 적 중 랜덤 재타겟 ──
            if cur is None or cur.hp <= 0:
                alive = self._alive_enemies()
                if not alive:
                    break                      # 남은 타격 중단 (카운트 제외)
                cur = _choice(alive)
                retargeted = True

            attempted += 1
            raw, dodge, crit = execute_single_hit(skill_name, self.player, cur)

            if dodge:
                msgs.append(f"{hi}타: {cur.name}이(가) 회피했다!")
                hits_detail.append({"hit": hi, "target_name": cur.name,
                                    "dodge": True, "crit": False, "damage": 0,
                                    "reaction": None, "killed": False})
                continue

            dmg = int(raw)
            # 집중 물약 — 각 타에 동일 배율
            if self._next_skill_bonus > 1.0 and dmg > 0:
                dmg = int(dmg * self._next_skill_bonus)
            # 도적 주사위 — 배율/강제크리 각 타 적용, 출혈은 스킬 전체 1회
            if dice_info:
                dmg = int(round(dmg * dice_info["mult"]))
                if dice_info["force_crit"] and not crit:
                    dmg = int(dmg * 1.5)
                    crit = True
                if dice_info["bleed"] and not bleed_done and hasattr(cur, "apply_status_effect"):
                    from ai.battle.Entity import StatusEffect
                    cur.apply_status_effect(StatusEffect(
                        effect_type="bleed", turns=3, name="출혈"))
                    msgs.append(f"🩸 {cur.name} 출혈!")
                    bleed_done = True

            # ── 원소 부착/반응 (타격마다 — 재타겟 시 새 대상 큐 기준) ──
            reaction_msgs: list = []
            dmg = apply_element_and_react(
                self.player, cur, meta.get("element", "") or "physical",
                dmg, reaction_msgs)
            reacted = bool(reaction_msgs)
            msgs.extend(reaction_msgs)

            # ── 실드 흡수 → HP 적용 ──
            sh_before = getattr(cur, "shield", 0.0)
            hp_dmg = self._apply_dmg_shielded(cur, dmg, msgs)
            sh_absorbed = max(0.0, sh_before - getattr(cur, "shield", 0.0))
            total_hp_dmg += hp_dmg
            total_shield_dmg += sh_absorbed

            killed = cur.hp <= 0
            tag = " (치명타!)" if crit else ""
            kill_tag = " 처치!" if killed else ""
            msgs.append(f"{hi}타: {cur.name}에게{tag} {hp_dmg} 피해!{kill_tag}")
            hits_detail.append({"hit": hi, "target_name": cur.name,
                                "dodge": False, "crit": bool(crit),
                                "damage": int(hp_dmg),
                                "shield_damage": int(sh_absorbed),
                                "reaction": reaction_msgs[0] if reaction_msgs else None,
                                "killed": killed})

        # 총합
        if total_shield_dmg > 0:
            msgs.append(f"총 {int(total_hp_dmg)} HP 피해 / {int(total_shield_dmg)} 실드 피해")
        else:
            msgs.append(f"총 {int(total_hp_dmg)} 피해!")

        if self._next_skill_bonus > 1.0:
            msgs.append("✨ 집중 효과 적용됨!")
            self._next_skill_bonus = 1.0
        self._end_rogue_dice()

        self.logs.append(TurnLog(
            turn=self.turn, actor="player", action="skill",
            action_detail=skill_name,
            damage_dealt=int(total_hp_dmg),
            hp_after=max(0, (cur.hp if cur is not None else 0)),
            mp_after=self.player.mp,
        ))
        # RL 로그용 타격 상세 (Battle_Log가 소비)
        self._rl_hits_detail = {"skill": skill_name, "hits": hits_detail,
                                "retargeted": retargeted,
                                "total_damage": int(total_hp_dmg + total_shield_dmg)}

        # ── 다대일 보정 실드 (스킬 1회당 1번) ──
        msh = meta.get("multi_shield", 0.0)
        if msh > 0 and self.player.job == "전사":
            alive_cnt = sum(1 for e in self.enemies if e.hp > 0)
            if alive_cnt >= 2:
                cap = self.player.maxhp * meta.get("multi_shield_cap", 0.0)
                gained = self.player.maxhp * msh
                self.player.shield = min(cap, self.player.shield + gained)
                msgs.append(f"🛡 다대일 대응! 실드 +{int(gained)} "
                            f"(현재 {int(self.player.shield)})")

        self.skills_used += 1
        # 전사 공격 카운트 — 시도된 타격 수만큼
        for _ in range(attempted):
            self._count_warrior_attack(msgs)
        return "ok"

    def _count_warrior_attack(self, msgs: list):
        """
        전사 패시브 — 적 공격(일반공격/공격형 스킬) 사용 3회마다 maxhp 10% 회복.
        아이템/버프/힐/디버프는 카운트하지 않음. 전투 시작 시 0 (lazy init).
        """
        if getattr(self.player, "job", "") != "전사":
            return
        cnt = getattr(self, "_warrior_attack_count", 0) + 1
        self._warrior_attack_count = cnt
        if cnt % 3 == 0 and self.player.hp > 0:
            m = self.player.passive_on_turn_start()
            if m:
                msgs.append(m)

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
            # ── 도적 주사위 (공격 입력 직후, 이모션 전) ──
            dice_info = self._roll_rogue_dice(msgs)
            dmg, dodge, crit = DamageCalc.physical(
                self.player.effective_stg(), self.player.luc,
                target.effective_arm(),       target.luc,
                skill_mult=1.0,
                role="player",
                attacker=self.player,
                defender=target,
            )
            self._end_rogue_dice()
            actual = 0 if dodge else int(dmg)
            if dodge:
                msgs.append(f"{target.name}이(가) 공격을 회피했다!")
            else:
                # ── 물리 원소 반응 (빙결+물리=깨짐 등) ──
                actual = apply_element_and_react(self.player, target, "physical", actual, msgs)
                # ── 주사위 배율/크리/출혈 (최종 피해 기준) ──
                if dice_info:
                    actual = self._apply_rogue_dice(actual, dice_info, target, msgs)
                    crit = crit or dice_info["force_crit"]
                dmg = self._apply_dmg_shielded(target, actual, msgs)
                tag = " (치명타!)" if crit else ""
                msgs.append(f"{self.player.name} → 공격{tag} | {dmg} 데미지")
                msgs.append(f"{target.name} HP: {max(0, int(target.hp))}")
            # ── 전사: 공격 사용 카운트 (+3회마다 회복) ──
            self._count_warrior_attack(msgs)

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

                # ── 도적 주사위 (AoE 전체에 배율 적용, 출혈은 피격 대상 전부) ──
                dice_info = self._roll_rogue_dice(msgs)

                # 1) 첫 대상 — execute_skill로 MP 정상 차감
                first = alive_targets[0]
                dmg, mp_lack, _info = execute_skill(skill_name, self.player, first)
                if self._next_skill_bonus > 1.0 and dmg > 0:
                    dmg = int(dmg * self._next_skill_bonus)
                if mp_lack:
                    self._end_rogue_dice()
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

                # ── 주사위 배율/크리/출혈 (첫 대상) ──
                if dice_info:
                    dmg = self._apply_rogue_dice(dmg, dice_info, first, msgs)

                hit_targets = 1 if dmg > 0 else 0   # 명중(비회피) 카운트 — 실드용 (흡수와 무관)
                dmg = self._apply_dmg_shielded(first, dmg, msgs)
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
                        # 주사위 배율/출혈 (ATB/크리 메시지는 첫 대상에서 1회만 출력됨)
                        if dice_info:
                            raw = int(round(raw * dice_info["mult"]))
                            if dice_info["force_crit"]:
                                raw = int(raw * 1.5)
                            if dice_info["bleed"] and hasattr(tgt, "apply_status_effect"):
                                from ai.battle.Entity import StatusEffect
                                tgt.apply_status_effect(StatusEffect(
                                    effect_type="bleed", turns=3, name="출혈"))
                        hit_targets += 1   # 명중 기준 (흡수와 무관)
                        raw = self._apply_dmg_shielded(tgt, raw, msgs)
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
                # ── 전사 광역 생존기: 명중한 적 수만큼 실드 (슬래시 전용) ──
                sph = meta.get("shield_per_hit", 0.0)
                if sph > 0 and self.player.job == "전사" and hit_targets > 0:
                    cap = meta.get("shield_cap", 0.0)
                    ratio = min(sph * hit_targets, cap)
                    gained = self.player.maxhp * ratio
                    self.player.shield = max(self.player.shield, gained)
                    msgs.append(f"🛡 {skill_name} — {hit_targets}명 명중! 실드 +{int(gained)} "
                                f"(maxhp {int(ratio*100)}%)")
                self.skills_used += 1   # ★ AoE 스킬 사용 성공 (Phase 3)
                self._end_rogue_dice()
                self._count_warrior_attack(msgs)   # AoE는 공격형 — 전사 카운트
                return "ok"

            # ── 단일 타깃 스킬 (기존 로직 + buff/heal/shield 메시지 보강) ──
            # 도적 주사위: 공격형 스킬(physical/magical/tank_attack/counter/multi_hit)에만
            _stype_for_dice = meta.get("type", "")
            dice_info = (self._roll_rogue_dice(msgs)
                         if _stype_for_dice in self._ATTACK_SKILL_TYPES else None)

            # ── 연속공격류: hits>1 physical/magical은 개별 타격 판정 경로 ──
            if meta.get("hits", 1) > 1 and _stype_for_dice in ("physical", "magical"):
                return self._exec_multi_hit_skill(skill_name, meta, target, msgs, dice_info)

            mp_before = self.player.mp
            dmg, mp_lack, debuff_name = execute_skill(
                skill_name, self.player, target
            )
            self._end_rogue_dice()
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
                    # ── 주사위 배율/크리/출혈 (최종 피해 기준) ──
                    if dice_info:
                        dmg = self._apply_rogue_dice(dmg, dice_info, target, msgs)
                    dmg = self._apply_dmg_shielded(target, dmg, msgs)
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

                # ── 다대일 보정 실드 (연속공격1 등) ──
                #    조건: 살아있는 적 2마리 이상 + 전사 + 스킬 사용 성공
                #    명중 여부와 무관하게 1회 부여 (cap까지 누적 아닌 상한 유지)
                msh = meta.get("multi_shield", 0.0)
                if msh > 0 and self.player.job == "전사":
                    alive_cnt = sum(1 for e in self.enemies if e.hp > 0)
                    if alive_cnt >= 2:
                        cap = self.player.maxhp * meta.get("multi_shield_cap", 0.0)
                        gained = self.player.maxhp * msh
                        self.player.shield = min(cap, self.player.shield + gained)
                        msgs.append(f"🛡 다대일 대응! 실드 +{int(gained)} "
                                    f"(현재 {int(self.player.shield)})")

                # ★ 단일 스킬 사용 성공 (Phase 3) — else 블록 맨 끝
                # debuff / buff / heal / shield / 일반 데미지 모두 카운트
                self.skills_used += 1
                # 전사: 공격형 스킬만 카운트 (버프/힐/실드/디버프 제외)
                if _stype_for_dice in self._ATTACK_SKILL_TYPES:
                    self._count_warrior_attack(msgs)

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
