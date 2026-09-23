"""
app/Map.py — 노드맵 Blueprint
─────────────────────────────────────────────
엔드포인트:
  POST /api/map/generate      — 챕터 맵 생성 (챕터 시작 시 1회)
  GET  /api/map/state         — 현재 맵 상태 (선택 가능 노드 목록)
  POST /api/map/choose        — 노드 선택 → 이벤트 결정
  POST /api/map/node/complete — 노드 처리 완료 후 다음 노드 활성화
  POST /api/map/next_chapter  — 챕터 1 클리어 후 챕터 2 시작

노드 타입별 처리 (choose 응답):
  battle  → BattleSession 생성 (기존 explore.py 로직 재사용)
  elite   → BattleSession 생성 (엘리트 몬스터, 나중에 패턴 추가)
  event   → 랜덤 이벤트 결과 바로 반환
  rest    → options 반환 (heal / train 선택)
  shop    → 상점 목록 반환
  boss    → 보스 BattleSession 생성
"""
from __future__ import annotations

import random
from random import choices as rand_choices, randint, choice

from flask import Blueprint, jsonify

from game.Map      import FloorMap, NORMAL_LAYERS
from game.Relics   import shop_relic_items
from ai.battle.Relics import relic_shop_item_price
from game.Enemy_Class import (
    Make_MidBoss, Make_FinalBoss,
)

from app.Shared  import (
    _get_session, _player_dict, _register_pending_swap, _get_json_body, _get_str_field, _grant_relic,
    _pending_node_type,
)
from app.Battle  import _start_battle, _start_battle_multi
from core.ErrorLog import log_error

map_bp = Blueprint("map", __name__)


# ─────────────────────────────────────────────
# 이벤트 풀 (확장 가능)
# ─────────────────────────────────────────────
_EVENTS = [
    {
        "id":      "item_found",
        "label":   "아이템 발견",
        "handler": "_event_item_found",
    },
    # 추가 이벤트는 여기에 dict로 추가
]

_ITEM_DROP_POOL = [
    ("HP_S_potion", 4), ("MP_S_potion", 4),
    ("HP_M_potion", 2), ("MP_M_potion", 2),
    ("HP_L_potion", 1), ("MP_L_potion", 1),
]

# ─────────────────────────────────────────────
# 전투 노드 생성 규칙
# ─────────────────────────────────────────────
# 일반 전투: 1~3마리, 3마리일 때 hard 금지
# 엘리트:    1~2마리, hard 고정
# 스탯 보정:
#   일반 1마리: 100%  / 2마리: 90%  / 3마리: 80%
#   엘리트 1마리: 100% / 2마리: 90%

NORMAL_GRADE_POOL  = {"하": 0.35, "중": 0.45, "상": 0.20}
NORMAL_GRADE_3     = {"하": 0.45, "중": 0.55}          # 3마리: hard 금지

# ⚠️ 아래 두 표와 _early_game_multi_scale()은 **더 이상 실전 경로에서 쓰이지 않는다.**
#   다대일이 튜너를 우회하면서(12차: 일반, 13차: 엘리트 2마리) "할인"이라는 전제가
#   깨졌고, _multi_stat_scale() / _elite_stat_scale()의 **가산** 사다리가 대신한다.
#   지우지 않고 남겨 둔 이유는 둘뿐이다 — (1) 예전 측정 기록을 재현하는
#   TestFile/rogue_band_measure.py가 아직 import한다, (2) "다대일은 할인이었다"는
#   과거 설계를 읽을 수 있게 한다. **새 코드에서 쓰지 말 것.**
STAT_SCALE         = {1: 1.00, 2: 0.90, 3: 0.80}
ELITE_STAT_SCALE   = {1: 1.00, 2: 0.90}


def _early_game_multi_scale(player_lv: int) -> float:
    """다대일 조기 완화 (밸런스 v6) — n_enemies 롤은 레벨과 무관하게 25%
    확률로 3마리가 나올 수 있는데, 전사가 광역기(슬래시1)를 배우기 전인
    Lv1~5 구간에서는 단일 대상 스킬로 3마리를 상대해야 해서 기존 -20%
    보정만으로는 부족했음 (MC 실측: 전사 Lv1 1v3 30%, 목표 45%↑).

    ⚠️ **지금은 어떤 실전 경로에서도 안 쓴다.** 일반 다대일은 _multi_stat_scale(),
      엘리트는 _elite_stat_scale()이 맡고 두 사다리가 이 완화까지 흡수했다.
      TestFile/rogue_band_measure.py가 옛 규칙을 재현하느라 아직 import한다.

    ★ game/Enemy_Class.py의 _level_curve_mult()와는 별개 배율(다른 문제를
      겨냥함)이라 두 배율이 함께 곱해진다 — 밸런스 재조정 시 이 함수만
      보지 말고 그쪽도 같이 확인할 것."""
    if player_lv <= 2:
        return 0.80
    if player_lv <= 5:
        return 0.90
    return 1.0


# ── 일반 다대일 배율 (튜너 우회 경로 전용) ──────────────────────────
# ★ 할인이 아니라 **가산**이다. STAT_SCALE(0.90/0.80)은 "1v1이 약 55%가 되게
#   튜닝된 칼날 위 몬스터"를 n마리 붙일 때의 할인이었다. _make_enemies가
#   다대일에서 튜너를 우회하면서 전제가 깨졌다 — 등급 팩토리 몬스터는 1v1
#   승률이 이미 100% 수준이라, 깎아 주면 2~3마리도 90~100%가 된다
#   (우회 직후 전 구간 스윕 실측: 1v2 0/18칸 · 1v3 1/18칸만 밴드 안).
#
# 값은 실전 경로 그대로 잰 배율 스윕에서 읽었다(N=60/셀, 3직업 × 1.0/1.2/1.4/1.6,
#   TestFile/multi_scale_measure.out). 3마리는 레벨 사다리가 깨끗하게 나왔다 —
#   세 직업이 **동시에** 밴드에 드는 배율이 Lv5 1.6 · Lv10 1.4 · Lv15 1.2 · Lv20 1.0이다.
#   레벨이 오를수록 가산이 줄어드는 이유는 _level_curve_mult()가 이미 레벨당
#   +6%씩 몬스터를 올려 주기 때문이다(두 배율이 곱해진다 — 위 주석 참고).
#
# 2마리가 3마리보다 큰 가산을 원하는 건 이상해 보이지만 출발선이 다르다 —
#   NORMAL_GRADE_3가 「상」을 금지해서(하45/중55) 3마리 노드는 애초에 약한
#   등급만 나온다. 2마리 풀은 상20이 섞인다.
_MULTI_SCALE_LADDER = {
    # n: [(이 레벨 이하, 배율), ...] — 위에서부터 처음 맞는 칸
    2: [(5, 1.9), (10, 1.6), (15, 1.5), (20, 1.4), (999, 1.3)],
    3: [(5, 1.6), (10, 1.4), (15, 1.2), (999, 1.0)],
}


