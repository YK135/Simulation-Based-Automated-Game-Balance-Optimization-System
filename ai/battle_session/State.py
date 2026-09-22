"""
battle_session/state.py — 상태 JSON
"""
from __future__ import annotations

from ai.battle import (
    _current_element, SKILL_META,
)
from ai.battle.EliteKit import (
    ASSASSIN_MARK_INTERVAL, BAT_SCREAM_INTERVAL,
    FIRE_SLIME_STACK_THRESHOLD, LIGHTNING_SLIME_STACK_THRESHOLD,
    GOLEM_PHASE_GUARD, GOLEM_PHASE_CHARGE, GOLEM_PHASE_STRIKE,
    PRIEST_PHASE_PREPARING, SLIME_SPLIT_STUN_ACTIONS,
)
from ai.battle.BossKit import (
    is_midboss, MIDBOSS_PHASE_LABEL, MIDBOSS_RIFT_INTERVAL,
    is_finalboss, is_shadow, FINALBOSS_PHASE_LABEL, FINALBOSS_ELEMENT_KOR, FINALBOSS_CYCLE_TURNS,
    finalboss_current_element, finalboss_next_element, GRASP_INTERVAL, SHADOW_GUARD,
    SHADOW_RESUMMON_TURNS, DOOM_FIRST_COUNT, DOOM_REPEAT_COUNT,
)
from ai.battle.Elements import RESONANCE_MAX_STACK as _RESONANCE_MAX
from ai.battle.Relics import relic_telegraph_lead, relic_resonance_max
from ai.battle.MonsterKit import (
    is_goblin, GOBLIN_PACK_STG_CAP, GOBLIN_PACK_STG_PER_ALLY, PRIEST_TYPE, PRIEST_QUICK_REVIVE_SKILL,
)
from game.Inventory import Inventory

# ── 엘리트 패턴 UI 배지 정의 (표시 전용) ───────────────────────
# "n회 행동마다 예고 → 다음 행동에 발동" 형태를 공유하는 두 리더.
# elite_pattern_turn이 카운터, elite_phase 1/2가 "예고됨"을 뜻한다
# (EliteKit.elite_forced_action 참고 — 1=막 예고, 2=다음 행동에 발동).
_TELEGRAPH_COUNTDOWN = {
    "박쥐":   ("초음파비명", BAT_SCREAM_INTERVAL),
    "암살자": ("암살 표식",  ASSASSIN_MARK_INTERVAL),
}
# 피격 스택이 임계치에 닿으면 강스킬이 나가는 원소 슬라임 두 종.
# elite_pattern_turn이 곧 스택 수이고, 임계치에 닿는 순간 소비된다.
_STACK_GAUGE = {
    "화염 슬라임": ("과부하 화염", FIRE_SLIME_STACK_THRESHOLD),
    "번개 슬라임": ("과부하 전격", LIGHTNING_SLIME_STACK_THRESHOLD),
}
# 골렘 3단계 사이클 — phase가 곧 "다음 행동에 무엇을 하는가"다.
_GOLEM_PHASE_LABEL = {
    GOLEM_PHASE_GUARD:  ("수비 태세", "idle"),
    GOLEM_PHASE_CHARGE: ("충전 예고", "charging"),
    GOLEM_PHASE_STRIKE: ("강타",      "armed"),
}
# 골렘 그로기: 일반공격 2연타로 방어력을 깎고, 충전 중이면 강타까지 취소된다
# (Player_Actions._update_golem_groggy). 엘리트가 아닌 골렘에게도 있다.
_GROGGY_HITS_REQUIRED = 2
# 중간 보스 페이즈 배지의 상태 — 3페이즈(붕괴)만 경고색으로 강조
_BOSS_PHASE_STATE = {1: "idle", 2: "charging", 3: "armed"}


