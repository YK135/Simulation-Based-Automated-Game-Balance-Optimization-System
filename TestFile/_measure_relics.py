# -*- coding: utf-8 -*-
"""
_measure_relics.py — 보스 측정 스크립트가 공유하는 「유물을 들고 들어간다」 처리

`boss_measure.py` · `final_boss_measure.py`가 지금까지 잰 것은 **유물 0개**의 보스전이다.
실전에서는 엘리트 노드와 보스 승리마다 3종 중 1개를 고르고 상점에서도 사므로, 보스에
도착한 플레이어는 보통 유물 몇 개를 들고 있다. 이 모듈이 그 차이를 한 곳에서 만든다.

환경변수 `RELICS`:
  (없음) / "none"   유물 0개 — 지금까지의 기준선. **유물 모듈을 import조차 하지 않으므로**
                    유물이 없던 옛 트리(AI_RPG_ROOT 비교 실행)에서도 그대로 돌아간다.
  "<k>"             실전 제시 규칙(game/Relics.relic_choices — 3장 중 1장은 직업 전용)으로
                    k번 제시받아 **무작위로 하나씩** 고른 조합. 전투마다 시드로 다시 뽑는다.
                    무작위 선택이므로 이 숫자는 유물 효과의 **하한**이다(아는 플레이어는 더 센 걸 고른다).
  "id,id,…"         고정 조합. 특정 유물의 기여를 따로 보거나 "최적 선택"의 상한을 잴 때.
  "each"            호출부가 유물 하나씩 순회하는 진단 모드로 쓴다(여기서는 목록만 돌려준다).

유물을 스냅샷에 입히는 규칙은 `app/Shared._grant_relic`과 같아야 한다 —
① `relics` 목록 ② 「굶주린 칼날」의 최대 HP 대가(획득 시 1회) ③ 포션 슬롯 증감.
플레이어 객체는 건드리지 않고 **EntitySnapshot만** 고친다(측정 스크립트가 플레이어를
(직업,레벨)당 하나만 만들어 재사용하기 때문 — 원본을 깎으면 다음 셀로 샌다).
"""
from __future__ import annotations

import random


def spec_is_empty(spec: str) -> bool:
    return not spec or spec.strip().lower() in ("none", "0", "-")


def all_relic_ids(job: str = "") -> list:
    """진단용 — 이 직업이 가질 수 있는 유물 전부(공용 + 자기 직업 전용)."""
    from ai.battle.Relics import COMMON_RELIC_IDS, JOB_RELIC_IDS
    return list(COMMON_RELIC_IDS) + list(JOB_RELIC_IDS.get(job, ()))


def draw(spec: str, job: str, rng: random.Random) -> list:
    """RELICS 스펙 → 유물 id 목록. 빈 스펙이면 [] (유물 모듈을 부르지 않는다)."""
    if spec_is_empty(spec):
        return []
    spec = spec.strip()
    if spec.isdigit():
        from game.Relics import relic_choices
        owned = []
        for _ in range(int(spec)):
            picks = relic_choices(owned, job, rng_sample=rng.sample)
            if not picks:
                break
            owned.append(rng.choice(picks))      # 무작위 선택 = 효과의 하한
        return owned
    return [r.strip() for r in spec.split(",") if r.strip()]


def apply_to_snapshot(snap, relic_ids) -> None:
    """EntitySnapshot에 유물을 입힌다 — _grant_relic과 같은 순서/규칙."""
    if not relic_ids:
        return
    from ai.battle.Relics import relic_maxhp_cost_mult
    snap.relics = list(relic_ids)
    for rid in relic_ids:
        mult = relic_maxhp_cost_mult(rid)
        if mult < 1.0:
            snap.maxhp = max(1, int(snap.maxhp * mult))
    snap.hp = min(snap.hp, snap.maxhp)


def items_for(relic_ids, base_items) -> list:
    """포션 슬롯 증감(탐욕의 인장 −1 / 전리품 자루 +1)을 들고 가는 포션 수에 반영한다.
    슬롯이 늘면 첫 번째 포션을 하나 더 넣고, 줄면 뒤에서 하나 뺀다(최소 1개)."""
    items = list(base_items)
    if not relic_ids:
        return items
    from ai.battle.Relics import relic_potion_slot_penalty
    penalty = relic_potion_slot_penalty(relic_ids)
    while penalty > 0 and len(items) > 1:
        items.pop()
        penalty -= 1
    while penalty < 0:
        items.insert(0, items[0])
        penalty += 1
    return items


