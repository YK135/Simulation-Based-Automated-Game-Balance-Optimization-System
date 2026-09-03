# -*- coding: utf-8 -*-
"""
test_log_manager_path_safety.py — ai/LOG_Manager.py 경로 순회 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_log_manager_path_safety.py

검증 대상 (전체 코드베이스 보안 리뷰에서 발견·수정된 취약점 잠금용):
  result.player_name(플레이어가 /api/new_game에 직접 입력하는 닉네임,
  검증 없이 그대로 저장됨 — app/Game.py 참고)이 LogManager.save_sim_log()/
  save_player_log()에서 검증 없이 파일명 f-string에 들어가고 있었다.
  "../../etc/passwd" 같은 이름을 쓰면 os.path.join이 이를 막아주지 않아
  data/Simul_LOG, data/Player_LOG 바깥 임의 경로에 파일을 쓸 수 있었음
  (get_enemy() → BalanceHook._cache_sim_log()를 통해 몬스터를 만날 때마다
  자동으로 실행되는, 인증 없이 도달 가능한 경로).

  수정: _safe_filename_part()로 파일명에 쓰기 전 위험 문자를 치환하고,
  _safe_join()으로 최종 경로가 실제로 SIM_DIR/PLAYER_DIR 바깥으로
  벗어나지 않는지 2중으로 확인.

방식:
  실제 LogManager.save_player_log()를 악의적인 player_name으로 호출하고,
  결과 파일이 반드시 PLAYER_DIR 내부에만 생성되는지 확인. 정상적인 한글/
  영문 이름은 여전히 읽기 좋은 파일명으로 저장되는지도 함께 확인(회귀 방지).
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


def _make_result(player_name, enemy_name="고블린"):
    from ai.battle import BattleResult
    return BattleResult(
        winner="player",
        total_turns=3,
        logs=[],
        final_player_hp=100,
        final_enemy_hp=0,
        player_name=player_name,
        enemy_name=enemy_name,
        final_player_items=[],
    )


def test_malicious_names_stay_inside_player_dir():
    print("\n[악의적인 player_name → PLAYER_DIR 바깥 탈출 시도]")
    from ai.LOG_Manager import LogManager, PLAYER_DIR

    lm = LogManager()
    real_player_dir = os.path.realpath(PLAYER_DIR)

    malicious_names = [
        "../../../../../../../tmp/pwned",
        "../../etc/passwd",
        "..\\..\\windows\\system32\\evil",
        "a/b/../../../c",
        "/etc/passwd",
    ]

    created_paths = []
    for name in malicious_names:
        result = _make_result(name)
        path = lm.save_player_log(result=result, player_lv=1)
        created_paths.append(path)
        real_path = os.path.realpath(path)
        inside = os.path.commonpath([real_player_dir, real_path]) == real_player_dir
        check(f"악의적 이름 {name!r} → 저장 경로가 PLAYER_DIR 내부",
              inside, f"path={real_path}")

    # 정리
    for p in created_paths:
        for ext_path in (p, p.replace(".json", ".txt")):
            try:
                os.remove(ext_path)
            except FileNotFoundError:
                pass


def test_normal_names_still_readable():
    print("\n[정상적인 이름 — 회귀 방지: 여전히 읽기 좋은 파일명]")
    from ai.LOG_Manager import LogManager, PLAYER_DIR

    lm = LogManager()
    for name in ["홍길동", "Hero123", "용사_A"]:
        result = _make_result(name)
        path = lm.save_player_log(result=result, player_lv=5)
        base = os.path.basename(path)
        check(f"정상 이름 {name!r}가 파일명에 그대로 보존됨",
              name in base or name.replace(" ", "_") in base, f"base={base}")
        for ext_path in (path, path.replace(".json", ".txt")):
            try:
                os.remove(ext_path)
            except FileNotFoundError:
                pass


def test_safe_filename_part_helper():
    print("\n[_safe_filename_part 단위 동작]")
    from ai.LOG_Manager import _safe_filename_part

    check("경로 구분자 제거", "/" not in _safe_filename_part("a/b/c"))
    check("빈 문자열 → fallback", _safe_filename_part("", "player") == "player")
    # ★ 예전엔 "or" 두 분기 중 첫 번째가 늘 참이라(반환값 "player"엔 ".."이
    #   없음) 두 번째 분기(실제 계약)가 검증되지 않는 죽은 코드였음 — sanitizer가
    #   나중에 약해져서 ".." 일부가 남아도("_.") 이 테스트가 못 잡았을 것.
    #   실제로 확인해야 하는 것 하나만 직접 단언.
    check("경로순회 문자열('..') → fallback으로 대체됨",
          _safe_filename_part("..", "player") == "player")
    check("길이 제한 적용", len(_safe_filename_part("a" * 100)) <= 40)


def main():
    print("=" * 50)
    print(" LOG_Manager 경로 순회 회귀 테스트")
    print("=" * 50)
    try:
        test_malicious_names_stay_inside_player_dir()
        test_normal_names_still_readable()
        test_safe_filename_part_helper()
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