# ── 엘리트 다대일 배율 ────────────────────────────────────────────
# ★ **단독 엘리트에는 적용하지 않는다(1.0).** 측정으로 단독은 이미 밴드 안이었다 —
#   전 직업 × Lv5~25의 15칸이 47.7~69.6%다(TestFile/elite_scale_measure.out).
#   즉 튜너는 "하드 튜닝 몬스터 + 패턴"을 제대로 맞추고 있다. 문제는 2마리뿐이고,
#   그건 12차에서 일반 다대일을 고친 것과 정확히 같은 범주 오류다
#   (1v1용으로 튜닝된 상대를 둘 붙이고 0.90만 곱했다 → 전 직업 0.0~14.6%).
#
# 그래서 처방도 2마리에만 건다 — 리더·동료를 등급 팩토리 「상」으로 뽑고(_make_elite_encounter)
#   아래 가산을 곱한다. 값은 실전 경로 그대로 잰 하이브리드 스윕에서 읽었다
#   (N=120/셀, TestFile/elite_scale_measure.out, HYBRID=1).
#
# 일반 2마리 사다리(1.9→1.3)보다 낮은 이유: 엘리트는 둘 다 「상」 등급이고 리더에 패턴이
#   붙으므로 출발선이 더 높다. 일반 2마리 풀은 하35/중45/상20이 섞인다.
_ELITE_SCALE_LADDER = [(5, 1.5), (10, 1.5), (15, 1.3), (20, 1.2), (999, 1.1)]


def _elite_stat_scale(player_lv: int, n: int) -> float:
    """엘리트 노드에서 적이 n마리일 때 몬스터 스탯에 곱할 배율.

    n == 1이면 1.0 — 단독 엘리트는 튜너가 이미 맞춰 놨으므로 건드리지 않는다.
    """
    if n <= 1:
        return 1.0
    for max_lv, mult in _ELITE_SCALE_LADDER:
        if player_lv <= max_lv:
            return mult
    return _ELITE_SCALE_LADDER[-1][1]


def _multi_stat_scale(player_lv: int, n: int) -> float:
    """일반 전투 노드에서 적이 n마리일 때 몬스터 스탯에 곱할 배율.

    n == 1이면 1.0(보정 없음 — 그 칸은 자동 튜너가 맡는다).
    엘리트는 _elite_stat_scale()을 쓴다(단독은 1.0 — 튜너가 이미 맞춰 놨다).
    """
    if n <= 1:
        return 1.0
    ladder = _MULTI_SCALE_LADDER.get(n) or _MULTI_SCALE_LADDER[3]
    for max_lv, mult in ladder:
        if player_lv <= max_lv:
            return mult
    return ladder[-1][1]


def _pick_grade(pool: dict) -> str:
    """가중치 기반 난이도 선택."""
    from random import choices as _rc
    keys = list(pool.keys())
    wts  = list(pool.values())
    return _rc(keys, weights=wts, k=1)[0]


def _apply_stat_scale(enemies: list, scale: float) -> None:
    """다대일 스탯 보정 적용 (인플레이스).

    ★ 예전엔 `scale >= 1.0`이면 곧바로 반환했다(할인 전용이었으므로). 일반
      다대일이 튜너를 우회하면서 _multi_stat_scale()이 1.0을 넘는 **가산**을
      돌려주게 됐고, 그 조기 반환이 남아 있으면 가산이 통째로 무시된다.
      이제 1.0(정확히)일 때만 아무것도 하지 않는다."""
    if scale == 1.0:
        return
    for e in enemies:
        for attr in ("hp", "maxhp"):
            if hasattr(e, attr):
                setattr(e, attr, int(getattr(e, attr) * scale))
        for attr in ("stg", "sp", "arm", "sparm"):
            if hasattr(e, attr):
                setattr(e, attr, round(getattr(e, attr) * scale, 1))


# 난이도 한글 → 내부 키 매핑 (BalanceHook 캐시 키)
_GRADE_TO_KEY = {"하": "easy", "중": "normal", "상": "hard"}


# ─────────────────────────────────────────────
# 챕터/노드 구간별 몬스터 출현 풀
# ─────────────────────────────────────────────
# 몬스터 출현은 플레이어 레벨(min_lv)이 아니라 "챕터 + 노드 구간" 기준으로 고정.
#   구간: 챕터 내 일반 층(1~NORMAL_LAYERS)을 초반/중반/후반 3등분.
#   elite 노드는 구간 무관 — 별도의 ELITE_CHAPTER_POOL에서만 뽑는다.
CHAPTER_TIER_POOL = {
    (1, "early"): ["고블린", "박쥐", "슬라임"],
    (1, "mid"):   ["고블린", "박쥐", "슬라임", "빙결 슬라임", "번개 슬라임"],
    (1, "late"):  ["고블린", "박쥐", "슬라임", "빙결 슬라임", "번개 슬라임", "화염 슬라임"],
    (2, "early"): ["박쥐", "화염 슬라임", "빙결 슬라임", "번개 슬라임", "사제", "암살자"],
    (2, "mid"):   ["박쥐", "화염 슬라임", "빙결 슬라임", "번개 슬라임", "사제", "암살자", "골렘"],
    (2, "late"):  ["박쥐", "화염 슬라임", "빙결 슬라임", "번개 슬라임", "사제", "암살자", "골렘", "유령"],
}

