# -*- coding: utf-8 -*-
"""
Battle_Log.py — 전투 (state, action, result) 로그 믹스인
─────────────────────────────────────────────────────────
행동 패턴 분석/자동 밸런싱 학습용 로그. step 1회 = 레코드 1개.

  state_t : 행동 "직전" 상태 스냅샷
            플레이어(직업/레벨/HP/MP/ATB/스탯/버프/디버프/실드)
            적 목록(이름/레벨/HP/ATB/스탯/원소/버프/디버프/실드)
            인벤토리/스킬 목록, 현재 타깃, 턴 번호
            (노드/챕터/전투타입은 앱 레이어가 battle_meta로 주입)
  action_t: 행동자/타입/상세/타깃, 선택 가능했던 행동 목록, AI·사람 여부
            (적 턴은 _rl_post에서 TurnLog로 실제 스킬명 보강)
  result_t: 준 피해/실드 흡수/받은 피해/처치/상태이상·원소반응(이름 포함)/
            damage_type·element_type/치명타·회피/부여된 버프·디버프/승패
            — "받은 공격 스택" 명세의 필드를 이 레코드가 대신한다.

사용:
  BattleSession이 이 믹스인을 상속. step()이 자동 기록.
  bs.rl_log                  → 레코드 리스트 (직렬화 가능한 순수 dict)
  bs.battle_meta             → {"node_type":..., "chapter":..., "source":"human"|"ai"}
  bs.rl_finalize(extra)      → 전투 종료 후 exp/gold/items 등 최종 보상 병합
"""
from typing import Optional


