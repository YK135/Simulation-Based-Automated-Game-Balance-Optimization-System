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
  result_t: 준 피해/실드 흡수/받은 피해/처치/상태이상·원소반응/승패

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
            d.update(self._rl_pack_effects(e))
            out.append(d)
        return out

    def _rl_available_actions(self) -> list:
        """이 시점 플레이어가 선택 가능했던 행동 목록."""
        from ai.battle import SKILL_META
        acts = ["attack", "escape"]
        p = self.player
        for sk in getattr(p, "learned_skills", []) or []:
            meta = SKILL_META.get(sk, {})
            cost = meta.get("mp", 0) * p.mp_cost_multiplier()
            if p.mp >= cost:
                acts.append(f"skill:{sk}")
        # 아이템은 "현재 전투 인벤토리"(BattleSession.items) 기준 —
        # use_item이 self.items에서 차감하므로 사용 후 목록이 즉시 갱신된다.
        for it in getattr(self, "items", []) or []:
            acts.append(f"item:{it}")
        return acts

    # ───────────────────────── pre / post 후킹 ─────────────────────────

    def _rl_pre(self, action: str) -> Optional[dict]:
        """행동 직전 스냅샷. done 상태면 기록 생략."""
        if getattr(self, "done", False):
            return None
        try:
            actor, aidx = self._peek_next_actor()
        except Exception:
            actor, aidx = ("player", -1)
        if actor == "done":
            return None

        is_player = (actor == "player")
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
        return {"state": state_t, "action": action_t, "prev": prev}

    def _rl_post(self, pre: Optional[dict], out: dict) -> None:
        if pre is None:
            return
        prev = pre.pop("prev")
        msgs = out.get("messages", []) or []

        dmg_dealt = sum(max(0.0, prev["e_hp"][i] - max(0.0, e.hp))
                        for i, e in enumerate(self.enemies) if i < len(prev["e_hp"]))
        e_absorbed = sum(max(0.0, prev["e_shield"][i] - getattr(e, "shield", 0.0))
                         for i, e in enumerate(self.enemies) if i < len(prev["e_shield"]))
        dmg_taken = max(0.0, prev["p_hp"] - self.player.hp)
        p_absorbed = max(0.0, prev["p_shield"] - getattr(self.player, "shield", 0.0))
        kills = sum(1 for i, e in enumerate(self.enemies)
                    if i < len(prev["e_alive"]) and prev["e_alive"][i] and e.hp <= 0)

        result_t = {
            # 스키마 잠금: damage(총) = hp_damage + shield_damage (행동자가 준 피해)
            "damage":        round(dmg_dealt + e_absorbed, 1),
            "hp_damage":     round(dmg_dealt, 1),
            "shield_damage": round(e_absorbed, 1),
            "damage_taken":        round(dmg_taken + p_absorbed, 1),
            "hp_damage_taken":     round(dmg_taken, 1),
            "shield_damage_taken": round(p_absorbed, 1),
            "killed": kills,
            "reaction": any(k in m for m in msgs for k in ("융해", "과부하", "파쇄")),
            "status_applied": any(k in m for m in msgs for k in ("🩸", "빙결", "감전", "화상", "🌀")),
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