# ── 엘리트 리더 전용 챕터별 풀 (패턴이 구현된 몬스터만) ──
# 챕터 단위로만 구분(일반 몬스터처럼 초/중/후반 세분화 안 함).
ELITE_CHAPTER_POOL = {
    1: ["고블린", "박쥐", "슬라임", "화염 슬라임", "빙결 슬라임", "번개 슬라임"],
    2: ["박쥐", "화염 슬라임", "빙결 슬라임", "번개 슬라임", "골렘", "암살자", "사제"],
}

# 항상 단독으로만 등장하는 엘리트 리더 (증식 슬라임 — UI 3슬롯 한도 때문)
_ELITE_SOLO_ONLY = {"슬라임"}
# 항상 동료와 함께 등장하는 엘리트 리더 (사제 — 부활 대상 필수)
_ELITE_PAIR_ONLY = {"사제"}


def _node_tier(layer: int) -> str:
    """일반 층(1~NORMAL_LAYERS)을 초반/중반/후반 3등분."""
    early_end = round(NORMAL_LAYERS / 3)
    mid_end   = round(NORMAL_LAYERS * 2 / 3)
    if layer <= early_end:
        return "early"
    if layer <= mid_end:
        return "mid"
    return "late"


def _make_enemies(hook, n: int, grade_pool: dict, chapter: int = 1, layer: int = 1) -> list:
    """일반 전투 노드용 — n마리 적 생성 (챕터+노드 구간 풀에서 선택, 각자 독립 grade,
    BalanceHook 캐시 조회). 엘리트 노드는 _make_elite_encounter()가 따로 처리한다.

    ※ 구 방식(플레이어 레벨 min_lv 기반 hook.pick_random_enemy_type)은 폐기 —
      챕터+노드 구간 기준 고정 풀(CHAPTER_TIER_POOL)에서만 출현.

    ★ n == 1이면 자동 튜닝(hook.get_enemy), n >= 2면 등급 팩토리
      (hook.make_graded_enemy) — **다대일은 튜너를 거치지 않는다.**

      튜너는 "1v1이 목표 승률(약 55%)이 되도록" 몬스터 하나를 맞춘다. 그렇게
      칼날 위에 세운 상대를 2~3마리 뽑아 평평한 STAT_SCALE(0.90/0.80)만
      곱하면 산수가 안 맞는다 — 턴제에서 n마리는 받는 피해도, 깎아야 할 HP도
      n배다. 실측(N=150, 실전 스폰 규칙 그대로):

          1v1  전사 46.7/53.3/62.0 · 마법사 58.0/50.7/56.7 · 도적 56.0/64.7/57.3  (Lv10/15/20)
          1v2  전 직업 0.0 ~ 1.3%
          1v3  전 직업 0.0 ~ 0.7%   ← 패배 시 적 HP가 63~93% 남는다

      접전이 아니라 계산이 성립하지 않는 것이다. 같은 칸을 등급 팩토리로
      바꾸면 절벽이 곡선이 된다(전사 1v3: Lv10 100% → Lv15 68% → Lv20 20%).
      이유는 단순하다 — 튜닝된 몬스터는 "1v1에서 간신히 이기는" 상대라 둘이
      되면 즉시 뒤집히지만, 등급 몬스터는 여유가 있어 마릿수에 완만하게 반응한다.

      보스가 이미 같은 이유로 튜너를 우회한다(Make_MidBoss/Make_FinalBoss는
      _apply_grade도 거치지 않고 직접 튜닝). 다대일도 같은 부류로 옮긴 것이고,
      그래서 다대일의 난이도 조절은 이제 손으로 맞춘 곡선
      (_level_curve_mult · _multi_stat_scale)이 전담한다.

      ※ n >= 2에서도 hook.get_enemy()가 하던 **백그라운드 튜닝 예열은 유지**한다 —
        그 몬스터를 나중에 1v1로 만날 때 폴백을 쓰지 않도록.
      ※ 이전 시도: BALANCE_PATCH_3의 hook.get_encounter() 그룹 튜닝은 연결했다가
        철회했다(이진탐색이 계단형 목적함수에서 재현 불가능한 값에 수렴 —
        같은 조합을 두 번 튜닝하면 배율이 0.15↔0.385로 갈렸다). 그 계단은 튜너
        입력 버그(d614105)를 고친 뒤에도 그대로 남아 있음을 재측정으로 확인했다.
        get_encounter()는 구현·테스트된 상태로 남아 있지만 연결하지 않는다."""
    tier = _node_tier(layer)
    pool = CHAPTER_TIER_POOL.get((chapter, tier)) or CHAPTER_TIER_POOL[(2, "late")]

    # 사제는 단독 등장 불가 — 항상 다른 몬스터와 함께 나와야 함.
    solo_pool = [t for t in pool if t != "사제"] or pool

    enemies = []
    grades  = []
    for _ in range(n):
        enemy_type = choice(pool if n > 1 else solo_pool)

        grade      = _pick_grade(grade_pool)
        diff_key   = _GRADE_TO_KEY.get(grade, "normal")
        if n > 1:
            # 다대일 — 등급 팩토리(튜너 우회). 위 docstring 참고.
            snap = hook.make_graded_enemy(enemy_type, grade)
            # 이 종류를 나중에 1v1로 만날 때를 위해 예열만 걸어 둔다(결과는 안 쓴다).
            hook.prewarm(enemy_type, chapter)
        else:
            # 단독 — difficulty 파라미터로 원하는 난이도 직접 지정
            snap = hook.get_enemy(enemy_type, difficulty=diff_key, chapter=chapter)
        unit       = hook.make_battle_unit(snap)
        enemies.append(unit)
        grades.append(grade)
    return enemies, grades