class BattleLogMixin:
    # ───────────────────────── 내부 스냅샷 도우미 ─────────────────────────

    @staticmethod
    def _rl_pack_effects(unit) -> dict:
        """버프/디버프/상태이상을 직렬화 가능한 형태로."""
        def _turns(x):
            # 실제 속성명은 turns — 구버전 호환으로 turns_left fallback
            v = getattr(x, "turns", None)
            if v is None:
                v = getattr(x, "turns_left", 0)
            return v

        out = {"buffs": [], "debuffs": [], "status": []}
        for b in getattr(unit, "buffs", []) or []:
            out["buffs"].append({"stat": getattr(b, "stat", ""),
                                 "amount": getattr(b, "amount", 0),
                                 "turns": _turns(b)})
        for d in getattr(unit, "debuffs", []) or []:
            out["debuffs"].append({"stat": getattr(d, "stat", ""),
                                   "amount": getattr(d, "amount", 0),
                                   "turns": _turns(d)})
        for s in getattr(unit, "status_effects", []) or []:
            out["status"].append({"name": getattr(s, "name", ""),
                                  "type": getattr(s, "effect_type", ""),
                                  # 출혈만 쓰는 값 — 스택 수가 곧 틱 피해라
                                  # 이름만으로는 상태를 복원할 수 없었다
                                  "stacks": getattr(s, "stacks", 1),
                                  "turns": _turns(s)})
        return out

    def _rl_pack_player(self) -> dict:
        p = self.player
        d = {
            "job": p.job, "lv": p.lv,
            "hp": round(p.hp, 1), "maxhp": p.maxhp,
            "mp": round(p.mp, 1), "maxmp": p.maxmp,
            "atb": round(getattr(self, "player_atb", 0.0), 1),
            "shield": round(getattr(p, "shield", 0.0), 1),
            "stats": {"stg": p.stg, "arm": p.arm, "sparm": p.sparm,
                      "sp": p.sp, "luc": p.luc, "spd": p.effective_spd()},
            # ★ 2차에서 들어온 자원 축 — 이게 없으면 "왜 그 행동을 골랐는지"를
            #   로그만 보고 복원할 수 없다(주사위를 미리 봤는지, 공명 몇 단계인지,
            #   전투당 1회짜리를 이미 썼는지가 전부 선택의 근거다).
            "pending_dice":   getattr(p, "pending_dice", 0),      # 패 고치기가 미리 본 눈 (0 = 없음)
            "dice_fix_uses":  getattr(p, "dice_fix_uses", 0),     # 이번 전투 재굴림 사용 횟수
            "free_rerolls":   getattr(p, "free_rerolls", 0),      # 연막이 준 무료 재굴림
            "resonance": {                                        # 마법사 원소 공명
                "element":  getattr(p, "resonance_element", ""),
                "stack":    getattr(p, "resonance_stack", 0),
                "switched": bool(getattr(p, "resonance_switched", False)),
            },
            "relics":            list(getattr(p, "relics", []) or []),
            "relic_revive_used": bool(getattr(p, "relic_revive_used", False)),
            "once_used":         list(getattr(p, "once_used", []) or []),   # 불굴 등 전투당 1회 스킬
        }
        d.update(self._rl_pack_effects(p))
        return d

    def _rl_pack_enemies(self) -> list:
        out = []
        for i, e in enumerate(self.enemies):
            d = {
                "idx": i, "name": e.name, "lv": e.lv,
                "hp": round(max(0.0, e.hp), 1), "maxhp": e.maxhp,
                "atb": round(self.enemy_atbs[i], 1) if i < len(getattr(self, "enemy_atbs", [])) else 0.0,
                "shield": round(getattr(e, "shield", 0.0), 1),
                "element_queue": list(getattr(e, "element_queue", []) or []),
                "attack_element": getattr(e, "attack_element", ""),
                "difficulty": getattr(e, "difficulty", ""),
                "stats": {"stg": e.stg, "arm": e.arm, "sparm": e.sparm,
                          "sp": e.sp, "luc": e.luc, "spd": e.effective_spd()},
            }
            # ★ 예고·페이즈 — 화면에는 배지로 보여주면서(State.py의 _pattern_badges)
            #   학습 로그에는 없었다. "다음 행동이 예고된 상태였는가"는 플레이어
            #   선택의 가장 큰 근거인데 그게 빠져 있으면 행동을 설명할 수 없다.
            if getattr(e, "boss_phase", 0) or getattr(e, "boss_telegraph_at", -1) >= 0:
                d["boss"] = {
                    "phase":         getattr(e, "boss_phase", 0),
                    "cycle":         getattr(e, "boss_cycle", 0),
                    # 예고 예약 시점(플레이어 행동 횟수). armed=True면 다음 보스
                    # 행동에 강공격이 터진다 — 예고 보장 규칙(4장) 그대로의 판정.
                    "telegraph_at":  getattr(e, "boss_telegraph_at", -1),
                    "armed":         (getattr(e, "boss_telegraph_at", -1) >= 0
                                      and getattr(self, "_player_action_count", 0)
                                          > getattr(e, "boss_telegraph_at", -1)),
                    "doom_at":       getattr(e, "boss_doom_at", -1),
                    "doom_count":    getattr(e, "boss_doom_count", 0),
                }
            if getattr(e, "elite_leader", False):
                d["elite"] = {
                    "phase":        getattr(e, "elite_phase", 0),
                    "pattern_turn": getattr(e, "elite_pattern_turn", 0),
                    "pattern_used": bool(getattr(e, "elite_pattern_used", False)),
                }
            d.update(self._rl_pack_effects(e))
            out.append(d)
        return out

    def _rl_available_actions(self) -> list:
        """이 시점 플레이어가 선택 가능했던 행동 목록.
        ★ 판정은 skill_requirement_error() 하나로 통일한다 — 전투 메뉴의 회색
          처리(get_skills)·측정용 AI·execute_skill 안전망이 쓰는 그 함수다.
          예전엔 여기서만 MP만 보고 판단해서, 출혈이 없는 대상에게 쓸 수 없는
          「피의 수확」이나 HP 35% 초과에서 못 쓰는 「불굴」, 횟수를 소진한
          「패 고치기」가 "선택 가능"으로 기록됐다 — 학습 데이터가 실제로는
          고를 수 없던 행동을 후보로 들고 있었다는 뜻이다.
        ※ 여기 나열된 행동이 전부 실제로 성공한다는 뜻은 아니다 — 마비 상태면
          이 목록과 무관하게 어떤 행동이든 확률적으로 강제 실패할 수 있다
          (_step_core의 is_paralyzed() 판정 참고). action_t의
          forced_fail_risk 플래그가 그 가능성을 나타낸다.
        ※ skill_requirement_error()는 순수 판정이라 난수를 쓰지 않는다 —
          로그를 남기는 것만으로 전투 결과가 달라지지 않는다."""
        from ai.battle import skill_requirement_error
        acts = ["attack", "escape"]
        p = self.player
        target = getattr(self, "enemy", None)
        blocked = {}
        for sk in getattr(p, "learned_skills", []) or []:
            why = skill_requirement_error(sk, p, target)
            if why:
                blocked[sk] = why
            else:
                acts.append(f"skill:{sk}")
        # 아이템은 "현재 전투 인벤토리"(BattleSession.items) 기준 —
        # use_item이 self.items에서 차감하므로 사용 후 목록이 즉시 갱신된다.
        for it in getattr(self, "items", []) or []:
            acts.append(f"item:{it}")
        self._rl_blocked_skills = blocked      # _rl_pre가 같은 step에 함께 싣는다
        return acts

    @staticmethod
    def _rl_has_paralyze(unit) -> bool:
        """마비 상태이상 보유 여부만 확인 — is_paralyzed()와 달리 실제 확률을
        굴리지 않는다. RL 로그를 남기려고 여기서 is_paralyzed()를 한 번 더
        부르면 그 호출 자체가 RNG를 소모해서, 실제 턴 처리(_step_core)가
        나중에 쓰는 난수 시퀀스가 밀려 전투 결과가 달라질 수 있다."""
        return any(getattr(e, "effect_type", "") == "paralyze"
                   for e in getattr(unit, "status_effects", []) or [])

    # ───────────────────────── pre / post 후킹 ─────────────────────────

    def _rl_pre(self, action: str) -> Optional[dict]:
        """행동 직전 스냅샷. done 상태거나 상태조회 전용(status, 실제 행동
        아님)이면 기록 생략.
        ★ "status"를 그냥 두면 실제로는 아무 행동도 일어나지 않았는데 정상
          행동 레코드가 남고, 특히 적 턴 도중 호출되면 _rl_post가 직전의
          진짜 행동(self.logs[-1])을 재사용해 그 행동을 중복 기록했다."""
        if getattr(self, "done", False) or action == "status":
            return None
        try:
            actor, aidx = self._peek_next_actor()
        except Exception:
            actor, aidx = ("player", -1)
        if actor == "done":
            return None

        is_player = (actor == "player")
        acting_unit = self.player if is_player else (
            self.enemies[aidx] if 0 <= aidx < len(self.enemies) else None)
        state_t = {
            "turn": self.turn,
            "player": self._rl_pack_player(),
            "enemies": self._rl_pack_enemies(),
            "target_idx": getattr(self, "_target_idx", 0),
            "skills": list(getattr(self.player, "learned_skills", []) or []),
            "inventory": list(getattr(self, "items", []) or []),   # 전투 인벤토리 기준
        }
        state_t.update(getattr(self, "battle_meta", {}) or {})

        # 행동 파싱 (플레이어 행동일 때만 의미)
        atype, detail, tgt = "auto", "", state_t["target_idx"]
        if is_player and action != "auto":
            parts = str(action).split(":")
            atype = parts[0]
            detail = parts[1] if len(parts) > 1 else ""
            if len(parts) > 2:
                try:
                    tgt = int(parts[2])
                except ValueError:
                    pass

        action_t = {
            "actor": "player" if is_player else "enemy",
            "actor_idx": aidx,
            "type": atype if is_player else "auto",
            "detail": detail,
            "target_idx": tgt,
            "available": self._rl_available_actions() if is_player else [],
            # 고를 수 없던 스킬과 그 이유 — {스킬: "mp"|"no_bleed"|"hp_high"|"used"|
            # "max_uses"|"no_element"}. available의 여집합이라 "무엇이 왜 빠졌는지"가
            # 남는다(_rl_available_actions가 같은 판정에서 채운다).
            "blocked": dict(getattr(self, "_rl_blocked_skills", {})) if is_player else {},
            # available 목록은 "선택 가능"했다는 뜻일 뿐 — 마비 상태면 이 중
            # 무엇을 골라도 확률적으로 강제 실패할 수 있다(실제 확률은 여기서
            # 굴리지 않음, _rl_has_paralyze 참고).
            "forced_fail_risk": self._rl_has_paralyze(acting_unit) if acting_unit is not None else False,
            "source": (getattr(self, "battle_meta", {}) or {}).get("source", "human")
                      if is_player else "ai",
        }

        # diff 계산용 이전 수치
        prev = {
            "p_hp": self.player.hp, "p_shield": getattr(self.player, "shield", 0.0),
            "e_hp": [e.hp for e in self.enemies],
            "e_shield": [getattr(e, "shield", 0.0) for e in self.enemies],
            "e_alive": [e.hp > 0 for e in self.enemies],
        }
        # log_len: 이번 step에 새로 추가된 TurnLog만 골라내기 위한 경계 (_rl_post)
        return {"state": state_t, "action": action_t, "prev": prev,
                "log_len": len(self.logs)}

    # 원소 반응 라벨 → 반응명 (Elements.REACTION_EFFECTS의 label과 짝맞춤)
    _REACTION_LABEL_TO_NAME = {"융해": "melt", "파쇄": "shatter", "과부하": "overload"}

    def _rl_derive_action_meta(self, action_t: dict) -> dict:
        """행동의 damage_type/element_type/buff·debuff_applied를 스킬 메타로 유도.
        몬스터가 플레이어 전용기를 쓴 경우 MONSTER_SKILL_META를 우선 조회
        (execute_skill의 몬스터 계수 분기와 동일한 우선순위)."""
        from ai.battle import SKILL_META, MONSTER_SKILL_META
        atype  = action_t.get("type", "")
        detail = action_t.get("detail", "")
        is_enemy = action_t.get("actor") == "enemy"

        if atype == "attack":
            elem = "physical"
            if is_enemy:
                aidx = action_t.get("actor_idx", -1)
                if 0 <= aidx < len(self.enemies):
                    elem = getattr(self.enemies[aidx], "attack_element", "") or "physical"
            return {"damage_type": "physical", "element_type": elem,
                    "buffs_applied": [], "debuffs_applied": []}

        if atype == "skill":
            meta = (MONSTER_SKILL_META.get(detail) if is_enemy else None) or SKILL_META.get(detail) or {}
            stype = meta.get("type", "")
            dmg_type = "magical" if stype == "magical" else (
                "physical" if stype in ("physical", "tank_attack", "counter", "multi_hit") else "")
            return {
                "damage_type": dmg_type,
                "element_type": meta.get("element", ""),
                "buffs_applied": [detail] if stype == "buff" else [],
                "debuffs_applied": [detail] if stype == "debuff" else [],
            }

        return {"damage_type": "", "element_type": "", "buffs_applied": [], "debuffs_applied": []}

    def _rl_no_action_kind(self, msgs: list) -> str:
        """이번 step에 행동자의 TurnLog가 하나도 없을 때의 행동 종류.
        실측(무작위 실전 2,034 step)으로는 1.5%가 여기 해당한다 —
          paralyzed : 마비로 행동에 실패 (차례는 소비, 선택한 행동 없음)
          ritual    : 엘리트 사제 부활 의식 준비/완성 (TurnLog를 남기지 않는 행동)
          none      : 그 외 — DoT로 행동 전에 사망, 죽은 적의 차례를 건너뜀 등"""
        override = getattr(self, "_fx_override", None)
        if override and override.get("stype") == "ritual":
            return "ritual"
        if any("마비로 행동에 실패" in m for m in msgs):
            return "paralyzed"
        return "none"

    def _rl_post(self, pre: Optional[dict], out: dict) -> None:
        if pre is None:
            return
        prev = pre.pop("prev")
        new_logs = self.logs[pre.pop("log_len", 0):]
        msgs = out.get("messages", []) or []

        dmg_dealt = sum(max(0.0, prev["e_hp"][i] - max(0.0, e.hp))
                        for i, e in enumerate(self.enemies) if i < len(prev["e_hp"]))
        e_absorbed = sum(max(0.0, prev["e_shield"][i] - getattr(e, "shield", 0.0))
                         for i, e in enumerate(self.enemies) if i < len(prev["e_shield"]))
        dmg_taken = max(0.0, prev["p_hp"] - self.player.hp)
        p_absorbed = max(0.0, prev["p_shield"] - getattr(self.player, "shield", 0.0))
        kills = sum(1 for i, e in enumerate(self.enemies)
                    if i < len(prev["e_alive"]) and prev["e_alive"][i] and e.hp <= 0)

        # ── 이번 step에 "이 행동자"가 남긴 로그만 본다 ──
        #    예전엔 self.logs[-1]을 썼는데, 새 로그가 없는 step(마비 실패·DoT 사망·
        #    부활 의식)에서 직전 step의 행동과 크리·회피가 그대로 복제됐다.
        #    도적 회피 반격(counter, actor=player)은 적 차례에 끼어드는 로그라
        #    행동자 판정에서 뺀다.
        action_t = pre["action"]
        actor = action_t.get("actor")
        act_log = next((l for l in reversed(new_logs)
                        if getattr(l, "actor", "") == actor
                        and getattr(l, "action", "") != "counter"), None)
        if act_log is None:
            action_t["type"] = self._rl_no_action_kind(msgs)
            action_t["detail"] = ""
        elif actor == "enemy":
            # 적 턴은 _rl_pre 시점에 행동이 아직 결정되지 않아 "auto"/""로만 채워져 있다
            action_t["type"] = "skill" if act_log.action == "skill" else (
                "attack" if act_log.action == "attack" else act_log.action)
            action_t["detail"] = act_log.action_detail

        reaction_name = None
        for label, name in self._REACTION_LABEL_TO_NAME.items():
            if any(label in m for m in msgs):
                reaction_name = name
                break

        act_meta = self._rl_derive_action_meta(action_t)
        if act_log is not None and act_log.debuff_applied and not act_meta["debuffs_applied"]:
            act_meta["debuffs_applied"] = [act_log.debuff_applied]

        result_t = {
            # 스키마 잠금: damage(총) = hp_damage + shield_damage (행동자가 준 피해)
            "damage":        round(dmg_dealt + e_absorbed, 1),
            "hp_damage":     round(dmg_dealt, 1),
            "shield_damage": round(e_absorbed, 1),
            "damage_taken":        round(dmg_taken + p_absorbed, 1),
            "hp_damage_taken":     round(dmg_taken, 1),
            "shield_damage_taken": round(p_absorbed, 1),
            "killed": kills,
            "reaction": reaction_name is not None,
            "reaction_name": reaction_name,
            "damage_type": act_meta["damage_type"],
            "element_type": act_meta["element_type"],
            "crit": bool(getattr(act_log, "is_crit", False)) if act_log is not None else False,
            "evade": bool(getattr(act_log, "is_dodge", False)) if act_log is not None else False,
            "buffs_applied": act_meta["buffs_applied"],
            "debuffs_applied": act_meta["debuffs_applied"],
            "status_applied": any(k in m for m in msgs for k in ("🩸", "빙결", "감전", "화상", "🌀", "균열")),
            "battle_done": bool(getattr(self, "done", False)),
            "winner": getattr(self, "winner", None) if getattr(self, "done", False) else None,
        }
        # multi-hit 타격 상세 (Player_Actions._exec_multi_hit_skill이 세팅)
        hd = getattr(self, "_rl_hits_detail", None)
        if hd:
            result_t["multi_hit"] = hd
            self._rl_hits_detail = None

        pre["result"] = result_t
        self.rl_log.append(pre)

    # ───────────────────────── 종료 시 최종 보상 병합 ─────────────────────────

    def rl_finalize(self, extra: dict) -> None:
        """전투 종료 후 앱 레이어가 exp/gold/items 등 최종 보상을 마지막 레코드에 병합."""
        if self.rl_log:
            self.rl_log[-1]["result"].update(extra or {})