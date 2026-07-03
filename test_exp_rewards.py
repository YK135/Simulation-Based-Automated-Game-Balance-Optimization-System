# -*- coding: utf-8 -*-
"""
test_exp_rewards.py — 경험치 보상 시스템 검증
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 test_exp_rewards.py

검증 항목 (player.maxexp = 100 기준):
  1대1: 하 45 / 중 55 / 상 80
  1대2 (×0.90): 하하 81 / 하중 90 / 하상 112 / 중중 99 / 중상 121 / 상상 144
  1대3 (×0.75): 하하하 101 / 하하중 108 / 하중중 116 / 중중중 123
  보스: 중간 보스 100 / 최종 보스 0
  fallback: exp_reward 없음 → difficulty(easy/normal/hard) → grade → 기본 중
  defeated_origins 우선 / battle.enemies 폴백
  실제 Enemy_Class.Unit.exp_reward와의 일치
"""
import sys

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \u2705 {name}")
    else:
        FAIL += 1
        print(f"  \u274c {name}  {detail}")


# ── app/Battle.py의 계산 함수 ──
from app.Battle import _enemy_exp, _calc_victory_exp


class FakeUnit:
    """exp_reward를 가진 원본 Unit 흉내 (grade 기반)."""
    _R = {"상": 0.80, "중": 0.55, "하": 0.45}
    def __init__(self, grade="중", name="몹"):
        self.name = name
        self.grade = grade
        self.hp = 0
    def exp_reward(self, player_maxexp):
        return int(player_maxexp * self._R[self.grade])


class FakeSnap:
    """exp_reward 없는 _SnapUnit/EntitySnapshot 흉내."""
    def __init__(self, difficulty="", grade="", name="몹"):
        self.name = name
        self.hp = 0
        if difficulty:
            self.difficulty = difficulty
        if grade:
            self.grade = grade


class FakePlayer:
    maxexp = 100


class FakeBattle:
    def __init__(self, defeated=None, enemies=None):
        self.defeated_origins = defeated or []
        self.enemies = enemies or []


def exp_of(*units):
    return _calc_victory_exp(FakePlayer(), FakeBattle(defeated=list(units)))


def test_spec_table():
    print("\n[명세 기대값 표 — maxexp=100]")
    U = FakeUnit
    cases = [
        ("1대1 하 45",   exp_of(U("하")), 45),
        ("1대1 중 55",   exp_of(U("중")), 55),
        ("1대1 상 80",   exp_of(U("상")), 80),
        ("1대2 하하 81",  exp_of(U("하"), U("하")), 81),
        ("1대2 하중 90",  exp_of(U("하"), U("중")), 90),
        ("1대2 하상 112", exp_of(U("하"), U("상")), 112),
        ("1대2 중중 99",  exp_of(U("중"), U("중")), 99),
        ("1대2 중상 121", exp_of(U("중"), U("상")), 121),
        ("1대2 상상 144", exp_of(U("상"), U("상")), 144),
        ("1대3 하하하 101", exp_of(U("하"), U("하"), U("하")), 101),
        ("1대3 하하중 108", exp_of(U("하"), U("하"), U("중")), 108),
        ("1대3 하중중 116", exp_of(U("하"), U("중"), U("중")), 116),
        ("1대3 중중중 123", exp_of(U("중"), U("중"), U("중")), 123),
        ("중간 보스 100", exp_of(FakeSnap(name="중간 보스")), 100),
        ("최종 보스 0",   exp_of(FakeSnap(name="최종 보스")), 0),
    ]
    for name, got, want in cases:
        check(name, got == want, f"got={got}")


def test_fallback():
    print("\n[fallback 우선순위]")
    check("difficulty=hard → 80", _enemy_exp(FakeSnap(difficulty="hard"), 100) == 80)
    check("difficulty=normal → 55", _enemy_exp(FakeSnap(difficulty="normal"), 100) == 55)
    check("difficulty=easy → 45", _enemy_exp(FakeSnap(difficulty="easy"), 100) == 45)
    check("difficulty 우선 (grade='중' 기본값 무시)",
          _enemy_exp(FakeSnap(difficulty="hard", grade="중"), 100) == 80)
    check("difficulty 없음 + grade='상' → 80",
          _enemy_exp(FakeSnap(grade="상"), 100) == 80)
    check("정보 없음 → 기본 중 55", _enemy_exp(FakeSnap(), 100) == 55)
    # exp_reward 최우선
    check("exp_reward 최우선", _enemy_exp(FakeUnit("상"), 100) == 80)


def test_origin_priority():
    print("\n[defeated_origins 우선 / enemies 폴백]")
    # origins 있으면 그것 사용
    b1 = FakeBattle(defeated=[FakeUnit("상")], enemies=[FakeSnap(difficulty="easy")])
    check("origins 우선 (상 80)", _calc_victory_exp(FakePlayer(), b1) == 80)
    # origins 비면 enemies 폴백
    b2 = FakeBattle(defeated=[], enemies=[FakeSnap(difficulty="easy"), FakeSnap(difficulty="normal")])
    check("enemies 폴백 (하+중 ×0.9 = 90)", _calc_victory_exp(FakePlayer(), b2) == 90)
    # 둘 다 비면 0
    check("둘 다 없음 → 0", _calc_victory_exp(FakePlayer(), FakeBattle()) == 0)
    # origins에 None 섞임 — 걸러짐
    b3 = FakeBattle(defeated=[None, FakeUnit("하"), None])
    check("None 필터링 (하 45)", _calc_victory_exp(FakePlayer(), b3) == 45)


def test_real_unit():
    print("\n[실제 Enemy_Class.Unit 일치]")
    try:
        from game.Enemy_Class import Make_Goblin
        for grade, want in [("하", 45), ("중", 55), ("상", 80)]:
            g = Make_Goblin(player_lv=3, grade=grade)
            check(f"고블린({grade}).exp_reward(100) == {want}",
                  g.exp_reward(100) == want, f"got={g.exp_reward(100)}")
            g.hp = 0
            check(f"고블린({grade}) 전투 exp == {want}", exp_of(g) == want)
    except Exception as ex:
        print(f"  \u26a0 Enemy_Class 로드 실패, 건너뜀: {str(ex)[:70]}")


def main():
    print("=" * 52)
    print(" 경험치 보상 시스템 검증 (난이도/마릿수 기반)")
    print("=" * 52)
    test_spec_table()
    test_fallback()
    test_origin_priority()
    test_real_unit()
    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()