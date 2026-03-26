"""
Main.py
─────────────────────────────────────────────
메인 게임 루프 — 전체 시스템 연결 버전

연결된 시스템:
  - Balance_Hook  : 백그라운드 AI 시뮬 + 몬스터 밸런싱
  - Action_Class  : 전투 UI (공격/스킬/아이템/도망/상태창)
  - Enemy_Class   : 등급별 몬스터, 중간보스/최종보스
  - Lv            : 레벨업 (MP 비율 유지, 스킬 자동 해금)
  - Visualizer    : 시뮬 그래프 (g 키)

게임 구조:
  50턴 진행 / 25턴 중간보스 / 50턴 최종보스
  전투 확률 60% → 25~30회 전투 목표
"""

from random import randint, random
import sys
import os

# ── 패키지 경로 설정 ──────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
for _sub in ["game", "ai", "core", "interfave"]:
    _p = os.path.join(_ROOT, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.path.insert(0, _ROOT)

from game.Player_Class        import Player
from game.Enemy_Class         import Make_Random_Monster, Make_MidBoss, Make_FinalBoss
from game.Item                import Item_
from game.Lv                  import LV_
from game.Skill               import Ply_Skill
from interfave.Game_Interface import (
    clear, GameEmdKey, Trun_interface, Rest_Area,
    Battle_interface, Player_Deth, show_enemy_status
)
from core.Action_Class  import Act
from core.Balance_Hook  import BalanceHook


# ════════════════════════════════════════════
# 플레이어 초기화
# ════════════════════════════════════════════

def _init_player(name: str) -> Player:
    p = Player(name, 1, 100, 0,
               200, 200, 25, 25,
               7, 5, 5, 5, 10, 15)
    p.skill = Ply_Skill()
    return p


plname    = input("이름을 입력하세요. ------> ").strip() or "용사"
ply       = _init_player(plname)
pl_item   = ["HP_S_potion"]
item_list = ["HP_S_potion", "HP_M_potion", "HP_L_potion",
             "MP_S_potion", "MP_M_potion", "MP_L_potion"]

hook = BalanceHook(ply, pl_item, show_graph=False, verbose=True)
mid_boss_cleared = False


# ════════════════════════════════════════════
# 공통 유틸
# ════════════════════════════════════════════

def _give_exp(monster):
    lv_obj = LV_(ply)
    exp = monster.exp_reward(ply.maxexp) if hasattr(monster, 'exp_reward') else randint(45, 60)
    lv_obj.Get_exp(ply, reward_exp=exp)
    hook.check_level_up()


def _run_battle(enemy) -> str:
    """반환: 'win' | 'lose' | 'escaped'"""
    battle = Act(ply, enemy, pl_item)
    result = battle.action()
    if result == "escaped":
        return "escaped"
    if ply.hp <= 0:
        return "lose"
    return "win"


# ════════════════════════════════════════════
# 이벤트
# ════════════════════════════════════════════

def _event_battle():
    enemy_type = "고블린" if random() < 0.5 else "박쥐"
    enemy_snap = hook.get_enemy(enemy_type)
    enemy      = hook.make_battle_unit(enemy_snap)

    print(f"  {enemy.name}이(가) 나타났다!\n")
    result = _run_battle(enemy)

    if result == "win":
        print(f"\n  {enemy.name}을(를) 처치했다!\n")
        _give_exp(enemy)
    elif result == "escaped":
        print("\n  도망쳤다!\n")
    else:
        Game_over()


def _event_item():
    item = item_list[randint(0, len(item_list) - 1)]
    pl_item.append(item)
    print(f"\n  ✦ {item} 을(를) 획득했다!\n")


def _event_rest():
    Rest_Area()
    key = input("입력: ").strip()
    if key == '1':
        if ply.hp >= ply.maxhp:
            print("  이미 체력이 가득 찼습니다.\n")
        else:
            heal = min(int(ply.maxhp / 3), ply.maxhp - ply.hp)
            ply.hp += heal
            print(f"  체력 {heal} 회복! ({int(ply.hp)}/{int(ply.maxhp)})\n")
    elif key == '2':
        ratio    = 0.60 + random() * 0.20
        exp_gain = int(ply.maxexp * ratio)
        print(f"  수련으로 {exp_gain} 경험치 획득!\n")
        lv_obj = LV_(ply)
        lv_obj.Get_exp(ply, reward_exp=exp_gain)
        hook.check_level_up()
    else:
        print("  잘못된 선택입니다.\n")


def _event_midboss():
    global mid_boss_cleared
    clear()
    print("=" * 45)
    print("  ⚠️  중간 보스 등장!")
    print("=" * 45)
    print(f"\n  현재 Lv.{ply.lv}  HP:{int(ply.hp)}/{int(ply.maxhp)}\n")
    input("  [Enter]를 눌러 전투 시작...")

    cached = hook._get_cached_monsters("고블린")
    base   = cached.get("normal", (None, None))[0] if cached else None
    boss   = Make_MidBoss(ply.lv, base)
    print(f"\n  {boss.name} 등장! (HP: {boss.hp})\n")

    result = _run_battle(boss)
    if result == "win":
        print("\n  중간 보스를 처치했다!\n")
        mid_boss_cleared = True
        _give_exp(boss)
        pl_item.append("HP_L_potion")
        print("  보상: HP_L_potion 획득!\n")
    elif result == "escaped":
        print("\n  도망쳤다! 보스는 아직 남아있다...\n")
    else:
        Game_over()


def _event_finalboss():
    clear()
    print("=" * 45)
    print("  💀  최종 보스 등장!")
    print("=" * 45)

    if ply.lv < 30:
        print(f"\n  현재 레벨 {ply.lv} — 레벨 30 이상을 권장합니다.")
        print("  그래도 도전하시겠습니까? (Y/N)")
        while True:
            k = input("입력: ").strip().lower()
            if k == 'y':
                break
            elif k == 'n':
                print("  더 강해져서 돌아오세요!\n")
                return
            else:
                print("  Y 또는 N을 입력하세요.")

    print(f"\n  현재 Lv.{ply.lv}  HP:{int(ply.hp)}/{int(ply.maxhp)}\n")
    input("  [Enter]를 눌러 최종 전투 시작...")

    cached = hook._get_cached_monsters("고블린")
    base   = cached.get("hard", (None, None))[0] if cached else None
    boss   = Make_FinalBoss(ply.lv, base)
    print(f"\n  {boss.name} 등장! (HP: {boss.hp})\n")

    result = _run_battle(boss)
    if result == "win":
        clear()
        print("\n" + "=" * 45)
        print("  🎉  최종 보스 처치!")
        print("  당신은 세계를 구했습니다!")
        print("=" * 45)
        print(f"\n  {ply.name}  /  최종 Lv.{ply.lv}")
        print(f"  잔여 HP: {int(ply.hp)}/{int(ply.maxhp)}\n")
        sys.exit()
    else:
        print("\n  패배했습니다...\n")
        Game_over()


# ════════════════════════════════════════════
# 게임 오버 / 재시작
# ════════════════════════════════════════════

def Game_over():
    if ply.hp > 0:
        return
    Player_Deth()
    while True:
        k = input("입력: ").strip().lower()
        if k == 'y':
            Game_restart()
            break
        elif k == 'n':
            print("게임을 종료합니다.")
            sys.exit()
        else:
            print("Y 또는 N을 입력하세요.")


def Game_restart():
    global ply, pl_item, hook, mid_boss_cleared
    name    = input("\n[재시작] 이름을 다시 입력하세요 ------> ").strip() or "용사"
    ply     = _init_player(name)
    pl_item = ["HP_S_potion"]
    hook    = BalanceHook(ply, pl_item, show_graph=False, verbose=True)
    mid_boss_cleared = False
    print("\n게임을 다시 시작합니다!\n")
    Trun(0)


# ════════════════════════════════════════════
# 메인 루프
# ════════════════════════════════════════════

def Trun(tn: int):
    global mid_boss_cleared

    while True:
        Game_over()

        # 25턴: 중간 보스
        if tn == 25 and not mid_boss_cleared:
            _event_midboss()
            tn += 1
            input("\n[Enter]를 눌러 계속...")
            continue

        # 50턴: 최종 보스
        if tn >= 50:
            _event_finalboss()
            break

        Trun_interface()
        key = input("입력: ").strip().lower()

        if key == '4':
            GameEmdKey()

        elif key == '1':
            print("앞으로 나아갑니다.\n")
            rd = randint(1, 20)

            if   1 <= rd <= 12: _event_battle()   # 60% 전투
            elif 13 <= rd <= 15: _event_item()    # 15% 아이템
            elif 16 <= rd <= 17: _event_rest()    # 10% 휴식/수련
            else: print("  조용하다... 아무 일도 일어나지 않았다.\n")

            tn += 1
            warn = "  ⚠️  다음 턴 중간 보스!" if tn == 24 and not mid_boss_cleared else ""
            print(f"\n  진행: {tn}/50턴  |  Lv.{ply.lv}"
                  f"  HP:{int(ply.hp)}/{int(ply.maxhp)}"
                  f"  MP:{int(ply.mp)}/{int(ply.maxmp)}")
            if warn:
                print(warn)
            input("\n[Enter]를 눌러 계속...")

        elif key == '2':
            clear()
            ply.Show_Staters()
            if ply.skill:
                ply.skill.show_skills()
            input("[Enter] 계속...")

        elif key == '3':
            pi = Item_(ply, pl_item)
            pi.show_item()
            if not pl_item:
                input("[Enter] 계속...")
                continue
            print("사용할 아이템 번호 선택 (취소: q)")
            k2 = input("입력: ").strip()
            if k2.lower() == 'q':
                continue
            try:
                idx    = int(k2)
                unique = list(dict.fromkeys(pl_item))
                if 0 <= idx < len(unique):
                    pi.use_item(unique[idx])
                else:
                    print("잘못된 번호입니다.\n")
            except (ValueError, IndexError):
                print("잘못된 입력입니다.\n")

        # a: 자동 전투 (테스트용)
        elif key == 'a':
            print("  자동 전투 실행...\n")
            snap   = hook.get_enemy("고블린")
            result = hook.run_auto_battle(snap, show_log=True)
            hook.after_battle(result)
            input("[Enter] 계속...")

        # g: 시뮬 그래프
        elif key == 'g':
            print("  그래프 생성 중...\n")
            try:
                from ai.Visualizer import Visualizer
                viz      = Visualizer()
                monsters = hook._get_cached_monsters("고블린")
                if monsters:
                    viz.win_rate_bar(monsters, ply.name)
                else:
                    print("  시뮬레이션 완료 후 다시 시도하세요.\n")
            except Exception as e:
                print(f"  그래프 오류: {e}\n")
            input("[Enter] 계속...")

        else:
            print("  1~4, a(자동전투), g(그래프) 중 입력하세요.\n")


# ════════════════════════════════════════════
# 게임 시작
# ════════════════════════════════════════════

clear()
print(f"\n  환영합니다, {ply.name}님!")
print("  AI가 실력에 맞춰 몬스터를 자동 조정합니다.")
print("  백그라운드에서 밸런스 분석 중...\n")
input("  [Enter]를 눌러 모험을 시작하세요...")

Trun(0)