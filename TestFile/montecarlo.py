# -*- coding: utf-8 -*-
"""montecarlo.py — 직업×레벨×전투타입 승률표 (BattleSession 실전 시뮬)

밸런스 3차(BALANCE_PATCH_3)에서 몬스터 생성 경로를 core/Balance_Hook.py의
실전 파이프라인(hook.get_enemy())으로 교체했다 — 예전엔 game/Enemy_Class.py의
등급(하/중/상) 팩토리를 직접 호출해 BalanceHook의 자동 파워인덱스 튜닝
레이어를 완전히 건너뛰었다. 몬스터 타입/등급 선택, 다대일 배율 적용은
app/Map.py의 실제 라우트 함수(_make_enemies, _make_elite_encounter)를 그대로
재사용한다 — 별도로 베낀 로직이 실전과 갈라질 위험을 없애기 위함.

(BALANCE_PATCH_3에서 1v2/1v3을 hook.get_encounter() 그룹 튜닝으로 연결하는
시도도 했지만, 이진탐색이 승률-배율 곡선이 가파른 조합에서 재현 불가능한
값에 수렴하는 문제가 확인돼 app/Map.py 쪽 연결은 철회했다 — 이 스크립트는
항상 최신 app/Map.py를 그대로 재사용하므로 특별한 스위치 없이 자동으로
개별 튜닝 경로만 탄다. 자세한 내용은 BALANCE_PATCH_3.md 참고.)
"""
import sys, io, os, json, time, contextlib, re
from random import choice, seed
from collections import defaultdict

sys.path.insert(0, '.')
from ai.Battlesession import BattleSession
from ai.Auto_AI import PlayerAI
from ai.battle import EntitySnapshot
from core.Balance_Hook import BalanceHook
from game.Player_Class import create_player_by_job
from game.Map import NORMAL_LAYERS
from game.Enemy_Class import Make_MidBoss, Make_FinalBoss
from game.Lv import LV_, Allocate_Stat_Points
try:
    from game.Lv import auto_resolve_skill_choices      # 2차 8번 이후 트리
except ImportError:                                      # 2택 1이 없던 트리에 대고 돌릴 때
    auto_resolve_skill_choices = None
import random as _random_mod
from app.Map import (
    _make_enemies, _make_elite_encounter,
    _apply_stat_scale, _multi_stat_scale,
    NORMAL_GRADE_POOL, NORMAL_GRADE_3,
)

MAIN_STAT = {"전사": "stg", "마법사": "sp", "탱커": "arm", "도적": "stg"}

# 플레이어 AI 모드 — 기본 balanced(튜닝 기준). Combat Content Brief 11-1은 패턴·역할 변화를
# 잴 때 측정용 reactive와 나란히 보라고 하므로 AI_MODE=reactive로 같은 스윕을 한 번 더 돈다.
AI_MODE = os.environ.get("AI_MODE", "balanced")
# 스킬 2택 1 정책 — new(신규 스킬) / old(기존 스킬) / random
SKILL_PICK = os.environ.get("SKILL_PICK", "new")
# 포션을 세션에도 넘길지 — 1(기본): 실제 게임(app/Battle.py _start_battle)처럼 BattleSession(items=…)에 넘기고
#   매 step AI 스냅샷(player.items)을 세션 목록과 맞춘다.
# 0: 2026-09-17 이전 방식 — 포션이 스냅샷에만 있어 AI가 고르면 세션이 "해당 아이템이 없습니다"로
#   차례를 버린다(HP가 낮을 때마다 반복). Combat Content Brief 2차 시리즈(3~8번) 스윕은 이 방식으로 쟀다 —
#   그 결과를 재현할 때만 SESSION_ITEMS=0.
SESSION_ITEMS = os.environ.get("SESSION_ITEMS", "1") == "1"


def pick_target(bs):
    """대상 인덱스 — 기본은 세션의 현재 대상(살아있는 첫 적). 최종 보스전에서 그림자가 살아 있으면
    HP가 가장 낮은 그림자를 먼저 친다(보스 경감 −25%를 풀어야 하는 페이즈 — 단일 대상 직업도 이렇게 한다)."""
    shadows = [(e.hp, i) for i, e in enumerate(bs.enemies) if e.hp > 0 and e.enemy_type == "심연의 그림자"]
    if bs.is_boss and shadows:
        return min(shadows)[1]
    return None

# 2차 콘텐츠 발동 카운터 — 메시지 부분 문자열로 센다 (없는 판에서는 0으로 남는다).
_BLEED_TICK = re.compile(r"출혈(?: ×\d+)? -(\d+)")
_DICE_MSG = re.compile(r"🎲 주사위: (\d)!")