def _make_elite_encounter(hook, chapter: int = 1, layer: int = 1, player_lv: int = None):
    """엘리트 노드 전용 — 리더 1마리(패턴 보유) + 필요 시 동료 1마리.

    리더 타입은 ELITE_CHAPTER_POOL[chapter]에서 뽑고, 증식 슬라임(_ELITE_SOLO_ONLY)은
    항상 단독, 사제(_ELITE_PAIR_ONLY)는 항상 동료 필수, 그 외는 기존처럼 랜덤 1~2마리.
    동료는 일반 CHAPTER_TIER_POOL에서 뽑아 elite_leader=False로 둔다
    (패턴 없는 평범한 몬스터 — 리더의 패턴만 발동).

    ★ **단독이면 튜너(hook.get_enemy hard), 2마리면 등급 팩토리 「상」**이다.
      측정으로 갈린 결과다 — 단독은 전 직업 × Lv5~25의 15칸이 47.7~69.6%로 이미
      밴드 안인데(튜너가 패턴까지 포함해 제대로 맞추고 있다) 2마리는 0.0~14.6%다.
      2마리 쪽은 12차에서 일반 다대일을 고친 것과 같은 범주 오류이므로 같은 처방을
      쓰고, 단독은 손대지 않는다. 단독까지 등급으로 바꾸면 100%가 된다(실측).

    ★ **배율을 이 함수 안에서 적용해서 돌려준다** — 호출부가 셋(app/Map.py의 라우트,
      app/Master.py, TestFile/montecarlo.py)인데 이미 갈라져 있었다(montecarlo만
      _early_game_multi_scale을 빼먹어, 스윕이 재는 저레벨 엘리트가 실전과 달랐다).
      호출부에서 또 곱하지 말 것.
    """
    leader_type = choice(ELITE_CHAPTER_POOL.get(chapter) or ELITE_CHAPTER_POOL[1])

    if leader_type in _ELITE_SOLO_ONLY:
        paired = False
    elif leader_type in _ELITE_PAIR_ONLY:
        paired = True
    else:
        paired = randint(1, 2) == 2

    if paired:
        # 2마리 — 등급 팩토리(튜너 우회). 나중에 이 종류를 단독으로 만날 때를 위해 예열만.
        leader_snap = hook.make_graded_enemy(leader_type, "상")
        hook.prewarm(leader_type, chapter)
    else:
        leader_snap = hook.get_enemy(leader_type, difficulty="hard", chapter=chapter)
    leader_unit = hook.make_battle_unit(leader_snap)
    leader_unit.is_elite = True
    leader_unit.elite_leader = True

    if leader_type == "빙결 슬라임":
        # "전투 시작 시 빙결 갑옷을 가진다" — 받는 물리 피해 추가 15% 감소를
        # 이 몬스터의 원래 physical_resist 위에 상대적으로 곱한다(고정값
        # 대입 아님 — 슬라임 종류마다 기본 저항이 달라서 절대값을 쓰면 틀어짐).
        from ai.battle.EliteKit import ICE_SLIME_ARMOR_REDUCTION
        leader_unit.physical_resist = getattr(leader_unit, "physical_resist", 1.0) * (1 - ICE_SLIME_ARMOR_REDUCTION)

    enemies = [leader_unit]
    grades  = ["상"]

    if paired:
        tier = _node_tier(layer)
        pool = CHAPTER_TIER_POOL.get((chapter, tier)) or CHAPTER_TIER_POOL[(2, "late")]
        escort_pool = [t for t in pool if t != "사제"] or pool
        escort_type = choice(escort_pool)
        escort_snap = hook.make_graded_enemy(escort_type, "상")
        hook.prewarm(escort_type, chapter)
        escort_unit = hook.make_battle_unit(escort_snap)
        enemies.append(escort_unit)
        grades.append("상")

    if player_lv is None:
        player_lv = getattr(getattr(hook, "player", None), "lv", 1)
    _apply_stat_scale(enemies, _elite_stat_scale(player_lv, len(enemies)))
    return enemies, grades


def _event_item_found(gs: dict) -> dict:
    """이벤트: 아이템 발견."""
    player = gs["player"]
    names   = [x[0] for x in _ITEM_DROP_POOL]
    weights = [x[1] for x in _ITEM_DROP_POOL]
    gained  = rand_choices(names, weights=weights, k=1)[0]

    inv    = gs["inventory"]
    result = inv.add(gained)
    gs["items"] = inv.to_flat_list()

    base = {
        "event_id": "item_found",
        "player":   _player_dict(player, inv),
    }
    if result["ok"]:
        return {**base, "message": f"[아이템 발견] {gained}을(를) 발견했다!",
                "item": gained}
    elif result.get("reason") == "special_full":
        ticket_id = _register_pending_swap(gs, gained, source="event")
        return {**base, "event": "item_full",
                "incoming":   gained,
                "ticket_id":  ticket_id,
                "candidates": result["candidates"],
                "message":    result["message"]}
    else:
        return {**base, "message": result["message"]}


# ─────────────────────────────────────────────
# DB 로그 헬퍼
# ─────────────────────────────────────────────

def _log_node_choice(gs: dict, node, battle_result: str = None,
                     battle_turns: int = None, extra: dict = None) -> int | None:
    """노드 선택을 DB에 기록. 생성된 행의 id를 반환(없으면 None).

    ★ battle/elite/boss 노드는 이 함수가 호출되는 시점(전투 시작 직후)엔
      아직 승패/턴 수를 모른다 — battle_result/battle_turns는 항상 기본값
      None으로 기록됐다. 반환된 id를 gs["pending_node_choice_id"]에 저장해
      두면, app/Battle.py의 _finish_battle()이 전투가 실제로 끝난 뒤 그 id로
      같은 행을 찾아 결과를 채워 넣을 수 있다(아래 _update_node_choice_result
      참고)."""
    try:
        from DB import get_session as db_session
        from DB.Models import NodeChoice
        import json as _json

        run_id = gs.get("run_id")
        if not run_id:
            return None

        player = gs["player"]
        with db_session() as db:
            nc = NodeChoice(
                run_id         = run_id,
                turn           = gs.get("map_turn", 1),
                layer          = node.layer,
                node_id        = node.node_id,
                node_type      = node.node_type,
                player_hp_ratio= round(player.hp / player.maxhp, 3) if player.maxhp > 0 else 0,
                player_lv      = player.lv,
                battle_result  = battle_result,
                battle_turns   = battle_turns,
                extra_data     = _json.dumps(extra or {}, ensure_ascii=False),
            )
            db.add(nc)
            db.flush()
            return nc.id
    except Exception as e:
        log_error("node_choice_log", e)
        return None