class StateMixin:
    """BattleSession에 상태 JSON 기능을 제공하는 mixin."""

    @staticmethod
    def _pattern_badges(en, player_action_count: int = 0, telegraph_lead: int = 0) -> list:
        """적이 '이미 갖고 있는' 패턴 상태를 UI 배지로 노출한다.

        ★ 전투 계산에는 전혀 쓰이지 않는 읽기 전용 파생값이다 — 여기서
          엔티티를 수정하면 안 된다. 새 상태를 만들지도 않는다: 전부
          elite_phase / elite_pattern_turn / physical_hit_streak를 읽어서
          문장으로 바꿀 뿐이라, 이 함수를 통째로 지워도 밸런스는 불변이다.

        배지 하나: {kind, label, cur, max, state}
          kind  : telegraph(예고형) | stack(스택형) | cycle(골렘) | groggy(플레이어측 게이지)
                  | phase(보스 페이즈)
          state : armed(다음 행동에 발동) | charging(진행 중) | idle

        telegraph_lead: 유물 「예언서」 — armed를 몇 행동 먼저 보여줄지(0이면 기존과 동일).
                        ★ 표시 시점만 당길 뿐, 적의 행동은 전혀 바뀌지 않는다.
        """
        def armed_at(cur: int, full: int, gap: int = 1) -> bool:
            """예고·스택이 "다음 행동에 터진다"로 보이는 시점. lead가 0이면 기존 판정 그대로."""
            return cur >= full - gap - telegraph_lead
        et      = getattr(en, "enemy_type", "")
        leader  = getattr(en, "elite_leader", False)
        phase   = getattr(en, "elite_phase", 0)
        counter = getattr(en, "elite_pattern_turn", 0)
        badges  = []

        if leader and et in _TELEGRAPH_COUNTDOWN:
            label, interval = _TELEGRAPH_COUNTDOWN[et]
            armed = phase != 0 or armed_at(min(counter, interval), interval, gap=0)
            badges.append({
                "kind":  "telegraph",
                "label": label,
                # 예고된 상태에서는 카운터가 0으로 리셋돼 있으므로 가득 찬 것으로 보여준다
                "cur":   interval if armed else min(counter, interval),
                "max":   interval,
                "state": "armed" if armed else "charging",
            })

        if leader and et in _STACK_GAUGE:
            label, threshold = _STACK_GAUGE[et]
            badges.append({
                "kind":  "stack",
                "label": label,
                "cur":   min(counter, threshold),
                "max":   threshold,
                "state": "armed" if armed_at(counter, threshold) else "charging",
            })

        if leader and et == "골렘":
            label, state = _GOLEM_PHASE_LABEL.get(phase, _GOLEM_PHASE_LABEL[GOLEM_PHASE_GUARD])
            badges.append({
                "kind":  "cycle",
                "label": label,
                "cur":   phase + 1,
                "max":   len(_GOLEM_PHASE_LABEL),
                "state": state,
            })

        # 증식 슬라임 본체 — 분열 직후 경직(플레이어에게 유리한 창이라 아군색 groggy)
        if getattr(en, "split_stun", 0) > 0:
            badges.append({
                "kind":  "groggy",
                "label": "분열 충격",
                "cur":   en.split_stun,
                "max":   SLIME_SPLIT_STUN_ACTIONS,
                "state": "armed",
            })

        if leader and et == "사제" and phase == PRIEST_PHASE_PREPARING \
                and not getattr(en, "elite_pattern_used", False):
            badges.append({
                "kind":  "telegraph",
                "label": "부활 의식",
                "cur":   1, "max": 1,
                "state": "armed",
            })

        # ── 일반 몬스터 정체성 (2장) — 값은 전부 세션이 이미 동기화한 필드를 읽기만 ──
        # 고블린 무리 전술: 가산이 붙어 있는 동안만 (살아있는 고블린 수 / 최대 3마리 게이지)
        if is_goblin(en) and getattr(en, "pack_bonus", 0.0) > 0:
            alive_goblins = 1 + int(round(en.pack_bonus / GOBLIN_PACK_STG_PER_ALLY))
            badges.append({
                "kind":  "stack",
                "label": f"무리 전술 +{int(round(en.pack_bonus * 100))}%",
                "cur":   alive_goblins,
                "max":   1 + int(round(GOBLIN_PACK_STG_CAP / GOBLIN_PACK_STG_PER_ALLY)),
                "state": "charging",
            })
        # 일반 사제 약식 소생: 아직 안 썼으면 "들고 있다"를 보여준다 (쓰면 사라진다)
        if not leader and et == PRIEST_TYPE and not getattr(en, "elite_pattern_used", False):
            badges.append({
                "kind":  "telegraph",
                "label": PRIEST_QUICK_REVIVE_SKILL,
                "cur":   1, "max": 1,
                "state": "idle",
            })

        # 중간 보스 — 페이즈(1/2/3)와 「대지 균열」 예고 카운터 (ai/battle/BossKit.py 필드를 읽기만)
        if is_midboss(en):
            bphase = getattr(en, "boss_phase", 0) or 1
            badges.append({
                "kind":  "phase",
                "label": MIDBOSS_PHASE_LABEL[bphase],
                "cur":   bphase,
                "max":   len(MIDBOSS_PHASE_LABEL),
                "state": _BOSS_PHASE_STATE[bphase],
            })
            interval = MIDBOSS_RIFT_INTERVAL.get(bphase)
            if getattr(en, "boss_telegraph_at", -1) >= 0:
                # 예약된 예고 — 페이즈 3으로 넘어가 주기가 없어졌어도 한 번은 발동한다
                full = interval or MIDBOSS_RIFT_INTERVAL[2]
                badges.append({"kind": "telegraph", "label": "대지 균열",
                               "cur": full, "max": full, "state": "armed"})
            elif interval:
                cyc = min(getattr(en, "boss_cycle", 0), interval)
                badges.append({"kind": "telegraph", "label": "대지 균열",
                               "cur": cyc, "max": interval,
                               "state": "armed" if armed_at(cyc, interval, gap=0) else "charging"})

        # 최종 보스 — 페이즈(1~4) + 페이즈별 규칙 (BossKit finalboss_* 필드를 읽기만)
        if is_finalboss(en):
            fphase = getattr(en, "boss_phase", 0) or 1
            badges.append({"kind": "phase", "label": FINALBOSS_PHASE_LABEL[fphase],
                           "cur": fphase, "max": len(FINALBOSS_PHASE_LABEL),
                           "state": {1: "idle", 2: "charging", 3: "charging", 4: "armed"}[fphase]})
            if fphase == 1:
                cur_e = FINALBOSS_ELEMENT_KOR[finalboss_current_element(en)]
                nxt_e = FINALBOSS_ELEMENT_KOR[finalboss_next_element(en)]
                cyc = min(getattr(en, "boss_cycle", 0), FINALBOSS_CYCLE_TURNS)
                badges.append({"kind": "cycle", "label": f"{cur_e} → 다음 {nxt_e}",
                               "cur": cyc, "max": FINALBOSS_CYCLE_TURNS,
                               "state": "armed" if armed_at(cyc, FINALBOSS_CYCLE_TURNS) else "charging"})
            if getattr(en, "boss_guard", 0.0) > 0:
                badges.append({"kind": "telegraph", "label": f"그림자 경감 −{int(SHADOW_GUARD * 100)}%",
                               "cur": 1, "max": 1, "state": "charging"})
            if getattr(en, "boss_stunned", 0) > 0:
                badges.append({"kind": "groggy", "label": "무방비", "cur": en.boss_stunned, "max": 2,
                               "state": "armed"})
            elif fphase == 2 and getattr(en, "boss_summon_cd", -1) > 0:
                left = en.boss_summon_cd
                badges.append({"kind": "cycle", "label": "재소환",
                               "cur": SHADOW_RESUMMON_TURNS - left, "max": SHADOW_RESUMMON_TURNS,
                               "state": "armed" if left <= 1 + telegraph_lead else "charging"})
            if getattr(en, "boss_telegraph_at", -1) >= 0:
                badges.append({"kind": "telegraph", "label": "심연의 손아귀",
                               "cur": GRASP_INTERVAL, "max": GRASP_INTERVAL, "state": "armed"})
            elif fphase == 3:
                gcyc = min(getattr(en, "boss_cycle", 0), GRASP_INTERVAL)
                badges.append({"kind": "telegraph", "label": "심연의 손아귀",
                               "cur": gcyc, "max": GRASP_INTERVAL,
                               "state": "armed" if armed_at(gcyc, GRASP_INTERVAL, gap=0) else "charging"})
            if fphase == 4 and getattr(en, "boss_doom_at", -1) >= 0:
                total = DOOM_FIRST_COUNT if getattr(en, "boss_doom_count", 0) == 0 else DOOM_REPEAT_COUNT
                left = max(0, en.boss_doom_at - player_action_count)   # 남은 플레이어 행동 수
                badges.append({"kind": "telegraph",
                               "label": "종언" + (" (즉사)" if getattr(en, "boss_doom_count", 0) else ""),
                               "cur": max(0, total - left), "max": total,
                               "state": "armed" if left <= 1 + telegraph_lead else "charging"})

        # 골렘 그로기는 엘리트 여부와 무관 — 플레이어가 쌓는 게이지라 항상 보여준다
        if et == "골렘":
            streak = getattr(en, "physical_hit_streak", 0)
            badges.append({
                "kind":  "groggy",
                "label": "그로기",
                "cur":   min(streak, _GROGGY_HITS_REQUIRED),
                "max":   _GROGGY_HITS_REQUIRED,
                "state": "armed" if streak >= _GROGGY_HITS_REQUIRED - 1 else "idle",
            })

        return badges

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
                {"type": s.effect_type, "name": s.name, "turns": s.turns,
                 "stacks": getattr(s, "stacks", 1)}      # 출혈 스택 (그 외는 1)
                for s in getattr(entity, "status_effects", [])
            ],
        }

    # ── 피해/회복 수치 팝업용 (UI 데미지 숫자) ──────────────────
    # 프론트가 한글 메시지 문자열에서 숫자를 파싱하지 않도록, step() 한 번 동안
    # 각 대상의 HP/실드 변화량을 구조화해서 내려준다.
    #   ※ step() 경계의 스냅샷 차분이라 "대상별 합계 1개"까지만 정확하다 —
    #     연속공격(hits>1)이나 AoE의 타별 분해는 하지 않는다(그건 타격 사이트
    #     전부를 계측해야 하는 별개 작업). UI도 한 행동당 대상별 숫자 1개를
    #     띄우므로 현재 표시 수준과 일치한다.
    # 피해 출처 태그 필드 (ai/battle/Entity.py의 EntitySnapshot — 표시 전용)
    _HIT_TAG_FIELDS = ("last_hit_element", "last_hit_reaction", "last_hit_via")

    # TurnLog.action → hit.via. 로그에 없는 행동(watch/escape 등)은 피해를 주지
    # 않으므로 매핑하지 않는다. counter(탱커 되갚기 / 도적 회피반격)는 반사 타격이라
    # 기본 공격과 같은 색으로 묶는다.
    _LOG_ACTION_TO_VIA = {
        "attack": "attack", "counter": "attack",
        "skill": "skill", "item": "item",
    }

    def _hp_snapshot(self, action: str = "") -> dict:
        """step() 진입 시 호출 — (hp, shield) 스냅샷을 뜨고 피격 장부를 켠다.
        action은 시전 대상 슬롯을 알아내는 데만 쓴다(없어도 동작)."""
        # ★ 피해 출처 태그를 여기서 지운다. 안 지우면 지난 step의 원소가 남아
        #   이번 step의 DoT 피해(태그를 안 남기는 경로도 있음)에 묻어 잘못된
        #   색으로 표시된다.
        for ent in [self.player] + list(self.enemies):
            for f in self._HIT_TAG_FIELDS:
                setattr(ent, f, "")
            ent.hit_ledger = []          # 이번 step에 일어난 피해·회복을 한 줄씩 기록
        self._fx_noted_targets = []      # 행동이 직접 알려준 시전 대상 (_note_fx_target)
        self._fx_override = None         # TurnLog를 남기지 않는 행동의 시전 정보

        def pair(e):
            return (float(getattr(e, "hp", 0.0)), float(getattr(e, "shield", 0.0)))

        # 이번 step의 행동자와 "시전 시점"의 대상 후보 — action_fx.targets는
        # 행동이 끝난 뒤 추정하면 이번 공격으로 죽은 적이 빠지므로 여기서 뜬다.
        actor, actor_idx = "", -1
        if not getattr(self, "done", False):
            try:
                actor, actor_idx = self._peek_next_actor()
            except Exception:                              # noqa: BLE001
                actor, actor_idx = "", -1
        alive = [en.hp > 0 for en in self.enemies]
        return {
            "player": pair(self.player),
            "enemies": [pair(en) for en in self.enemies],
            "log_len": len(self.logs),
            "actor": actor if actor in ("player", "enemy") else "",
            "actor_idx": actor_idx,
            "alive": alive,
            "target_idx": self._fx_target_slot(action, alive),
        }

    def _fx_target_slot(self, action: str, alive: list) -> int:
        """플레이어 단일 대상 행동이 실제로 겨눌 적 슬롯.
        Player_Actions._player_action + Targeting._current_target과 같은 규칙:
        'attack:N' / 'skill:이름:N'의 N이 살아 있으면 N, 아니면 현재 타깃,
        그것도 죽었으면 살아 있는 첫 적."""
        parts = str(action or "").split(":")
        n = None
        try:
            if parts[0] == "attack" and len(parts) == 2:
                n = int(parts[1])
            elif parts[0] == "skill" and len(parts) == 3:
                n = int(parts[2])
        except ValueError:
            n = None
        if n is not None and 0 <= n < len(alive) and alive[n]:
            return n
        cur = getattr(self, "_target_idx", 0)
        if 0 <= cur < len(alive) and alive[cur]:
            return cur
        return next((i for i, a in enumerate(alive) if a), -1)

    @staticmethod
    def _ledger_groups(entity, prev) -> dict:
        """장부를 damage/heal/shield 세 묶음으로 나누고, 장부에 안 잡힌 변화량을
        '잔차'로 채운다.

        잔차가 생기는 경우: 기록 훅이 없는 경로로 HP/실드가 바뀐 경우(새 경로가
        훅 없이 추가됐거나, 테스트가 hp를 직접 바꾼 경우). 잔차 덕분에 화면에서
        숫자가 사라지지는 않지만, 실전 경로에서는 0이어야 정상이다 —
        TestFile/test_hit_ledger.py가 무작위 전투로 이걸 검사한다.
        """
        prev_hp, prev_shield = prev
        hp     = float(getattr(entity, "hp", 0.0))
        shield = float(getattr(entity, "shield", 0.0))
        ledger = getattr(entity, "hit_ledger", None) or []

        groups = {"damage": [], "heal": [], "shield": []}
        hp_net = sh_net = 0.0
        for e in ledger:
            k = e["kind"]
            if k == "damage":
                groups["damage"].append(e); hp_net -= e["amount"]
            elif k == "absorb":
                groups["damage"].append(e); sh_net -= e["amount"]
            elif k == "heal":
                groups["heal"].append(e);   hp_net += e["amount"]
            elif k == "shield":
                groups["shield"].append(e); sh_net += e["amount"]

        stamp = {
            "via":      getattr(entity, "last_hit_via", "") or "",
            "element":  getattr(entity, "last_hit_element", "") or "",
            "reaction": getattr(entity, "last_hit_reaction", "") or "",
        }
        residual = 0
        r_hp = (hp - prev_hp) - hp_net
        if getattr(entity, "fled", False):
            # 달아난 개체(고블린 겁쟁이)는 hp를 0으로 내려 전투에서 빼는 것이지 피해가 아니다 —
            # 숫자를 띄우지 않고 잔차로도 세지 않는다 (달아난 뒤에는 피해·회복 대상이 되지 않는다)
            r_hp = 0.0
        if abs(r_hp) >= 0.5:
            residual += 1
            kind = "heal" if r_hp > 0 else "damage"
            groups[kind].append({"kind": kind, "amount": abs(r_hp), **stamp})
        r_sh = (shield - prev_shield) - sh_net
        if abs(r_sh) >= 0.5:
            residual += 1
            kind = "shield" if r_sh > 0 else "damage"
            groups[kind].append({"kind": kind, "amount": abs(r_sh), **stamp})
        groups["residual"] = residual
        return groups

    def _hits_from_snapshot(self, before: dict) -> list:
        """이번 step의 피격 장부를 UI용 hit 이벤트로 합친다.

        집계 단위는 「대상 × 이벤트 종류」별 합계 1개다 — 같은 대상의 연타는
        숫자 하나로 합치고, 같은 step의 피해와 회복은 서로 지우지 않고 따로 낸다
        (예전 순변화량 방식은 출혈 16 + 흡혈 23.4가 heal 7 하나로 뭉개졌다).
          kind: damage(HP 피해 + 실드 흡수) / heal(회복) / shield(실드 획득)

        damage 이벤트의 태그 (프론트 팔레트는 BattleEffects.js의 _hitToneClass와 짝):
          element        : 마지막 타격의 원소
          reaction       : 이번 step에 이 대상에게 터진 마지막 반응
          reaction_count : {반응명: 횟수} — 연타 파쇄 ×3 같은 표기용
          via            : attack/skill/item/dot/passive
        """
        if not before:
            return []
        self._last_hit_residual = 0

        # 이번 step 동안 추가된 로그에서 크리티컬 여부 판정.
        #   로그에는 대상 슬롯 정보가 없어서, 피해를 입은 적이 1마리일 때만
        #   플레이어의 크리를 그 적에게 귀속시킨다(AoE 다중 대상은 미표시).
        new_logs = self.logs[before.get("log_len", 0):]
        player_crit = any(getattr(l, "actor", "") == "player" and getattr(l, "is_crit", False)
                          for l in new_logs)
        enemy_crit  = any(getattr(l, "actor", "") == "enemy" and getattr(l, "is_crit", False)
                          for l in new_logs)

        def via_from_logs(actor: str) -> str:
            """행동 종류(기본공격/스킬/아이템)는 엔진 타격 지점에서 알 수 없어서
            로그에서 유도한다. 크리 귀속과 같은 규칙 — player 로그는 적에게 준
            피해, enemy 로그는 플레이어가 받은 피해에 대응한다."""
            for l in reversed(new_logs):
                if getattr(l, "actor", "") != actor:
                    continue
                v = self._LOG_ACTION_TO_VIA.get(getattr(l, "action", ""))
                if v:
                    return v
            return ""

        # 적이 받은 피해는 플레이어 행동, 플레이어가 받은 피해는 적 행동에서 유도
        via_on_enemy  = via_from_logs("player")
        via_on_player = via_from_logs("enemy")

        def events(entity, prev, target, slot, via_fallback):
            g = self._ledger_groups(entity, prev)
            self._last_hit_residual += g["residual"]
            out = []
            dmg = g["damage"]
            total = sum(e["amount"] for e in dmg)
            if int(round(total)) > 0:
                last = dmg[-1]
                reactions = [e["reaction"] for e in dmg if e.get("reaction")]
                count: dict = {}
                for r in reactions:
                    count[r] = count.get(r, 0) + 1
                out.append({"target": target, "slot": slot,
                            "amount": int(round(total)), "kind": "damage",
                            "element":  last.get("element", ""),
                            "reaction": reactions[-1] if reactions else "",
                            "reaction_count": count,
                            # DoT·패시브는 기록 지점이 직접 남긴다 — 그 경우 로그 유도값보다 우선
                            "via": last.get("via", "") or via_fallback})
            for kind in ("heal", "shield"):
                amt = sum(e["amount"] for e in g[kind])
                if int(round(amt)) > 0:
                    vias = [e.get("via", "") for e in g[kind] if e.get("via")]
                    out.append({"target": target, "slot": slot,
                                "amount": int(round(amt)), "kind": kind,
                                "via": vias[-1] if vias else ""})
            return out

        hits = events(self.player, before["player"], "player", -1, via_on_player)
        for h in hits:
            if h["kind"] == "damage":
                h["crit"] = bool(enemy_crit)

        prev_enemies = before.get("enemies", [])
        enemy_hits = []
        for i, en in enumerate(self.enemies):
            if i >= len(prev_enemies):
                continue                      # 전투 중 새로 생긴 개체(분열/부활)
            enemy_hits.append(events(en, prev_enemies[i], "enemy", i, via_on_enemy))

        damaged = [e for group in enemy_hits for e in group if e["kind"] == "damage"]
        for e in damaged:
            e["crit"] = bool(player_crit) and len(damaged) == 1
        for group in enemy_hits:
            hits.extend(group)

        # 프론트가 키 존재 여부를 따지지 않아도 되게 전 이벤트에 기본값을 채운다
        # (heal/shield 이벤트는 색이 kind로 정해지므로 원소 태그가 비어 있다).
        for h in hits:
            h.setdefault("crit", False)
            h.setdefault("element", "")
            h.setdefault("reaction", "")
            h.setdefault("reaction_count", {})
            h.setdefault("via", "")
        return hits

    # ── 시전 이펙트 (action_fx) ─────────────────────────────────
    # 시전당 1개. 피격 숫자(hits)와 층을 나눈다 — 버프·디버프처럼 수치가 안 변하는
    # 행동도 이펙트를 내야 하고, 와이드 AoE는 대상이 셋이어도 한 장만 그려야 한다.
    _FX_SELF_STYPES = ("buff", "heal", "shield", "dice")

    def _note_fx_target(self, side: str, slot: int) -> None:
        """시전 대상을 행동 코드가 직접 알려준다 (표시 전용).
        스킬 메타만으로는 대상을 알 수 없는 경우에 쓴다 — 사제힐·사제축복은 메타상
        heal/buff(자기 대상)지만 실제로는 다른 적에게 걸고, 축복은 HP가 안 변해서
        장부로도 못 잡는다. 여기 남긴 대상이 있으면 추정 대상보다 우선한다."""
        noted = getattr(self, "_fx_noted_targets", None)
        if noted is None:
            return
        t = {"side": side, "slot": slot}
        if t not in noted:
            noted.append(t)

    def _note_fx(self, name: str, stype: str, kind: str = "skill") -> None:
        """TurnLog를 남기지 않는 행동(엘리트 사제 부활 의식)의 시전 정보를 남긴다."""
        if hasattr(self, "_fx_override"):
            self._fx_override = {"kind": kind, "name": name, "stype": stype}

    def _action_fx(self, before: dict):
        """이번 step에서 행동한 쪽의 시전 정보. 행동이 없었으면(상태 조회, 마비 실패) None."""
        from ai.battle import SKILL_META, MONSTER_SKILL_META, ITEM_META
        if not before or not before.get("actor"):
            return None
        actor, aidx = before["actor"], before.get("actor_idx", -1)
        new_logs = self.logs[before.get("log_len", 0):]
        log = next((l for l in new_logs
                    if getattr(l, "actor", "") == actor
                    and getattr(l, "action", "") != "counter"), None)
        override = getattr(self, "_fx_override", None)
        noted    = list(getattr(self, "_fx_noted_targets", None) or [])
        if log is None and override is None:
            return None
        if override is not None:
            return {"actor": actor, "actor_slot": aidx if actor == "enemy" else -1,
                    "kind": override["kind"], "name": override["name"],
                    "stype": override["stype"], "scope": "single",
                    "element": "", "targets": noted}

        kind   = log.action
        detail = (log.action_detail or "")
        name   = detail.split("(", 1)[0]          # '난사1(aoe)' / '강타1(mp_lack)' → 스킬명
        stype, element, scope = "", "", "single"
        if kind in ("skill", "skill_failed"):
            meta = ((MONSTER_SKILL_META.get(name) if actor == "enemy" else None)
                    or SKILL_META.get(name) or {})
            stype   = meta.get("type", "")
            element = meta.get("element", "")
            if meta.get("aoe") or detail.endswith("(aoe)"):
                scope = "aoe"
            elif stype in self._FX_SELF_STYPES:
                scope = "self"
        elif kind == "item":
            meta  = ITEM_META.get(name, {})
            stype = meta.get("category", "")
            element = meta.get("element", "")
            if stype == "aoe_damage":
                scope = "aoe"
            elif stype not in ("element",):
                scope = "self"
        elif kind == "attack":
            stype = "physical"
            if actor == "enemy" and 0 <= aidx < len(self.enemies):
                element = getattr(self.enemies[aidx], "attack_element", "") or ""
        elif kind in ("watch", "escape", "escape_blocked"):
            scope = "self"

        # ── 대상: 시전 시점의 의도 대상 ∪ 이번 행동으로 수치가 변한 대상 ──
        alive = before.get("alive", [])
        targets: list = []

        def add(side, slot):
            t = {"side": side, "slot": slot}
            if t not in targets:
                targets.append(t)

        if noted and kind not in ("skill_failed", "item_failed"):
            # 행동이 대상을 직접 알려준 경우 — 자기 대상 스킬 메타라도 실제로는 남에게 건 것
            if scope == "self":
                scope = "single"
            targets.extend(noted)
        elif kind not in ("skill_failed", "item_failed"):
            if scope == "self":
                add(actor, aidx if actor == "enemy" else -1)
            elif actor == "player":
                if scope == "aoe":
                    for i, a in enumerate(alive):
                        if a:
                            add("enemy", i)
                else:
                    ti = before.get("target_idx", 0)
                    if 0 <= ti < len(alive):
                        add("enemy", ti)
            else:
                add("player", -1)

            # 실제로 수치가 변한 대상 — DoT/패시브는 행동의 결과가 아니므로 제외,
            # 행동자 자신의 흡혈 같은 부수 회복도 대상이 아니다(scope=self는 위에서 이미 포함)
            def touched(ent):
                return any(not e.get("via") for e in (getattr(ent, "hit_ledger", None) or []))
            if actor != "player" and touched(self.player):
                add("player", -1)
            for i, en in enumerate(self.enemies):
                if actor == "enemy" and i == aidx:
                    continue
                if touched(en):
                    add("enemy", i)

        return {
            "actor":      actor,
            "actor_slot": aidx if actor == "enemy" else -1,
            "kind":       kind,
            "name":       name,
            "stype":      stype,
            "scope":      scope,
            "element":    element,
            "targets":    targets,
        }

    def _close_hit_ledgers(self) -> None:
        """step이 끝나면 장부를 끈다 — 다음 step 전까지는 아무 것도 기록하지 않는다."""
        for ent in [self.player] + list(self.enemies):
            ent.hit_ledger = None

    def _live_inventory_dict(self) -> dict:
        """전투 중 self.items(원본 평탄 리스트 — 문자열)로부터 구조화 인벤토리
        breakdown을 만들어 반환 — app/Shared.py._player_dict()의 비-Inventory
        폴백과 동일한 패턴(분류 로직 재구현 없음). gs["inventory"] 자체는
        건드리지 않는다.
        ★ get_items()는 UI 아이템 메뉴용으로 이미 {name,count} dict 리스트로
          집계돼 있어서 여기선 쓸 수 없다 — 원본 문자열 리스트인 self.items를
          직접 써야 한다."""
        tmp = Inventory.new()
        for item_name in self.items:
            tmp.add(item_name)
        return tmp.to_response_dict()

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
        battle_meta = getattr(self, "battle_meta", {}) or {}

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
                "fled":             bool(getattr(en, "fled", False)),   # 달아난 개체 — 죽은 것과 다르게 그린다
                "hp":               max(0.0, round(en.hp, 1)),
                "maxhp":            round(en.maxhp, 1),
                "mp":               round(en.mp, 1),
                "maxmp":            round(en.maxmp, 1),
                "shield":           round(getattr(en, "shield", 0.0), 1),
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
                # ── 패턴 배지 (표시 전용 파생값 — _pattern_badges 주석 참고) ──
                "pattern":          self._pattern_badges(
                    en, getattr(self, "_player_action_count", 0),
                    relic_telegraph_lead(getattr(self.player, "relics", []))),
            })

        return {
            "turn":       self.turn,
            "is_boss":    self.is_boss,   # UI: 보스전이면 도망 버튼 숨김
            "chapter":    battle_meta.get("chapter", 1),
            "current_layer": battle_meta.get("current_layer", 0),
            "node_type":  battle_meta.get("node_type", "battle"),
            "player_hp":  round(self.player.hp, 1),
            "player_mp":  round(self.player.mp, 1),
            "player_shield": round(getattr(self.player, "shield", 0.0), 1),
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
            # 도적 「패 고치기」 — 저장된 다음 주사위와 남은 재굴림 횟수 (표시 전용). 도적이 아니면 None
            "player_dice": (
                {"pending": self.player.pending_dice,
                 "rerolls_left": max(0, SKILL_META.get("패 고치기", {}).get("max_uses", 0) - self.player.dice_fix_uses),
                 "free_rerolls": self.player.free_rerolls}
                if getattr(self.player, "job", "") == "도적" and "패 고치기" in self.player.learned_skills else None),
            # 마법사 원소 공명 단계 (표시 전용 — Elements.mage_resonance_*). 마법사가 아니면 None
            "player_resonance": (
                {"element": self.player.resonance_element, "stack": self.player.resonance_stack,
                 "max": relic_resonance_max(self.player, _RESONANCE_MAX)}   # 유물 「공명의 수정」
                if getattr(self.player, "job", "") == "마법사" and self.player.resonance_stack > 0 else None),
            "player_element_aura":   player_element_aura,
            "player_status_effects": player_status_effects,
            "enemy_element_aura":    enemy_element_aura,
            "enemy_status_effects":  enemy_status_effects,
            # ── 1대1 호환 (단수) — 기존 UI는 이 필드들 사용 ──
            "enemy_hp":   max(0.0, round(e.hp, 1)),
            "enemy_maxhp": e.maxhp,
            "enemy_name": e.name,
            "enemy_shield": round(getattr(e, "shield", 0.0), 1),
            "enemy_info": {
                "name":             e.name,
                "lv":               e.lv,
                "difficulty":       diff_raw,
                "difficulty_label": self._DIFF_LABEL.get(diff_raw, diff_raw),
                "hp":               max(0.0, round(e.hp, 1)),
                "maxhp":            round(e.maxhp, 1),
                "shield":           round(getattr(e, "shield", 0.0), 1),
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
            # ★ 전투 중 아이템 팝업(플레이어 패널)이 state.player.items(평탄
            #   리스트)만 보고 있어서 state.player.inventory(구조화 필드)와
            #   실시간으로 어긋나던 버그 — 여기서도 매 응답마다 구조화 breakdown을
            #   함께 실어보낸다. app/Shared.py의 _player_dict()가 이미 쓰는
            #   "평탄 리스트 → Inventory.new()+add() 반복" 폴백과 동일한 패턴이라
            #   새 분류 로직을 만들지 않는다. gs["inventory"](Inventory 객체)
            #   자체는 여전히 전투 중엔 안 건드림 — 최종 반영은 전투 종료 시
            #   app/Battle.py._finish_battle()이 한 번에 처리(기존 그대로).
            "inventory":  self._live_inventory_dict(),
            "skills":     self.get_skills(),
            "done":       self.done,
            "winner":     self.winner,
            "messages":   messages or [],
            # ★ 데미지 숫자 팝업용 — 실제 값은 step()이 채운다(스냅샷 차분이라
            #   _step_core 내부에서는 아직 알 수 없음). 여기서 빈 리스트로 키를
            #   항상 만들어 두면 프론트가 존재 여부를 따지지 않아도 된다.
            "hits":       [],
            # ★ A1 응답 분리 — 다음 행동자 정보
            "next_actor":         next_actor,
            "acting_enemy_idx":   acting_enemy_idx,
        }