MESSAGE_KEYWORDS = {
    "goblin_pack":    "무리 전술",          # 고블린 무리 전술 발동/갱신
    "goblin_flee":    "달아났다",           # 겁쟁이 도주 성공
    "goblin_flee_f":  "도주에 실패",        # 겁쟁이 도주 실패
    "bat_wing":       "날갯소리",           # 박쥐 날갯소리(ATB 감소)
    "bat_drain":      "피해를 흡수해",       # 박쥐 흡혈(일반·엘리트)
    "priest_revive":  "되살아났다",         # 사제 소생(약식·의식)
    "execute":        "처형",               # 강타 처형
    "resonance":      "공명",               # 마법사 원소 공명
    "bleed_vital":    "출혈 급소",          # 급소찌르기 출혈 보너스
    "lifesteal":      "🩸 흡혈 +",          # 플레이어 흡혈 회복
}

_PLAYER_CACHE = {}
def build_player(job, level):
    key = (job, level)
    if key in _PLAYER_CACHE:
        return _PLAYER_CACHE[key]
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("SIM", job)
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        pts = getattr(p, "pending_points", 0)
        if pts > 0:
            Allocate_Stat_Points(p, {MAIN_STAT[job]: pts})
        # 스킬 2택 1(2차 8번) — 시뮬은 SKILL_PICK 정책으로 확정 (random은 (직업,레벨)마다 고정 시드)
        if auto_resolve_skill_choices is not None:
            auto_resolve_skill_choices(p, SKILL_PICK, rng=_random_mod.Random(f"{job}|{level}"))
    _PLAYER_CACHE[key] = p
    return p

# (job, level)당 BalanceHook 하나만 만들어 재사용 — 실전도 레벨업 전까진
# 같은 hook/캐시를 계속 쓰므로 동일 전제. 새로 만들 때마다 튜닝을 처음부터
# 다시 돌리면 시간이 (job×level) 배로 불어난다.
_HOOK_CACHE = {}
def get_hook(job, level):
    key = (job, level)
    if key in _HOOK_CACHE:
        return _HOOK_CACHE[key]
    p = build_player(job, level)
    hook = BalanceHook(p, start_items(level), show_graph=False, verbose=False,
                        auto_prewarm=False)
    _HOOK_CACHE[key] = hook
    return hook

def player_snap(p, items):
    return EntitySnapshot(
        name="SIM", hp=p.maxhp, maxhp=p.maxhp, mp=p.maxmp, maxmp=p.maxmp,
        stg=p.stg, arm=p.arm, sparm=p.sparm, sp=p.sp, luc=p.luc, lv=p.lv,
        spd=getattr(p, "spd", 10.0),
        learned_skills=list(getattr(p, "learned_skills", []) or []),
        items=list(items), job=p.job)

def build_battle(btype, plv, job):
    """app/Map.py의 실제 라우트 로직을 그대로 재사용 — 몬스터 생성/
    다대일 배율 적용까지 실전과 100% 동일하게 결정된다."""
    chapter = 1 if plv < 8 else 2
    layer   = choice(range(1, NORMAL_LAYERS + 1))
    hook    = get_hook(job, plv)

    if btype == "mid_boss":
        u = Make_MidBoss(player_lv=plv)
        return [EntitySnapshot.from_enemy(u)], [u], True
    if btype == "final_boss":
        u = Make_FinalBoss(player_lv=plv)
        return [EntitySnapshot.from_enemy(u)], [u], True

    if btype == "elite":
        # 배율은 _make_elite_encounter()가 안에서 적용한다(여기서 또 곱하면 두 번 걸린다).
        # ★ 예전엔 이 줄이 엘리트 할인만 곱하고 저레벨 완화를 빼먹어서,
        #   스윕이 재는 저레벨 엘리트가 실전보다 20% 셌다.
        units, _grades = _make_elite_encounter(hook, chapter, layer=layer, player_lv=plv)
        esnaps = [EntitySnapshot.from_enemy(u) for u in units]
        return esnaps, units, False

    n = {"1v1": 1, "1v2": 2, "1v3": 3}[btype]
    grade_pool = NORMAL_GRADE_3 if n == 3 else NORMAL_GRADE_POOL
    units, _grades = _make_enemies(hook, n, grade_pool, chapter, layer=layer)
    if n > 1:
        # 일반 다대일은 app/Map.py와 같은 규칙 — 튜너 우회 + 가산 배율.
        # (예전엔 할인 표 STAT_SCALE[n] × 저레벨 완화였다 — 둘 다 12차에 삭제.)
        _apply_stat_scale(units, _multi_stat_scale(plv, n))
    esnaps = [EntitySnapshot.from_enemy(u) for u in units]
    return esnaps, units, False

def start_items(level):
    if level <= 5:  return ["HP_S_potion", "HP_S_potion", "MP_S_potion"]
    if level <= 15: return ["HP_M_potion", "HP_M_potion", "MP_M_potion"]
    return ["HP_L_potion", "HP_M_potion", "MP_L_potion", "MP_M_potion"]

