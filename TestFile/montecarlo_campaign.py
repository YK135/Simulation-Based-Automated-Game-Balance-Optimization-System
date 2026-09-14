# -*- coding: utf-8 -*-
"""
montecarlo_campaign.py — cross-battle ATB 이월 단독 효과 측정 (BALANCE_PATCH_3)
─────────────────────────────────────────────
montecarlo.py의 메인 스윕은 매 시행이 독립된 1회성 전투라 "전투 간 ATB
이월" 효과 자체는 설계상 측정되지 않는다(각 시행이 서로 다른 표본이어야
하므로 — BALANCE_PATCH_3.md 참고). 이 스크립트는 실전 그대로
(app/Battle.py._start_battle()와 동일하게 BattleSession(...,
player_original=player)를 매 전투마다 사용) 여러 전투를 연속으로 이어 붙인
"캠페인"을 시뮬레이션해서 이월 있음(carryover=True) vs 없음(강제로 매
전투 시작 전 atb_remainder=0으로 리셋) 두 조건을 같은 시드로 비교한다.

측정 대상: 캠페인당 평균 승리 전투 수(생존력), 평균 총 턴 수,
"이월 덕분에 첫 행동에서 즉시 보너스 행동권을 얻은 비율"(직업별 SPD 차이
— 특히 도적의 고SPD 복리효과 — 를 직접 드러내는 지표).

단순화 (둘 다 명시):
  1) 캠페인 내 각 전투는 1v1만 사용한다(그룹 튜닝/다대일 검증은
     montecarlo.py의 메인 스윕이 이미 담당 — 여기는 ATB 이월 메커니즘
     자체만 격리해서 본다. 이월 메커니즘은 1v1이든 1vN이든 "전투 시작
     ATB" 하나에만 관여하므로 1v1로 좁혀도 효과 측정에는 지장이 없다).
  2) 전투 사이에 HP/MP/아이템을 전혀 이월하지 않는다 — 매 전투 시작마다
     player_snap()이 maxhp/maxmp로 다시 채운다. 실전은 노드맵을 걷는 동안
     회복 없이 누적 피해를 받는(휴식 노드에서만 회복) "소모전"에 가깝지만,
     여기서는 ATB 이월 하나만 격리해서 보려고 일부러 HP/MP를 전투마다
     리셋했다 — 그래서 이 스크립트의 "생존 전투 수"는 실제 캠페인의 절대
     생존력이 아니라 "ATB 이월 유무만 다른 두 조건의 상대 비교"로만
     해석해야 한다. carryover=True/False 둘 다 같은 단순화를 받으므로
     비교 자체는 공정하다.
  3) 각 (job, LEVEL) 블록 시작 시 seed()를 다시 걸어 carryover=True/False가
     최대한 같은 초기 조건(같은 몬스터 롤 시퀀스 시작점)에서 갈라지게
     했다 — 완벽한 paired comparison은 아니다(전투 1회의 실제 진행 턴 수가
     조건마다 달라지면 그 이후 소비되는 난수 위치도 갈라짐), 하지만 적어도
     "이월 조건이 나중에 실행돼서 이월 없음 조건이 이미 소비한 난수를
     이어받는" 이전 버전의 편향은 제거했다.

실행: python3 TestFile/montecarlo_campaign.py
환경변수: N(캠페인 반복수, 기본 300), BATTLES(캠페인당 전투수, 기본 6),
          LEVEL(고정 레벨, 기본 10)
"""
import sys, io, os, json, contextlib
sys.path.insert(0, '.')
from random import seed, choice

from ai.Battlesession import BattleSession
from ai.Auto_AI import PlayerAI
from ai.battle import EntitySnapshot
from core.Balance_Hook import BalanceHook
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points

JOBS = ["전사", "마법사", "탱커", "도적"]
MAIN_STAT = {"전사": "stg", "마법사": "sp", "탱커": "arm", "도적": "stg"}


def build_player(job, level):
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("CAMPAIGN", job)
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        pts = getattr(p, "pending_points", 0)
        if pts > 0:
            Allocate_Stat_Points(p, {MAIN_STAT[job]: pts})
    p.atb_remainder = 0.0
    return p


def start_items(level):
    if level <= 5:  return ["HP_S_potion", "HP_S_potion", "MP_S_potion"]
    if level <= 15: return ["HP_M_potion", "HP_M_potion", "MP_M_potion"]
    return ["HP_L_potion", "HP_M_potion", "MP_L_potion", "MP_M_potion"]


def player_snap(p, items):
    return EntitySnapshot(
        name="CAMPAIGN", hp=p.maxhp, maxhp=p.maxhp, mp=p.maxmp, maxmp=p.maxmp,
        stg=p.stg, arm=p.arm, sparm=p.sparm, sp=p.sp, luc=p.luc, lv=p.lv,
        spd=getattr(p, "spd", 10.0),
        learned_skills=list(getattr(p, "learned_skills", []) or []),
        items=list(items), job=p.job)


