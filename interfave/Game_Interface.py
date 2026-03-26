import sys
import os

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def GameEmdKey():
    clear()
    print("******************************\n"
          "*     게임을 종료합니까?     *\n"
          "*                            *\n"
          "*    확인[Y]   아니요[N]     *\n"
          "******************************\n")
    while True:
        key = input("입력: ").strip().lower()
        if key == 'n': return
        elif key == 'y': sys.exit()
        else: print("Y 또는 N을 입력하세요.")

def Trun_interface():
    clear()
    print("*********************************************\n"
          "* 1. 앞으로 나아간다    2. 상태             *\n"
          "* 3. 아이템             4. 종료             *\n"
          "* a. 자동 전투          g. 시뮬 그래프      *\n"
          "*********************************************\n")

def Rest_Area():
    clear()
    print("*********************************************\n"
          "*                 쉼터 발견                 *\n"
          "*   1. 쉬어간다(Hp회복)     2. 수련한다     *\n"
          "*********************************************\n")

def Battle_interface(player=None, enemy=None):
    """
    전투 UI 출력.
    player, enemy 전달 시 현재 HP/MP 상태바 표시.
    clear() 제거 — 행동 결과가 보이도록 유지.
    """
    # ── HP/MP 상태바 ──
    if player and enemy:
        p_hp_bar = _hp_bar(player.hp, player.maxhp, 15)
        e_hp_bar = _hp_bar(enemy.hp,  getattr(enemy, 'maxhp', enemy.hp), 15)
        print("\n" + "─" * 44)
        print(f"  {player.name:<10} HP {p_hp_bar} {int(player.hp):>4}/{int(player.maxhp)}"
              f"  MP {int(player.mp):>3}/{int(player.maxmp)}")
        print(f"  {enemy.name:<10} HP {e_hp_bar} {int(enemy.hp):>4}/{int(getattr(enemy,'maxhp',enemy.hp))}")
        print("─" * 44)

    # ── 빈 줄 간격 후 기존 스타일 메뉴 ──
    print()
    print("************************\n"
          "* 1. 공격      2. 스킬 *\n"
          "* 3. 아이템    4. 상태 *\n"
          "* 5. 적 상태   6. 도망 *\n"
          "************************\n")

def _hp_bar(current, maximum, width=15) -> str:
    """HP 시각적 바 생성"""
    if maximum <= 0:
        return "█" * width
    ratio  = max(0.0, min(1.0, current / maximum))
    filled = int(ratio * width)
    bar    = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"

def show_enemy_status(enemy):
    """적 상태창 출력"""
    print("\n" + "─" * 35)
    print(f"  ── {enemy.name} 상태 ──")
    maxhp = getattr(enemy, 'maxhp', enemy.hp)
    print(f"  Lv  : {enemy.lv}")
    print(f"  HP  : {int(enemy.hp)} / {int(maxhp)}")
    print(f"  STG : {enemy.stg}")
    print(f"  ARM : {enemy.arm}")
    print(f"  SPD : {getattr(enemy, 'spd', '?')}")
    # 활성 디버프
    debuffs = getattr(enemy, 'debuffs', [])
    if debuffs:
        print("  [디버프]")
        stat_map = {"arm": "방어력", "sparm": "마법방어력",
                    "stg": "공격력", "spd": "스피드"}
        for d in debuffs:
            print(f"    {d.name}: {stat_map.get(d.stat, d.stat)} "
                  f"-{int(d.amount*100)}% ({d.turns}턴)")
    print("─" * 35)

def Player_Deth():
    clear()
    print("##### 플레이어가 쓰러졌습니다... #####\n")
    print("##################################\n"
          "#     다시 도전하시겠습니까?     #\n"
          "#                                #\n"
          "#     예(Y)        아니오(N)     #\n"
          "##################################\n")