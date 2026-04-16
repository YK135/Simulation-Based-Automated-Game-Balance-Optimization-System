from __future__ import annotations
import sys, os, time


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
        if key == 'n':   return
        elif key == 'y': sys.exit()
        else:            print("Y 또는 N을 입력하세요.")


def Trun_interface(tn: int = 0, player=None):
    clear()
    if player is not None:
        print("=" * 45)
        print("  진행: " + str(tn) + "/50턴" +
              "  |  Lv." + str(player.lv) +
              "  HP:" + str(int(player.hp)) + "/" + str(int(player.maxhp)) +
              "  MP:" + str(int(player.mp)) + "/" + str(int(player.maxmp)))
        print("=" * 45)
    print("*********************************************\n"
          "* 1. 앞으로 나아간다    2. 상태             *\n"
          "* 3. 아이템             4. 종료             *\n"
          "* g. 시뮬 그래프                            *\n"
          "*********************************************\n")


def Rest_Area():
    clear()
    print("*********************************************\n"
          "*                 쉼터 발견                 *\n"
          "*   1. 쉬어간다(Hp회복)     2. 수련한다     *\n"
          "*********************************************\n")


# ── HP/MP 바 ─────────────────────────────────────────
def _bar(current: float, maximum: float, width: int = 20,
         fill_char: str = "█", empty_char: str = "░") -> str:
    ratio  = max(0.0, min(1.0, current / max(maximum, 1)))
    filled = int(ratio * width)
    empty  = width - filled
    return "[" + fill_char * filled + empty_char * empty + "]"


def Battle_interface(player=None, enemy=None):
    clear()
    SEP = "  " + "─" * 42

    # 적 HP
    if enemy is not None:
        e_max = int(getattr(enemy, 'maxhp', enemy.hp))
        e_bar = _bar(enemy.hp, e_max)
        print("  [" + enemy.name + "  Lv." + str(enemy.lv) + "]")
        print("  HP " + e_bar +
              str(int(enemy.hp)).rjust(6) + " / " + str(e_max))
        print(SEP)

    # 플레이어 HP / MP
    if player is not None:
        p_bar  = _bar(player.hp, player.maxhp)
        mp_bar = _bar(player.mp, player.maxmp,
                      fill_char="▒", empty_char="░")
        print("  [" + player.name + "  Lv." + str(player.lv) + "]")
        print("  HP " + p_bar +
              str(int(player.hp)).rjust(6) + " / " + str(int(player.maxhp)))
        print("  MP " + mp_bar +
              str(int(player.mp)).rjust(6) + " / " + str(int(player.maxmp)))
        print(SEP)

    print("\n  ************************\n"
          "  * 1.공격      2.스킬  *\n"
          "  * 3.아이템    4.내상태*\n"
          "  * 5.적상태    6.도망  *\n"
          "  * a.자동전투          *\n"
          "  ************************\n")


def show_enemy_status(enemy):
    clear()
    print("  ――  " + enemy.name + " 상태  " + "―" * 28)
    print("  Lv    : " + str(enemy.lv))
    print("  HP    : " + str(int(enemy.hp)) +
          " / " + str(int(getattr(enemy, 'maxhp', enemy.hp))))
    print("  STG   : " + str(round(float(enemy.stg), 1)))
    print("  ARM   : " + str(round(float(enemy.arm), 1)))
    print("  SPD   : " + str(round(float(getattr(enemy, 'spd', 10)), 1)))
    print("  " + "―" * 38)


def Player_Deth():
    clear()
    print("  ##### 플레이어가 쓰러졌습니다... #####\n")
    print("  ##################################\n"
          "  #     다시 도전하시겠습니까?     #\n"
          "  #                                #\n"
          "  #     예(Y)        아니오(N)     #\n"
          "  ##################################\n")