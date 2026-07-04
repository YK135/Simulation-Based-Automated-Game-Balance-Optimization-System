# -*- coding: utf-8 -*-
"""
test_reward_drops.py — 전투 보상(골드+드랍) 검증
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 test_reward_drops.py
"""
import sys

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


from game.Rewards import calc_battle_rewards as calc


class E:
    def __init__(self, diff="", grade=""):
        self.name = "몹"
        if diff:
            self.difficulty = diff
        if grade:
            self.grade = grade


def main():
    print("=" * 52)
    print(" 전투 보상 시스템 검증 (골드 + 아이템 드랍)")
    print("=" * 52)

    print("\n[골드 범위/다중 보정]")
    g = [calc([E("easy")])["gold"] for _ in range(2000)]
    check("하 1마리: 10~15", min(g) == 10 and max(g) == 15, f"{min(g)}~{max(g)}")
    g = [calc([E("normal")])["gold"] for _ in range(2000)]
    check("중 1마리: 16~20", min(g) == 16 and max(g) == 20, f"{min(g)}~{max(g)}")
    g = [calc([E("hard")])["gold"] for _ in range(2000)]
    check("상 1마리: 21~30", min(g) == 21 and max(g) == 30, f"{min(g)}~{max(g)}")
    g = [calc([E("normal"), E("normal")], "battle")["gold"] for _ in range(3000)]
    check("중 2마리 ×1.05: 33~42", min(g) >= 33 and max(g) <= 42, f"{min(g)}~{max(g)}")
    g = [calc([E("easy")] * 3)["gold"] for _ in range(3000)]
    check("하 3마리 ×1.10: 33~49", min(g) >= 33 and max(g) <= 49, f"{min(g)}~{max(g)}")

    print("\n[드랍률 (실측)]")
    N = 20000
    res = [calc([E("easy")]) for _ in range(N)]
    pot = sum(1 for r in res if any(i.endswith("_potion") for i in r["items"])) / N * 100
    spc = sum(1 for r in res if any(not i.endswith("_potion") for i in r["items"])) / N * 100
    check(f"score1 포션 ~10% (실측 {pot:.1f})", 8.5 < pot < 11.5)
    check(f"score1 특수 ~6% (실측 {spc:.1f})", 4.8 < spc < 7.2)
    res = [calc([E("hard")] * 3) for _ in range(N)]
    pot = sum(1 for r in res if any(i.endswith("_potion") for i in r["items"])) / N * 100
    spc = sum(1 for r in res if any(not i.endswith("_potion") for i in r["items"])) / N * 100
    check(f"score9 포션 상한 45% (실측 {pot:.1f})", 43 < pot < 47)
    check(f"score9 특수 상한 20% (실측 {spc:.1f})", 18.5 < spc < 21.5)

    print("\n[엘리트 — node_type=='elite'일 때만]")
    g = [calc([E("hard")], "battle")["gold"] for _ in range(2000)]
    check("hard + battle 노드 → 일반 보상 (21~30)", min(g) == 21 and max(g) == 30, f"{min(g)}~{max(g)}")
    g = [calc([E("hard")], "elite")["gold"] for _ in range(2000)]
    check("elite 1마리: 45~60", min(g) == 45 and max(g) == 60, f"{min(g)}~{max(g)}")
    g = [calc([E("hard")] * 2, "elite")["gold"] for _ in range(2000)]
    check("elite 2마리: 70~90", min(g) == 70 and max(g) == 90, f"{min(g)}~{max(g)}")
    res = [calc([E("hard")], "elite") for _ in range(N)]
    check("elite 포션 확정 1개", all(any(i.endswith("_potion") for i in r["items"]) for r in res))
    pool = set()
    for r in res:
        pool.update(i for i in r["items"] if i.endswith("_potion"))
    check("elite 포션 풀 = 중형 이상만",
          pool <= {"HP_M_potion", "MP_M_potion", "HP_L_potion", "MP_L_potion"}, str(pool))
    spc = sum(1 for r in res if len(r["items"]) > 1) / N * 100
    check(f"elite 특수 25~35% (실측 {spc:.1f})", 27 < spc < 33)

    print("\n[형식/엣지]")
    r = calc([E("easy")], "battle")
    check("반환 키 gold/items/relics/messages", set(r.keys()) == {"gold", "items", "relics", "messages"})
    check("relics 항상 [] (유물 자리)", r["relics"] == [])
    check("골드 메시지 존재", any("골드" in m for m in r["messages"]))
    check("빈 defeated → 0 보상", calc([], "battle") == {"gold": 0, "items": [], "relics": [], "messages": []})
    check("grade 폴백 (difficulty 없음, grade='상')",
          21 <= calc([E(grade="상")])["gold"] <= 30)

    print("\n[Battle.py 연결 검사 (소스)]")
    import inspect
    import app.Battle as AB
    src = inspect.getsource(AB._finish_battle)
    win_block = src.split('winner == "player"')[1].split('elif')[0]
    check("보상 호출은 승리 분기 안에만 (패배/도망 무보상)",
          "calc_battle_rewards" in win_block
          and src.count("calc_battle_rewards") == win_block.count("calc_battle_rewards"))
    check("보스 전투 제외 (중간보스 중복 지급 방지)", "is_boss" in win_block)
    check("relics_gained 필드", "relics_gained" in src)
    check("battle_node_type 초기화", 'pop("battle_node_type"' in src)
    check("gold_gained/items_gained는 데이터, 로그는 messages",
          'result["messages"].extend(rw["messages"])' in src)

    # ── 지급 순서 검사 (재반영이 보상을 덮어쓰지 않게) ──
    i_reapply = src.index("Inventory 재반영")
    i_reward  = src.index("calc_battle_rewards(")
    i_boss    = src.index("중간 보스 클리어 보상")
    i_player  = src.index('result["player"] = _player_dict')
    i_db      = src.index("_save_battle_to_db(")
    check("순서: 재반영 → 보상 지급 (보상이 안 덮임)", i_reapply < i_reward)
    check("순서: 재반영 → 중간보스 HP_L (안 덮임)", i_reapply < i_boss)
    check("순서: 모든 보상 → player 스냅샷 → DB 저장", i_boss < i_player < i_db)
    check("items_gained = 성공분만 (gained 리스트)",
          'result["items_gained"]  = gained' in src)
    check("실패는 메시지로만 (놓쳤다)", "놓쳤다" in src)

    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()