def _update_node_choice_result(node_choice_id: int, battle_result: str, battle_turns: int) -> None:
    """전투 종료 후 해당 NodeChoice 행의 battle_result/battle_turns를 채운다.
    app/Battle.py의 _finish_battle()에서 호출 — 실패해도 게임 진행에는
    영향 없어야 하므로 다른 DB 로깅 헬퍼들과 동일하게 조용히 실패한다."""
    if not node_choice_id:
        return
    try:
        from DB import get_session as db_session
        from DB.Models import NodeChoice

        with db_session() as db:
            nc = db.query(NodeChoice).filter(NodeChoice.id == node_choice_id).first()
            if nc:
                nc.battle_result = battle_result
                nc.battle_turns  = battle_turns
    except Exception as e:
        log_error("node_choice_result_update", e)


def _create_run(gs: dict, chapter: int) -> None:
    """런 시작 시 DB Run 레코드 생성."""
    try:
        from DB import get_session as db_session
        from DB.Models import Run

        db_user_id = gs.get("db_user_id")
        if not db_user_id:
            return

        player = gs["player"]
        new_run_id = None
        with db_session() as db:
            run = Run(
                user_id        = db_user_id,
                chapter        = chapter,
                player_job     = player.job,
                player_lv_start= player.lv,
            )
            db.add(run)
            db.flush()
            new_run_id = run.id
        # ★ gs 반영은 with 블록을 예외 없이 빠져나온 뒤(=커밋 확정 후)에만
        #   한다 — flush 직후(커밋 전)에 곧장 대입하면, 그 뒤 commit만 실패하는
        #   드문 DB 장애에서 gs["run_id"]가 실제로는 존재하지 않는(롤백된) 행을
        #   가리키게 되고, 이후 그 run_id로 저장되는 모든 NodeChoice가 고아
        #   레코드가 될 수 있었다.
        gs["run_id"] = new_run_id
        gs["run_finished"] = False   # 새 런 시작 — 이전 런의 종료 표시 초기화
        print(f"[DB] Run created: id={new_run_id}, chapter={chapter}")
    except Exception as e:
        log_error("run_create", e)


def _finish_run(gs: dict, result: str) -> None:
    """런 종료 시 DB Run 업데이트."""
    try:
        from DB import get_session as db_session
        from DB.Models import Run

        run_id = gs.get("run_id")
        if not run_id:
            return

        player = gs["player"]
        with db_session() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            # ★ 이미 결과가 박힌 런은 덮어쓰지 않는다 — gs["run_finished"]는
            #   세션 스냅샷에 실리지만(app/Shared.py) Redis까지 사라진 뒤
            #   DB로만 복구되면 없을 수 있다. DB에 남아 있는 결과가 최종
            #   판단 근거다: clear/dead로 끝난 런이 나중에 abandon으로
            #   바뀌면 런 통계가 거짓이 된다.
            if run and run.result and result == "abandon":
                gs["run_finished"] = True
                return
            if run:
                run.result        = result
                run.player_lv_end = player.lv
                run.total_nodes   = gs.get("map_turn", 0)
                run.boss_cleared  = (result == "clear")
        # ★ gs["run_id"]는 여기서 지우지 않는다 — 새 런 시작(_create_run)이
        #   그 값을 덮어쓰는 게 기존 설계다. 대신 "이미 종료 처리됨" 표시만
        #   남겨서, 게임을 그만두고 "새 게임"을 눌렀을 때(app/Game.py의
        #   new_game()) 이미 clear/dead로 끝난 런을 abandon으로 잘못
        #   덮어쓰지 않게 한다 — 아래 참고.
        gs["run_finished"] = True
    except Exception as e:
        log_error("run_finish", e)


# ─────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────