def label(spec: str) -> str:
    """표에 넣을 짧은 이름 — 고정 조합은 유물 id를 한글 이름으로 바꿔 준다."""
    spec = (spec or "").strip()
    if spec_is_empty(spec):
        return "유물없음"
    if spec.isdigit():
        return f"무작위{spec}개"
    try:
        from game.Relics import RELIC_META
        names = [RELIC_META[r.strip()]["name"] for r in spec.split(",")
                 if r.strip() in RELIC_META]
        if names:
            return "+".join(names)
    except Exception:
        pass
    return spec


# ─────────────────────────────────────────────
# python3 TestFile/_measure_relics.py — 보스에 도착할 때 유물을 몇 개 들고 있는가 +
# 이 모듈이 app/Shared._grant_relic과 같은 규칙을 쓰는지 자체 점검
# ─────────────────────────────────────────────
def _arrival_distribution(trials: int = 3000, chapter: int = 1, seed: int = 20260917):
    """한 챕터를 한 번 통과할 때 **실제로 밟는** 엘리트·상점 노드 수 분포.
    맵은 계층마다 갈래가 갈리므로 배치된 엘리트(1~3개)를 전부 밟지는 않는다 —
    "보스 앞에서 유물을 몇 개 들고 있나"의 근거가 되는 숫자다."""
    from collections import Counter
    from game.Map import FloorMap
    rng = random.Random(seed)
    elite, shop = Counter(), Counter()
    for _ in range(trials):
        fm = FloorMap.generate(chapter)
        nodes = fm.nodes
        start = [n for n in nodes.values() if n.layer == 0]
        cur, e, s, guard = (start[0] if start else None), 0, 0, 0
        while cur is not None and guard < 40:
            guard += 1
            nxt = [nodes[i] for i in cur.next_ids if i in nodes]
            if not nxt:
                break
            cur = rng.choice(nxt)
            e += cur.node_type == "elite"
            s += cur.node_type == "shop"
            if cur.node_type == "boss":
                break
        elite[e] += 1
        shop[s] += 1
    return elite, shop


if __name__ == "__main__":
    import os, sys, tempfile
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
    os.environ.setdefault("DATABASE_URL", "sqlite:///" + _db)

    elite, shop = _arrival_distribution()
    total = sum(elite.values())
    print("한 챕터를 통과하며 실제로 밟는 엘리트 노드 수")
    for k in sorted(elite):
        print(f"  {k}개 {100 * elite[k] / total:5.1f}%")
    print(f"  평균 {sum(k * v for k, v in elite.items()) / total:.2f}개 · "
          f"상점 평균 {sum(k * v for k, v in shop.items()) / total:.2f}개")
    print("→ 중간 보스 앞: 챕터1 엘리트만 = 유물 0~2개(0개가 최빈).")
    print("→ 최종 보스 앞: 챕터1 엘리트 + **중간 보스 보상 1개(확정)** + 챕터2 엘리트")
    print("   = 최소 1개, 보통 2~3개. 유물 0개인 최종 보스전은 실제로는 일어나지 않는다.")

    # 자체 점검 — _grant_relic과 같은 규칙인가
    from ai.battle.Relics import RELIC_HUNGRY_BLADE, HUNGRY_BLADE_MAXHP_COST

    class _S:
        maxhp = 1000.0; hp = 1000.0; relics = []
    s = _S()
    apply_to_snapshot(s, [RELIC_HUNGRY_BLADE])
    want = max(1, int(1000.0 * (1.0 - HUNGRY_BLADE_MAXHP_COST)))
    assert s.maxhp == want and s.hp == want, (s.maxhp, s.hp, want)
    assert items_for(["greed_seal"], ["a", "b", "c"]) == ["a", "b"]
    assert items_for(["loot_sack"], ["a", "b"]) == ["a", "a", "b"]
    assert items_for(["greed_seal", "loot_sack"], ["a", "b"]) == ["a", "b"]
    assert items_for([], ["a", "b"]) == ["a", "b"]
    assert draw("none", "전사", random.Random(1)) == []
    assert len(draw("3", "전사", random.Random(1))) == 3
    assert draw("iron_heart,greed_seal", "전사", random.Random(1)) == ["iron_heart", "greed_seal"]
    print("\n자체 점검 통과 — 굶주린 칼날 대가 · 포션 슬롯 증감 · 추첨 규칙")
    os.remove(_db)