def run_one_battle(p, hook, level, ai):
    """1v1 전투 1회 — app/Battle.py._start_battle()와 동일 패턴
    (player_original=p → 실전 그대로 ATB 이월). 반환: (win, turns)."""
    chapter = 1 if level < 8 else 2
    diff = choice(["easy", "normal", "hard"])
    pool = ["고블린", "박쥐", "슬라임"] if chapter == 1 else ["박쥐", "화염 슬라임", "사제", "암살자"]
    enemy_type = choice(pool)
    snap = hook.get_enemy(enemy_type, difficulty=diff, chapter=chapter)
    origin = hook.make_battle_unit(snap)

    items = start_items(level)
    bs = BattleSession(player_snap(p, items), enemy=snap, items=items,
                       enemy_origins=[origin], is_boss=False, player_original=p)

    guard = 0
    while not bs.done and guard < 200:
        na, _ = bs._peek_next_actor()
        if na == "player":
            a = ai.decide(bs.player, bs.enemy, enemy_count=1)
            s = {"attack": "attack", "skill": f"skill:{a.detail}",
                 "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            bs.step(s)
        else:
            bs.step("auto")
        guard += 1

    return bs.winner == "player", bs.turn


def run_campaign(job, level, n_battles, carryover, ai, hook):
    """캠페인 1회 — 패배 시 즉시 종료(실전과 동일: 죽으면 런 끝).
    hook은 호출부가 (job, level)당 하나만 만들어 재사용한다 — 캠페인마다
    새로 만들면 매번 몬스터 튜닝을 처음부터 다시 돌려야 해서(N=300일 때
    감당 불가능한 속도) 실전처럼 "이미 튜닝된 세션"을 재사용하는 것이
    맞는 전제이기도 하다.
    반환: (승리한 전투 수, 총 턴 수, 이월 덕분에 즉시 보너스를 얻은 전투 수,
          실제로 시도한 전투 수 — early_bonus_rate의 정확한 분모용)."""
    p = build_player(job, level)
    wins = 0
    total_turns = 0
    early_bonus = 0
    battles_attempted = 0
    for _ in range(n_battles):
        if not carryover:
            p.atb_remainder = 0.0
        spd = float(getattr(p, "spd", 10.0))
        start_atb = float(getattr(p, "atb_remainder", 0.0))
        if start_atb + spd >= 100.0:
            early_bonus += 1
        battles_attempted += 1

        win, turns = run_one_battle(p, hook, level, ai)
        total_turns += turns
        if win:
            wins += 1
        else:
            break
    return wins, total_turns, early_bonus, battles_attempted


def main():
    BASE_SEED = 20260914
    N       = int(os.environ.get("N", "300"))
    BATTLES = int(os.environ.get("BATTLES", "6"))
    LEVEL   = int(os.environ.get("LEVEL", "10"))
    OUT     = os.environ.get("OUT", "mc_campaign.json")

    ai = PlayerAI()
    results = {}
    for job in JOBS:
        # (job, LEVEL)당 hook 하나만 만들어 재사용 — 같은 job+레벨이면 매
        # 캠페인 시행의 플레이어 스탯이 결정적으로 동일(레벨업 공식에 RNG
        # 없음)하므로 몬스터 튜닝 캐시를 공유해도 무방하다. 시행마다 새로
        # 만들면 매번 튜닝을 처음부터 다시 돌려야 해서 N=300 규모가 감당
        # 안 될 정도로 느려진다(파일럿 실측: 1회당 십수 초).
        hook = BalanceHook(build_player(job, LEVEL), start_items(LEVEL),
                           show_graph=False, verbose=False, auto_prewarm=False)
        for carryover in (True, False):
            # 조건마다 시드를 다시 걸어 carryover=True/False가 같은
            # 초기조건(같은 몬스터 롤 시퀀스 시작점)에서 갈라지게 한다 —
            # 예전엔 시드를 한 번만 걸어서 carryover=False가 carryover=True가
            # 이미 소비한 난수 위치를 이어받는 편향이 있었다.
            seed(BASE_SEED)
            wins = turns = bonus = attempted = 0
            for _ in range(N):
                w, t, b, a = run_campaign(job, LEVEL, BATTLES, carryover, ai, hook)
                wins += w; turns += t; bonus += b; attempted += a
            key = f"{job}|carryover={carryover}"
            results[key] = {
                "avg_battles_won_per_campaign": round(wins / N, 3),
                "avg_turns_per_campaign":       round(turns / N, 2),
                # 분모를 N*BATTLES(패배로 조기 종료된 캠페인도 끝까지 싸운
                # 것처럼 취급)가 아니라 실제로 시도된 전투 수로 정정 —
                # 조기 종료가 있으면 예전 계산은 비율을 과소평가했다.
                "early_bonus_rate":             round(bonus / attempted, 4) if attempted else 0.0,
                "battles_attempted":            attempted,
            }
            print(key, results[key], file=sys.stderr)

    with open(OUT, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("DONE ->", OUT, file=sys.stderr)


if __name__ == "__main__":
    main()
