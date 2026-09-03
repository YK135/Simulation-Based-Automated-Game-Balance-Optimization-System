# -*- coding: utf-8 -*-
"""
test_after_battle_feedback.py — 패배 시 AI 복기 피드백 배선 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_after_battle_feedback.py

검증 대상 (이번에 새로 연결한 것 — "프로젝트 정체성" 재정리 후 실전 배선):
  core/Balance_Hook.py의 BalanceHook.after_battle()이
  BehaviorAnalyzer/FeedbackEngine으로 실제 FeedbackReport를 만들어 반환하고,
  app/Battle.py의 _finish_battle()이 패배(winner=="enemy") 시 이걸 호출해서
  result["feedback"]에 담는지 확인한다. 이전엔 after_battle() 자체가 게임
  어디서도 호출되지 않는 죽은 경로였다 — 이 테스트가 그 회귀를 잠근다.

방식:
  1) BalanceHook.after_battle()을 BattleResult로 직접 호출 — 승리/패배 각각
     반환값이 기대대로인지(승리=None, 패배=FeedbackReport) 단위 검증.
  2) 실제 BattleSession을 만들어 패배 상태로 강제 전이시킨 뒤
     app/Battle.py의 _finish_battle()을 직접 호출해서 result["feedback"]이
     실제로 채워지는지 통합 검증 (전체 배선 확인).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def _make_hook():
    from game.Player_Class import create_player_by_job
    from game.Inventory import Inventory
    from core.Balance_Hook import BalanceHook

    player = create_player_by_job("피드백테스터", "전사")
    inv = Inventory.new()
    hook = BalanceHook(player, inv.to_flat_list(), show_graph=False, verbose=False)
    return player, hook


def _make_battle_result(winner, logs=None):
    from ai.battle import BattleResult, TurnLog

    if logs is None:
        logs = [
            TurnLog(turn=1, actor="player", action="attack", action_detail="",
                    damage_dealt=30, is_crit=False, escaped=False),
            TurnLog(turn=2, actor="enemy", action="attack", action_detail="",
                    damage_dealt=20, is_crit=False, escaped=False),
        ]
    return BattleResult(
        winner=winner,
        total_turns=len(logs),
        logs=logs,
        final_player_hp=(120 if winner == "player" else 0),
        final_enemy_hp=(0 if winner == "player" else 40),
        player_name="피드백테스터",
        enemy_name="고블린",
        final_player_items=[],
    )


def test_after_battle_unit():
    print("\n[BalanceHook.after_battle() 단위 검증]")
    player, hook = _make_hook()

    win_result = _make_battle_result("player")
    report = hook.after_battle(win_result)
    check("승리 시 after_battle() → None (피드백 생성 안 함)", report is None,
          f"report={report}")

    lose_result = _make_battle_result("enemy")
    report = hook.after_battle(lose_result)
    check("패배 시 after_battle() → FeedbackReport 반환", report is not None)
    if report:
        check("score가 0~100 범위", 0 <= report.score <= 100, f"score={report.score}")
        check("headline 비어있지 않음", bool(report.headline), f"headline={report.headline!r}")
        check("good_plays/bad_plays/suggestions가 list",
              isinstance(report.good_plays, list) and isinstance(report.bad_plays, list)
              and isinstance(report.suggestions, list))


def test_finish_battle_wiring():
    print("\n[app/Battle.py _finish_battle() 전체 배선 검증]")
    from ai.battle import EntitySnapshot
    from ai.Battlesession import BattleSession
    from game.Enemy_Class import Make_Goblin
    from app.Battle import _finish_battle
    from app.Shared import _player_to_snap

    player, hook = _make_hook()
    from game.Inventory import Inventory
    inv = Inventory.new()

    player_snap = _player_to_snap(player, inv)
    enemy_snap = EntitySnapshot.from_enemy(Make_Goblin(1, "중"))

    battle = BattleSession(
        player_snap,
        enemy=enemy_snap,
        items=inv.to_flat_list(),
        is_boss=False,
        enemy_origins=[Make_Goblin(1, "중")],
        player_original=player,
    )

    # 최소 한 번 실제 행동을 밟아서 logs를 채운 뒤(피드백 분석 대상),
    # 플레이어 차례에 HP를 0으로 만들어 패배로 강제 전이.
    # (Battlesession.py: 플레이어 차례 시작 시 hp<=0이면 즉시 winner="enemy" 확정)
    state = battle.step("status") if hasattr(battle, "step") else None
    na, _ = battle._peek_next_actor()
    if na == "enemy":
        battle.step("auto")
        na, _ = battle._peek_next_actor()

    battle.player.hp = 0
    battle.step("attack")  # 플레이어 차례 시작 → hp<=0 감지 → done/winner 확정

    check("BattleSession이 패배로 확정됨", battle.done and battle.winner == "enemy",
          f"done={battle.done}, winner={battle.winner}")

    gs = {
        "player": player,
        "inventory": inv,
        "hook": hook,
        "db_user_id": None,   # 게스트 — DB 요약 저장은 스킵되지만 RL 로그는 저장됨
        "gold": 100,
    }
    result = {}
    _finish_battle(gs, battle, result, "enemy")

    check("result에 feedback 키가 채워짐", "feedback" in result, f"result keys={list(result.keys())}")
    if "feedback" in result:
        fb = result["feedback"]
        check("feedback.score가 0~100", 0 <= fb.get("score", -1) <= 100, f"fb={fb}")
        check("feedback.headline 존재", bool(fb.get("headline")), f"fb={fb}")
        check("feedback에 good_plays/bad_plays/suggestions 키 존재",
              all(k in fb for k in ("good_plays", "bad_plays", "suggestions")))
    check("gs['battle']가 정리됨(None)", gs["battle"] is None)


def main():
    print("=" * 50)
    print(" 패배 시 AI 복기 피드백 배선 회귀 테스트")
    print("=" * 50)
    try:
        test_after_battle_unit()
        test_finish_battle_wiring()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        print(f"\n  ❌ 테스트 실행 중 예외: {ex}")
        sys.exit(2)
    print("\n" + "=" * 50)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 50)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
