# -*- coding: utf-8 -*-
"""montecarlo.py — 직업×레벨×전투타입 승률표 (BattleSession 실전 시뮬)"""
import sys, io, os, json, time, contextlib
from random import choice, seed
from collections import Counter, defaultdict

sys.path.insert(0, '.')
from ai.Battlesession import BattleSession
from ai.Auto_AI import PlayerAI
from ai.battle import EntitySnapshot
from game.Player_Class import create_player_by_job
from game.Enemy_Class import (Make_Goblin, Make_Bat, Make_Slime, Make_FireSlime,
                              Make_IceSlime, Make_LightningSlime, Make_Golem,
                              Make_Assassin, Make_Priest, Make_MidBoss, Make_FinalBoss)
from game.Lv import LV_, Allocate_Stat_Points

# ── 실게임 상수 (app/Map.py와 동일) ──
FACTORY = {"고블린": Make_Goblin, "박쥐": Make_Bat, "슬라임": Make_Slime,
           "화염 슬라임": Make_FireSlime, "빙결 슬라임": Make_IceSlime,
           "번개 슬라임": Make_LightningSlime, "골렘": Make_Golem,
           "암살자": Make_Assassin, "사제": Make_Priest}
CH1 = ["고블린", "박쥐", "슬라임", "화염 슬라임", "빙결 슬라임", "번개 슬라임"]
CH2 = CH1 + ["사제", "암살자", "골렘"]
NORMAL_POOL = [("하", 0.35), ("중", 0.45), ("상", 0.20)]
NORMAL_3    = [("하", 0.45), ("중", 0.55)]
MAIN_STAT = {"전사": "stg", "마법사": "sp", "탱커": "arm", "도적": "stg"}

def pick_grade(pool):
    import random
    r = random.random(); acc = 0
    for g, w in pool:
        acc += w
        if r <= acc: return g
    return pool[-1][0]

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
    _PLAYER_CACHE[key] = p
    return p

def player_snap(p, items):
    return EntitySnapshot(
        name="SIM", hp=p.maxhp, maxhp=p.maxhp, mp=p.maxmp, maxmp=p.maxmp,
        stg=p.stg, arm=p.arm, sparm=p.sparm, sp=p.sp, luc=p.luc, lv=p.lv,
        spd=getattr(p, "spd", 10.0),
        learned_skills=list(getattr(p, "learned_skills", []) or []),
        items=list(items), job=p.job)

def make_enemy(name, plv, grade):
    u = FACTORY[name](player_lv=plv, grade=grade)
    s = EntitySnapshot.from_enemy(u)
    s.difficulty = {"하": "easy", "중": "normal", "상": "hard"}[grade]
    return s, u

def build_battle(btype, plv):
    ch = CH1 if plv < 8 else CH2
    if btype == "mid_boss":
        u = Make_MidBoss(player_lv=plv)
        return [EntitySnapshot.from_enemy(u)], [u], True
    if btype == "final_boss":
        u = Make_FinalBoss(player_lv=plv)
        return [EntitySnapshot.from_enemy(u)], [u], True
    if btype == "elite":
        n = choice([1, 2])
        pairs = [make_enemy(choice(ch), plv, "상") for _ in range(n)]
    elif btype == "1v1":
        pairs = [make_enemy(choice(ch), plv, pick_grade(NORMAL_POOL))]
    elif btype == "1v2":
        pairs = [make_enemy(choice(ch), plv, pick_grade(NORMAL_POOL)) for _ in range(2)]
    else:  # 1v3
        pairs = [make_enemy(choice(ch), plv, pick_grade(NORMAL_3)) for _ in range(3)]
    return [p[0] for p in pairs], [p[1] for p in pairs], False

def start_items(level):
    if level <= 5:  return ["HP_S_potion", "HP_S_potion", "MP_S_potion"]
    if level <= 15: return ["HP_M_potion", "HP_M_potion", "MP_M_potion"]
    return ["HP_L_potion", "HP_M_potion", "MP_L_potion", "MP_M_potion"]

def run_one(job, level, btype, stats):
    p = build_player(job, level)
    esnaps, origins, is_boss = build_battle(btype, level)
    bs = BattleSession(player_snap(p, start_items(level)),
                       enemies=esnaps, enemy_origins=origins, is_boss=is_boss)
    ai = PlayerAI()
    msgs_all = []
    guard = 0
    while not bs.done and guard < 400:
        na, _ = bs._peek_next_actor()
        if na == "player":
            tgt = bs._current_target() or bs.enemy
            alive = sum(1 for e in bs.enemies if e.hp > 0)
            a = ai.decide(bs.player, tgt, enemy_count=alive)
            if a.action_type == "skill":
                stats[f"sk_{a.detail}"] += 1   # 스킬별 선택 횟수 (슬래시1 추적용)
            s = {"attack": "attack", "skill": f"skill:{a.detail}",
                 "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            r = bs.step(s)
        else:
            r = bs.step("auto")
        msgs_all.extend(r.get("messages", []))
        guard += 1

    win = bs.winner == "player"
    stats["n"] += 1
    stats["win"] += win
    stats["turns"] += bs.turn
    stats["hp_ratio"] += max(0, bs.player.hp) / bs.player.maxhp
    stats["items_used"] += bs.items_used
    stats["skills_used"] += bs.skills_used
    stats["actions"] += bs.skills_used + bs.items_used  # 근사

    for m in msgs_all:
        if "🎲 주사위:" in m:
            d = int(m.split("주사위:")[1].strip().rstrip("!"))
            stats[f"dice_{d}"] += 1
        if "[도적 반격]" in m: stats["counter"] += 1
        if "출혈 -" in m:
            try: stats["bleed_dmg"] += int(m.split("출혈 -")[1].split()[0]); stats["bleed_ticks"] += 1
            except Exception: pass
        if "🩸" in m and "출혈!" in m: stats["bleed_apply"] += 1
        if "융해" in m and "발동" in m: stats["melt"] += 1
        if "과부하" in m and "발동" in m: stats["overload"] += 1
        if "파쇄" in m and "발동" in m: stats["shatter"] += 1
        if "[전사 패시브]" in m: stats["warrior_heal"] += 1
        if "[탱커 패시브]" in m: stats["tanker_proc"] += 1
        if "[마법사 패시브]" in m: stats["mage_mp"] += 1

    # 되갚기 피해 (TurnLog)
    for lg in bs.logs:
        if lg.actor == "player" and lg.action == "skill" and "되갚기" in (lg.action_detail or ""):
            stats["gg_dmg"] += lg.damage_dealt; stats["gg_n"] += 1

def main():
    seed(20260706)
    JOBS = ["전사", "마법사", "탱커", "도적"]
    LEVELS = [1, 5, 10, 15, 20, 25]
    TYPES = ["1v1", "1v2", "1v3", "elite", "mid_boss", "final_boss"]
    N = int(os.environ.get("N", "120"))

    results = {}
    t0 = time.time()
    for job in JOBS:
        for lvl in LEVELS:
            for bt in TYPES:
                st = defaultdict(float)
                for _ in range(N):
                    try:
                        run_one(job, lvl, bt, st)
                    except Exception as ex:
                        st["errors"] += 1
                results[f"{job}|{lvl}|{bt}"] = dict(st)
        print(f"[{time.time()-t0:6.1f}s] {job} 완료", file=sys.stderr)
    with open("mc_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False)
    print("DONE", time.time() - t0, "s", file=sys.stderr)

if __name__ == "__main__":
    main()