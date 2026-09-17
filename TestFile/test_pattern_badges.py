# -*- coding: utf-8 -*-
"""
test_pattern_badges.py — 엘리트 패턴 UI 배지(표시 전용 파생값) 검증
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_pattern_badges.py

검증 항목:
  1. 일반 몬스터·엘리트가 아닌 개체에는 배지가 안 붙는다
  2. 박쥐/암살자 — 카운터가 차오르고, 예고되면 armed로 뒤집힌다
  3. 화염/번개 슬라임 — 스택 게이지
  4. 골렘 — 3단계 사이클 + 그로기(엘리트가 아니어도 그로기는 나온다)
  5. 사제 — 부활 의식 준비 중에만, 이미 썼으면 안 나온다
  6. ★ 배지 계산이 엔티티를 절대 수정하지 않는다 (밸런스 불변 보장)
  7. 실제 _state() 응답의 enemies[i]에 pattern 키가 실린다
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.battle.Entity import EntitySnapshot                      # noqa: E402
from ai.battle_session.State import StateMixin                   # noqa: E402

badges_of = StateMixin._pattern_badges

_ok = _fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"✅ {label}")
    else:
        _fail += 1
        print(f"❌ {label}")


def mob(enemy_type, **kw):
    base = dict(name=enemy_type, hp=100, maxhp=100, mp=0, maxmp=0,
                stg=10, arm=5, sparm=5, sp=5, luc=5, lv=10,
                enemy_type=enemy_type)
    base.update(kw)
    return EntitySnapshot(**base)


def one(en):
    """배지 1개를 기대하는 경우 그 배지를 꺼낸다."""
    b = badges_of(en)
    assert len(b) == 1, f"배지 {len(b)}개: {b}"
    return b[0]


print("\n── 1. 배지가 안 붙어야 하는 경우 ──")
check(badges_of(mob("고블린")) == [], "일반 고블린 — 배지 없음")
check(badges_of(mob("박쥐")) == [], "엘리트가 아닌 박쥐 — 배지 없음")
check(badges_of(mob("화염 슬라임", elite_pattern_turn=2)) == [],
      "엘리트가 아닌 화염 슬라임 — 스택이 있어도 배지 없음")

print("\n── 2. 예고형 (박쥐 / 암살자) ──")
b = one(mob("박쥐", elite_leader=True, elite_pattern_turn=1))
check(b["kind"] == "telegraph" and b["label"] == "초음파비명",
      f"박쥐 — 예고형 배지 '{b['label']}'")
check((b["cur"], b["max"], b["state"]) == (1, 3, "charging"),
      f"박쥐 1/3 charging (실제 {b['cur']}/{b['max']} {b['state']})")

b = one(mob("박쥐", elite_leader=True, elite_phase=1, elite_pattern_turn=0))
check((b["cur"], b["max"], b["state"]) == (3, 3, "armed"),
      f"박쥐 예고 직후(phase 1) — 카운터가 0이어도 3/3 armed (실제 {b['cur']}/{b['max']} {b['state']})")

b = one(mob("박쥐", elite_leader=True, elite_phase=2))
check(b["state"] == "armed", "박쥐 발동 대기(phase 2) — 여전히 armed")

b = one(mob("암살자", elite_leader=True, elite_pattern_turn=2))
check(b["label"] == "암살 표식" and (b["cur"], b["max"]) == (2, 3),
      f"암살자 — '암살 표식' 2/3 (실제 {b['label']} {b['cur']}/{b['max']})")

b = one(mob("박쥐", elite_leader=True, elite_pattern_turn=99))
check(b["cur"] == 3, "카운터가 임계치를 넘어도 칸 수를 넘지 않는다")

print("\n── 3. 스택형 (화염 / 번개 슬라임) ──")
b = one(mob("화염 슬라임", elite_leader=True, elite_pattern_turn=1))
check(b["kind"] == "stack" and (b["cur"], b["max"], b["state"]) == (1, 3, "charging"),
      f"화염 슬라임 1/3 charging (실제 {b['cur']}/{b['max']} {b['state']})")
b = one(mob("화염 슬라임", elite_leader=True, elite_pattern_turn=2))
check(b["state"] == "armed", "화염 슬라임 2/3 — 다음 피격에 터지므로 armed")
b = one(mob("번개 슬라임", elite_leader=True, elite_pattern_turn=3))
check(b["label"] == "과부하 전격" and b["state"] == "armed", "번개 슬라임 3/3 armed")

print("\n── 4. 골렘 (사이클 + 그로기) ──")
bs = badges_of(mob("골렘", elite_leader=True, elite_phase=2, physical_hit_streak=1))
check(len(bs) == 2, f"엘리트 골렘 — 사이클 + 그로기 2개 (실제 {len(bs)}개)")
cyc = next(x for x in bs if x["kind"] == "cycle")
gro = next(x for x in bs if x["kind"] == "groggy")
check(cyc["label"] == "강타" and cyc["state"] == "armed",
      f"골렘 phase 2 — '강타' armed (실제 '{cyc['label']}' {cyc['state']})")
check((gro["cur"], gro["max"], gro["state"]) == (1, 2, "armed"),
      f"그로기 1/2 — 한 대 더면 발동 (실제 {gro['cur']}/{gro['max']} {gro['state']})")

cyc = next(x for x in badges_of(mob("골렘", elite_leader=True, elite_phase=0)) if x["kind"] == "cycle")
check(cyc["label"] == "수비 태세" and cyc["state"] == "idle", "골렘 phase 0 — 수비 태세 idle")
cyc = next(x for x in badges_of(mob("골렘", elite_leader=True, elite_phase=1)) if x["kind"] == "cycle")
check(cyc["label"] == "충전 예고" and cyc["state"] == "charging", "골렘 phase 1 — 충전 예고 charging")

b = one(mob("골렘"))
check(b["kind"] == "groggy" and b["cur"] == 0,
      "엘리트가 아닌 골렘 — 그로기 게이지만 나온다 (플레이어가 쌓는 값이므로)")

print("\n── 5. 사제 (부활 의식) ──")
check(badges_of(mob("사제", elite_leader=True, elite_phase=0)) == [],
      "사제 평시 — 배지 없음")
b = one(mob("사제", elite_leader=True, elite_phase=1))
check(b["label"] == "부활 의식" and b["state"] == "armed" and b["max"] == 1,
      "사제 의식 준비 중 — armed, 칸 없음(단발)")
check(badges_of(mob("사제", elite_leader=True, elite_phase=1, elite_pattern_used=True)) == [],
      "이미 부활을 쓴 사제 — 배지 없음")

print("\n── 6. 배지 계산이 엔티티를 수정하지 않는가 (밸런스 불변) ──")
WATCH = ("elite_phase", "elite_pattern_turn", "elite_pattern_used",
         "physical_hit_streak", "hp", "mp", "buffs", "debuffs")
for en in (mob("박쥐", elite_leader=True, elite_phase=1, elite_pattern_turn=2),
           mob("골렘", elite_leader=True, elite_phase=2, physical_hit_streak=1),
           mob("사제", elite_leader=True, elite_phase=1),
           mob("번개 슬라임", elite_leader=True, elite_pattern_turn=3)):
    before = {k: repr(getattr(en, k)) for k in WATCH}
    badges_of(en)
    badges_of(en)          # 두 번 불러도 같아야 한다
    after = {k: repr(getattr(en, k)) for k in WATCH}
    check(before == after,
          f"{en.enemy_type} — 배지 계산 전후 상태 동일 "
          f"{'' if before == after else [k for k in WATCH if before[k] != after[k]]}")

print("\n── 7. 실제 전투 응답에 pattern이 실리는가 ──")
from ai.Battlesession import BattleSession                       # noqa: E402
from game.Enemy_Class import Make_Golem                          # noqa: E402

# app/Battle.py의 _start_battle과 같은 형태 — BattleSession은 EntitySnapshot을 받는다
player_snap = EntitySnapshot(name="테스터", hp=800, maxhp=800, mp=60, maxmp=60,
                             stg=45, arm=24, sparm=15, sp=12, luc=11, lv=10,
                             spd=18, job="전사")
golem_snap = EntitySnapshot.from_enemy(Make_Golem(10, "상"))
golem_snap.elite_leader = True
golem_snap.elite_phase  = 2                # 강타 대기(예고 완료) 상태로 고정
golem_snap.physical_hit_streak = 1
sess = BattleSession(player_snap, golem_snap)
st = sess.step("status")
pat = st["enemies"][0].get("pattern")
check(isinstance(pat, list) and len(pat) == 2,
      f"_state().enemies[0].pattern — 배지 2개 (실제 {pat!r})")
check(any(x["kind"] == "cycle" and x["state"] == "armed" for x in (pat or [])),
      "전투 응답에서도 골렘 강타가 armed로 보인다")

print(f"\n{'─' * 46}\n총 {_ok + _fail}건 — 성공 {_ok} / 실패 {_fail}")
sys.exit(1 if _fail else 0)