def run_one(job, level, btype, stats):
    p = build_player(job, level)
    esnaps, origins, is_boss = build_battle(btype, level, job)
    bs = BattleSession(player_snap(p, start_items(level)),
                       enemies=esnaps, enemy_origins=origins, is_boss=is_boss,
                       items=start_items(level) if SESSION_ITEMS else None)
    bs.battle_meta = {"source": "ai", "battle_type": btype}
    ai = PlayerAI(AI_MODE)
    msgs_all = []
    guard = 0
    while not bs.done and guard < 400:
        na, _ = bs._peek_next_actor()
        if na == "player":
            ti = pick_target(bs)
            tgt = bs.enemies[ti] if ti is not None else (bs._current_target() or bs.enemy)
            alive = sum(1 for e in bs.enemies if e.hp > 0)
            a = ai.decide(bs.player, tgt, enemy_count=alive)
            if a.action_type == "skill":
                stats[f"sk_{a.detail}"] += 1   # 스킬별 선택 횟수 (슬래시1 추적용)
            s = {"attack": "attack", "skill": f"skill:{a.detail}",
                 "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            if ti is not None and a.action_type in ("attack", "skill"):
                s = f"attack:{ti}" if a.action_type == "attack" else f"{s}:{ti}"
            r = bs.step(s)
            if SESSION_ITEMS:
                bs.player.items = list(bs.items)    # 쓴 포션을 AI 스냅샷에서도 지운다
        else:
            r = bs.step("auto")
        msgs_all.extend(r.get("messages", []))
        guard += 1

    # 멀티히트 재타겟 발생률 (RL 로그 기준)
    for rec in getattr(bs, "rl_log", []):
        mh = rec.get("result", {}).get("multi_hit")
        if mh:
            stats["mh_uses"] += 1
            if mh.get("retargeted"):
                stats["mh_retargeted"] += 1

    win = bs.winner == "player"
    stats["n"] += 1
    stats["win"] += win
    stats["turns"] += bs.turn
    stats["hp_ratio"] += max(0, bs.player.hp) / bs.player.maxhp
    stats["items_used"] += bs.items_used
    stats["skills_used"] += bs.skills_used
    stats["actions"] += bs.skills_used + bs.items_used  # 근사

    for m in msgs_all:
        if "🛡 다대일 대응!" in m:
            stats["multi_shield_procs"] += 1
        _dm = _DICE_MSG.match(m)                # "🎲 주사위: 4!" / "… 4! (미리 본 눈)" (2차 6번)
        if _dm:
            stats[f"dice_{_dm.group(1)}"] += 1
        if "[도적 반격]" in m: stats["counter"] += 1
        _bl = _BLEED_TICK.search(m)          # "출혈 -N" / "출혈 ×2 -N" (2차 5번 스택 표기)
        if _bl:
            stats["bleed_dmg"] += int(_bl.group(1)); stats["bleed_ticks"] += 1
        if "🩸" in m and "출혈!" in m: stats["bleed_apply"] += 1
        if "융해" in m and "발동" in m: stats["melt"] += 1
        if "과부하" in m and "발동" in m: stats["overload"] += 1
        if "파쇄" in m and "발동" in m: stats["shatter"] += 1
        if "[전사 패시브]" in m: stats["warrior_heal"] += 1
        if "[탱커 패시브]" in m: stats["tanker_proc"] += 1
        if "[마법사 패시브]" in m: stats["mage_mp"] += 1
        for key, kw in MESSAGE_KEYWORDS.items():
            if kw in m: stats[key] += 1

    # 되갚기 피해 (TurnLog)
    for lg in bs.logs:
        if lg.actor == "player" and lg.action == "skill" and "되갚기" in (lg.action_detail or ""):
            stats["gg_dmg"] += lg.damage_dealt; stats["gg_n"] += 1

def main():
    seed(20260706)
    ALL_JOBS   = ["전사", "마법사", "탱커", "도적"]
    ALL_LEVELS = [1, 5, 10, 15, 20, 25]
    TYPES = ["1v1", "1v2", "1v3", "elite", "mid_boss", "final_boss"]
    N = int(os.environ.get("N", "120"))
    OUT = os.environ.get("OUT", "mc_results.json")
    # 파일럿(소요시간 실측)용 — 셀 수를 좁히고 싶을 때 JOBS/LEVELS env로 제한
    JOBS   = os.environ.get("JOBS", ",".join(ALL_JOBS)).split(",")
    LEVELS = [int(x) for x in os.environ.get("LEVELS", ",".join(map(str, ALL_LEVELS))).split(",")]
    SHOW_ERRORS = os.environ.get("SHOW_ERRORS", "0") == "1"

    results = {}
    t0 = time.time()
    for job in JOBS:
        for lvl in LEVELS:
            for bt in TYPES:
                st = defaultdict(float)
                for _ in range(N):
                    try:
                        run_one(job, lvl, bt, st)
                    except Exception as e:
                        st["errors"] += 1
                        if SHOW_ERRORS:
                            import traceback; traceback.print_exc()
                results[f"{job}|{lvl}|{bt}"] = dict(st)
        print(f"[{time.time()-t0:6.1f}s] {job} 완료", file=sys.stderr)
    with open(OUT, "w") as f:
        json.dump(results, f, ensure_ascii=False)
    print("DONE", time.time() - t0, "s ->", OUT, file=sys.stderr)

if __name__ == "__main__":
    main()