@map_bp.route("/api/map/generate", methods=["POST"])
def map_generate():
    """
    챕터 맵 생성 — 최초 챕터 1 시작 전용.
    요청: { "chapter": 1 }

    ★ 예전엔 기존 맵/전투/챕터 상태를 전혀 확인하지 않아서, 이미 챕터 1을
      진행 중(또는 챕터 2에 있음)이어도 이 API를 다시 호출하면 챕터 1 맵을
      새로 덮어써 진행 상황을 날리거나(맵/런 초기화), 심지어 전투 도중에도
      맵 자체를 바꿔치기할 수 있었다 — 사실상 진행 우회/데이터 손실 경로.
      프런트의 유일한 호출부(UI_Map.js의 initMap(chapter=1), Actions.js의
      newGame()에서 딱 한 번 호출)도 항상 chapter=1의 "새 게임 시작"만
      의도하므로, 여기서는 그 한 가지 경우만 허용한다 — 챕터 2 진입은
      /api/map/next_chapter(클리어 여부를 확인하는 전용 라우트)의 몫이다.
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    if gs.get("battle"):
        return jsonify({"ok": False, "error": "전투 중에는 맵을 생성할 수 없습니다."}), 400

    if gs.get("map"):
        return jsonify({"ok": False, "error": "이미 진행 중인 맵이 있습니다."}), 400

    data = _get_json_body()
    try:
        chapter = int(data.get("chapter", 1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "chapter는 정수여야 합니다."}), 400

    if chapter != 1:
        return jsonify({"ok": False, "error": "챕터 1만 이 API로 시작할 수 있습니다."}), 400

    fmap = FloorMap.generate(chapter)
    gs["map"]      = fmap.to_dict()    # 직렬화해서 저장
    gs["map_turn"] = 0
    gs["chapter"]  = chapter

    _create_run(gs, chapter)

    return jsonify({
        "ok":      True,
        "chapter": chapter,
        "map":     fmap.get_state(),
        "message": f"챕터 {chapter} 시작!",
    })


@map_bp.route("/api/map/state", methods=["GET"])
def map_state():
    """현재 맵 상태 반환."""
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    if not gs.get("map"):
        return jsonify({"ok": False, "error": "맵이 없습니다. /api/map/generate 먼저 호출하세요."}), 400

    fmap = FloorMap.from_dict(gs["map"])
    return jsonify({"ok": True, "map": fmap.get_state(),
                    "player": _player_dict(gs["player"], gs["inventory"])})


@map_bp.route("/api/map/choose", methods=["POST"])
def map_choose():
    """
    노드 선택 → 타입별 처리 후 결과 반환.
    요청: { "node_id": "3_1" }

    응답 event 필드:
      battle / elite / boss → battle_state 포함
      event                 → message + item 등
      rest                  → options 포함
      shop                  → shop_items 포함
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    player = gs.get("player")
    if player and player.hp <= 0:
        return jsonify({"ok": False, "error": "사망한 상태입니다. 새 게임을 시작하세요.",
                        "reason": "player_dead"}), 400

    if gs.get("battle"):
        return jsonify({"ok": False, "error": "전투 중입니다. 먼저 전투를 완료하세요."})

    if not gs.get("map"):
        return jsonify({"ok": False, "error": "맵이 없습니다. /api/map/generate 먼저 호출하세요."}), 400

    data    = _get_json_body()
    node_id = _get_str_field(data, "node_id")
    if not node_id:
        return jsonify({"ok": False, "error": "node_id가 필요합니다."}), 400

    fmap = FloorMap.from_dict(gs["map"])
    ok, node, err = fmap.choose(node_id)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    gs["map_turn"] = gs.get("map_turn", 0) + 1
    gs["pending_node_id"] = node_id   # node/complete 호출 시 참조

    player  = gs["player"]
    node_type = node.node_type

    # ── 전투 / 엘리트 / 보스 ──────────────────
    if node_type in ("battle", "elite", "boss"):
        gs["battle_node_type"] = node_type
        gs["battle_map_layer"] = node.layer
        is_boss = (node_type == "boss")
        chapter = gs.get("chapter", 1)

        if is_boss:
            boss = _get_boss(chapter, player.lv)
            state = _start_battle(gs, boss, is_boss=True)
            gs["pending_node_choice_id"] = _log_node_choice(gs, node)
            _save_map(gs, fmap)
            return jsonify({
                "ok": True, "event": node_type,
                "node_id": node_id,
                "enemy": {"name": boss.name, "hp": boss.hp},
                "battle_state": state,
            })

        hook = gs["hook"]

        if node_type == "elite":
            # ── 엘리트: 리더(패턴 보유) + 필요 시 동료 1마리 ──
            # ★ 배율은 _make_elite_encounter()가 이미 적용해서 돌려준다 — 여기서 또 곱하지 말 것.
            enemies, grades = _make_elite_encounter(hook, chapter, layer=node.layer,
                                                    player_lv=player.lv)
            n_enemies = len(enemies)
            scale     = 1.0
        else:
            # ── 일반: 1~3마리, 3마리일 때 hard 금지 ──
            rd = randint(1, 20)
            n_enemies  = 1 if rd <= 11 else (2 if rd <= 15 else 3)
            grade_pool = NORMAL_GRADE_3 if n_enemies == 3 else NORMAL_GRADE_POOL
            # ★ 일반 다대일은 STAT_SCALE(할인)이 아니라 _multi_stat_scale(가산)을 쓴다
            #   — _make_enemies가 이 칸에서 튜너를 우회하기 때문. 그쪽 docstring 참고.
            scale      = _multi_stat_scale(player.lv, n_enemies)
            enemies, grades = _make_enemies(hook, n_enemies, grade_pool, chapter,
                                             layer=node.layer)

        # 다대일 스탯 보정 (BattleSession 내 보정과 중복 방지 — 외부에서만 처리)
        if n_enemies > 1:
            _apply_stat_scale(enemies, scale)

        # 전투 시작
        if n_enemies == 1:
            state = _start_battle(gs, enemies[0])
        else:
            state = _start_battle_multi(gs, enemies)

        # 로그 기록
        gs["pending_node_choice_id"] = _log_node_choice(gs, node, extra={
            "node_type":   node_type,
            "enemy_count": n_enemies,
            "grades":      grades,
            "stat_scale":  scale,
        })
        _save_map(gs, fmap)

        resp = {
            "ok":          True,
            "event":       node_type,
            "node_id":     node_id,
            "enemy_count": n_enemies,
            "grades":      grades,
            "stat_scale":  scale,
            "battle_state": state,
        }
        if n_enemies == 1:
            resp["enemy"] = {"name": enemies[0].name, "hp": enemies[0].hp}
        else:
            resp["enemies"] = [{"name": e.name, "hp": e.hp} for e in enemies]

        return jsonify(resp)

    # ── 이벤트 ────────────────────────────────
    elif node_type == "event":
        event_def = _pick_event()
        handler   = globals().get(event_def["handler"])
        result    = handler(gs) if handler else {"message": "알 수 없는 이벤트"}
        _log_node_choice(gs, node)
        # 이벤트는 즉시 완료 → 바로 visited 처리
        fmap.mark_visited(node_id)
        _save_map(gs, fmap)
        return jsonify({
            "ok": True, "event": "event",
            "node_id": node_id,
            "event_id": event_def["id"],
            "node_done": True,    # 프론트에 즉시 완료 신호
            **result,
        })

    # ── 휴식 ──────────────────────────────────
    elif node_type == "rest":
        _log_node_choice(gs, node)
        _save_map(gs, fmap)   # ★ choose()의 갈래 잠금(player_branch) 저장 — 새로고침 시 유지
        return jsonify({
            "ok": True, "event": "rest",
            "node_id": node_id,
            "message": "휴식 지점에 도착했다.",
            "options": [
                {"key": "heal",  "label": "체력 회복 (maxHP의 1/3)"},
                {"key": "train", "label": "수련 (경험치 60~80%)"},
            ],
        })

    # ── 상점 ──────────────────────────────────
    elif node_type == "shop":
        _log_node_choice(gs, node)
        _save_map(gs, fmap)   # ★ choose()의 갈래 잠금(player_branch) 저장 — 새로고침 시 유지
        shop_items = _shop_items_for(player)
        return jsonify({
            "ok": True, "event": "shop",
            "node_id":    node_id,
            "message":    "상점에 도착했다.",
            "shop_items": shop_items,
            "gold":       gs.get("gold", 0),
        })

    return jsonify({"ok": False, "error": f"알 수 없는 노드 타입: {node_type}"}), 400


@map_bp.route("/api/map/node/complete", methods=["POST"])
def map_node_complete():
    """
    노드 처리 완료 후 호출 (휴식 선택/상점 구매 완료 등).
    전투 완료는 battle_action에서 자동 처리.

    ★ node_id는 요청 바디로 받지 않는다 — 예전엔 클라이언트가 보낸 node_id를
      그대로 신뢰해서(서버의 pending_node_id보다 우선 사용), 아무 노드
      ID나(보스 노드 포함) 보내서 실제로 밟지 않은 노드를 완료 처리하고
      다음 노드를 미리 열어버릴 수 있었다. 항상 서버가 /api/map/choose에서
      직접 검증하고 기록해 둔 pending_node_id만 사용한다.
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    if not gs.get("map"):
        return jsonify({"ok": False, "error": "맵이 없습니다. /api/map/generate 먼저 호출하세요."}), 400

    node_id = gs.get("pending_node_id", "")
    if not node_id:
        return jsonify({"ok": False, "error": "완료할 노드가 없습니다."}), 400

    # ★ 이 API는 "휴식 선택 완료 · 상점 나가기"처럼 서버가 결과를 따로 검증할
    #   수 없는 노드만 닫는다. 전투 계열 노드는 app/Battle.py의 _finish_battle()이
    #   승리를 확인하고 닫는다 — 예전엔 그 구분이 없어서, 보스전이 진행 중인
    #   상태에서 이 API를 직접 호출하면 전투는 그대로 둔 채 보스 노드를
    #   완료 처리하고 fmap.completed → _finish_run(gs, "clear")까지 갔다
    #   (보스를 잡지 않고 챕터 클리어). CLAUDE.md의 "서버가 아는 것을 클라이언트
    #   입력으로 대신하지 않는다"에 해당하는 구멍이다.
    if gs.get("battle") is not None:
        return jsonify({"ok": False, "error": "전투 중에는 노드를 완료할 수 없습니다.",
                        "reason": "battle_in_progress"}), 400
    node_type = _pending_node_type(gs)
    if node_type in ("battle", "elite", "boss"):
        return jsonify({"ok": False,
                        "error": "전투 노드는 전투를 끝내야 완료됩니다.",
                        "reason": "battle_node"}), 400

    fmap = FloorMap.from_dict(gs["map"])
    if not fmap.mark_visited(node_id):
        return jsonify({"ok": False, "error": "이미 처리됐거나 선택할 수 없는 노드입니다."}), 400
    _save_map(gs, fmap)

    if fmap.completed:
        # ★ 아래 미완료 분기와 동일하게 pending_node_id를 비운다 — 현재
        #   라우팅상 이 분기는 보스가 아닌 노드(휴식/상점)에서 fmap.completed가
        #   True가 되는 경우가 없어 실질적으로 도달하지 않지만(보스전 완료는
        #   app/Battle.py의 _finish_battle()이 처리), 방어적으로 맞춰둔다 —
        #   여기서 안 지우면 다음 요청이 이미 끝난 노드를 pending으로 오인할
        #   잠재 위험이 있다.
        gs["pending_node_id"] = None
        _finish_run(gs, "clear")
        chapter = gs.get("chapter", 1)
        if chapter >= 2:
            return jsonify({
                "ok": True, "map_done": True,
                "game_clear": True,
                "message": "🎉 모든 챕터를 클리어했습니다!",
                "map": fmap.get_state(),
            })
        return jsonify({
            "ok": True, "map_done": True,
            "next_chapter": chapter + 1,
            "message": f"챕터 {chapter} 클리어! 챕터 {chapter + 1}로 진행합니다.",
            "map": fmap.get_state(),
        })

    gs["pending_node_id"] = None
    return jsonify({
        "ok":    True,
        "map":   fmap.get_state(),
        "player": _player_dict(gs["player"], gs["inventory"]),
    })


@map_bp.route("/api/map/next_chapter", methods=["POST"])
def map_next_chapter():
    """챕터 1 클리어 후 챕터 2 맵 생성.

    ★ 예전엔 현재 챕터 맵을 실제로 클리어했는지 확인하지 않아서, 이 API를
      직접 호출하면 챕터 1을 한 노드도 안 밟고 바로 챕터 2로 건너뛸 수
      있었다(보스도 안 잡고 진행). 현재 맵의 completed 플래그를 확인한다."""
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    if not gs.get("map") or not gs["map"].get("completed"):
        return jsonify({"ok": False, "error": "현재 챕터를 먼저 클리어해야 합니다."}), 400

    next_ch = gs.get("chapter", 1) + 1
    if next_ch not in (1, 2):
        return jsonify({"ok": False, "error": "더 이상 챕터가 없습니다."}), 400

    fmap = FloorMap.generate(next_ch)
    gs["map"]      = fmap.to_dict()
    gs["map_turn"] = 0
    gs["chapter"]  = next_ch
    gs["pending_node_id"] = None

    _create_run(gs, next_ch)

    return jsonify({
        "ok":      True,
        "chapter": next_ch,
        "map":     fmap.get_state(),
        "message": f"챕터 {next_ch} 시작!",
    })


# ─────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────

def _save_map(gs: dict, fmap: FloorMap) -> None:
    """FloorMap → gs["map"] 저장."""
    gs["map"] = fmap.to_dict()


def _pick_event() -> dict:
    """랜덤 이벤트 선택 (균등 확률)."""
    return random.choice(_EVENTS) if _EVENTS else {
        "id": "nothing", "label": "아무 일도 없음", "handler": None
    }


def _get_boss(chapter: int, player_lv: int):
    """챕터별 보스 생성."""
    if chapter == 1:
        return Make_MidBoss(player_lv)
    return Make_FinalBoss(player_lv)


def _get_shop_items(player_lv: int, relics=None, job: str = "") -> list:
    """
    상점 아이템 목록 생성 (포션 + 특수 아이템 + 아직 없는 유물).
    특수 아이템은 레벨 3 이상부터 노출. 유물은 game/Relics.py(가격 RELIC_SHOP_PRICE)에서.
    """
    items = [
        {"id": "HP_M_potion", "name": "HP 중형 포션", "type": "potion",
         "effect": "HP +60%", "price": 50},
        {"id": "HP_L_potion", "name": "HP 대형 포션", "type": "potion",
         "effect": "HP +100%", "price": 80},
        {"id": "MP_M_potion", "name": "MP 중형 포션", "type": "potion",
         "effect": "MP +60%", "price": 50},
        {"id": "MP_L_potion", "name": "MP 대형 포션", "type": "potion",
         "effect": "MP +100%", "price": 80},
    ]
    if player_lv >= 3:
        items += [
            {"id": "bomb",       "name": "폭탄",       "type": "special",
             "effect": "전체 데미지", "price": 120},
            {"id": "web_bomb",   "name": "거미줄 폭탄", "type": "special",
             "effect": "전체 데미지 + 속도 감소", "price": 150},
            {"id": "focus_drug", "name": "집중 물약",   "type": "special",
             "effect": "다음 스킬 추가 피해", "price": 100},
        ]
    # 유물 「여행자의 지도」 — 아이템만 −20%. 유물 가격은 깎지 않는다(7장: 풀 소진 방지)
    for it in items:
        it["price"] = relic_shop_item_price(relics or [], it["price"])
    items += shop_relic_items(relics or [], job)
    return items


def _shop_items_for(player) -> list:
    return _get_shop_items(player.lv, getattr(player, "relics", []), getattr(player, "job", ""))


# ─────────────────────────────────────────────
# 상점 구매 API
# ─────────────────────────────────────────────

@map_bp.route("/api/shop/buy", methods=["POST"])
def shop_buy():
    """
    상점 아이템 구매.
    요청: { "item_id": "HP_M_potion" }
    ★ price는 요청 바디로 받지 않는다 — 클라이언트가 보낸 값을 그대로 믿으면
      {"price": 0}이나 음수 price로 무료 구매/골드 무한 생성이 가능해짐.
      항상 _shop_items_for(player)의 서버 측 가격표에서 조회한다.
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data    = _get_json_body()
    item_id = data.get("item_id", "")
    gold    = gs.get("gold", 0)

    shop_items = _shop_items_for(gs["player"])
    item_meta  = next((it for it in shop_items if it["id"] == item_id), None)
    if item_meta is None:
        return jsonify({"ok": False, "error": "판매하지 않는 아이템입니다."}), 400
    price = item_meta["price"]

    if gold < price:
        return jsonify({"ok": False, "error": f"골드가 부족합니다. (보유: {gold}G)"}), 400

    if item_meta.get("type") == "relic":
        # 유물은 인벤토리 칸이 아니라 플레이어에게 붙는다 — 이미 가졌으면 진열되지 않으므로 여기선 안전망
        if not _grant_relic(gs, item_id):
            return jsonify({"ok": False, "error": "이미 가진 유물입니다."}), 400
        gs["gold"] = gold - price
        return jsonify({
            "ok":        True,
            "message":   f"유물 {item_meta['name']} 획득! (-{price}G)",
            "gold":      gs["gold"],
            "player":    _player_dict(gs["player"], gs["inventory"]),
            "shop_items": _shop_items_for(gs["player"]),
        })

    inv    = gs["inventory"]
    result = inv.add(item_id)
    if not result.get("ok"):
        reason = result.get("reason", "")
        if reason == "special_full":
            # ★ 아직 결제 전(gold 차감 안 함) — 스왑 확정 시점에 결제한다.
            #   그때 /api/inventory/swap이 이 티켓을 확인해야만 처리되므로
            #   결제 없이 임의의 아이템을 얻는 경로가 되지 않는다.
            ticket_id = _register_pending_swap(gs, item_id, source="shop", price=price)
            return jsonify({"ok": False, "error": "특수 아이템 칸이 가득 찼습니다.",
                           "reason": "special_full", "ticket_id": ticket_id,
                           "candidates": result.get("candidates", [])}), 400
        if reason == "potion_full":
            ticket_id = _register_pending_swap(gs, item_id, source="shop", price=price)
            return jsonify({"ok": False,
                           "error": "포션 슬롯이 가득 찼습니다. 기존 포션을 사용한 뒤 구매하세요.",
                           "reason": "potion_full", "ticket_id": ticket_id,
                           "candidates": result.get("candidates", [])}), 400
        return jsonify({"ok": False, "error": result.get("message", "인벤토리 가득 참")}), 400

    gs["gold"]  = gold - price
    gs["items"] = inv.to_flat_list()

    return jsonify({
        "ok":        True,
        "message":   f"{item_id} 구매! (-{price}G)",
        "gold":      gs["gold"],
        "player":    _player_dict(gs["player"], inv),
        "shop_items": _shop_items_for(gs["player"]),  # 상점 UI 재렌더용
    })
