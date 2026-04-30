"""
Main.py - ver0.3
AI 밸런싱 메시지만 1.5초 자동 → 나머지는 엔터
초기 포션 S/M/L 각 1개씩
"""
from __future__ import annotations
from random import randint, random
import sys, os, time

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _sub in ["game", "ai", "core", "interface"]:
    _p = os.path.join(_ROOT, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.path.insert(0, _ROOT)

from game.Player_Class        import Player
from game.Enemy_Class         import Make_Random_Monster, Make_MidBoss, Make_FinalBoss
from game.Item                import Item_
from game.Lv                  import LV_
from game.Skill               import Ply_Skill
from interface.Game_Interface import (
    clear, GameEmdKey, Trun_interface, Rest_Area,
    Battle_interface, Player_Deth, show_enemy_status
)
from core.Action_Class  import Act
from core.Balance_Hook  import BalanceHook


# ── 딜레이 헬퍼 ─────────────────────────────
def _ai_msg(msg: str):
    """AI 밸런싱 메시지 전용: 출력 후 1.5초 자동 넘김"""
    print(msg)
    time.sleep(1.5)
    clear()

def _enter(msg: str):
    """이벤트 내 메시지: 그냥 출력만 (엔터는 턴 표시 후 한 번만)"""
    print(msg)


# ── 직업 선택 ──────────────────────────
def _select_job() -> str:
    """직업 선택 UI"""
    clear()
    print("=" * 60)
    print("  직업을 선택하세요")
    print("=" * 60)
    print()
    print("  1. 전사   — 균형잡힌 물리 공격수 (HP 높음, 물리 데미지 특화)")
    print("  2. 마법사 — 강력한 마법과 회복 (마력 특화, MP 회복 패시브)")
    print("  3. 탱커   — 높은 생존력과 반격 (HP/방어 특화, 피해 감소 패시브)")
    print("  4. 도적   — 빠른 연타와 크리티컬 (스피드/행운 특화, 크리티컬 관통)")
    print()
    
    jobs = {
        "1": "전사",
        "2": "마법사",
        "3": "탱커",
        "4": "도적",
    }
    
    while True:
        choice = input("  선택 (1~4): ").strip()
        if choice in jobs:
            clear()
            return jobs[choice]
        print("  1~4 중 하나를 선택하세요.\n")


# ── 플레이어 초기화 ──────────────────────────
def _init_player(name: str, job: str) -> Player:
    """직업별 초기 스탯으로 플레이어 생성"""
    from game.Player_Class import create_player_by_job
    p = create_player_by_job(name, job)
    p.skill = Ply_Skill(job=job)
    p.skill.update_skills(1)  # Lv1 스킬 해금
    return p


plname = input("이름을 입력하세요. ------> ").strip() or "용사"
pljob  = _select_job()
ply    = _init_player(plname, pljob)

# 초기 아이템: HP_S×2, HP_M×1, MP_S×2 (총 5개)
pl_item = [
    "HP_S_potion", "HP_S_potion",
    "HP_M_potion",
    "MP_S_potion", "MP_S_potion",
]
item_list = list(pl_item)

hook = BalanceHook(ply, pl_item, show_graph=True, verbose=True)   # graphs/ 폴더에 자동 저장
mid_boss_cleared = False

# 피드백 엔진 (API 키 생기면 use_llm=True, api_key="sk-..." 로 변경)
from ai.FeedBack import FeedbackEngine
_fb = FeedbackEngine(use_llm=False)


# ── 공통 유틸 ────────────────────────────────
def _give_exp(monster):
    lv_obj = LV_(ply)
    exp = (monster.exp_reward(ply.maxexp)
           if hasattr(monster, 'exp_reward') else randint(45, 60))
    lv_obj.Get_exp(ply, reward_exp=exp)
    hook.check_level_up()


def _run_battle(enemy, is_boss: bool = False) -> str:
    return Act(ply, enemy, pl_item, is_boss=is_boss).action()


# ── 이벤트 ──────────────────────────────────
def _event_battle():
    # 콘솔/Flask 동일 풀 사용 — Balance_Hook의 _ENEMY_POOL 기준.
    # Lv1: 고블린/박쥐, Lv3+: 슬라임, Lv6+: 골렘, Lv7+: 유령, Lv10+: 암살자.
    enemy_type = hook.pick_random_enemy_type()

    # AI 밸런싱 — 이 메시지만 1.5초 자동
    print()
    enemy_snap = hook.get_enemy(enemy_type)   # 내부에서 [밸런싱] 메시지 출력
    enemy      = hook.make_battle_unit(enemy_snap)
    time.sleep(1.5)
    clear()

    print("  " + enemy.name + "이(가) 나타났다!\n")
    time.sleep(1.0)

    result = _run_battle(enemy)

    if result == "win":
        print("\n  " + enemy.name + "을(를) 처치했다!\n")
        time.sleep(1.0)
        _give_exp(enemy)
    elif result == "escaped":
        print("\n  도망쳤다!\n")
        time.sleep(0.8)
    else:
        Game_over()


def _event_item():
    item = item_list[randint(0, len(item_list) - 1)]
    pl_item.append(item)
    print("\n  [아이템 획득] " + item + " 을(를) 발견했다!")


def _event_rest():
    Rest_Area()
    key = input("입력: ").strip()
    if key == '1':
        if ply.hp >= ply.maxhp:
            _enter("  이미 체력이 가득 찼습니다.")
        else:
            heal   = min(int(ply.maxhp / 3), ply.maxhp - ply.hp)
            ply.hp += heal
            _enter("  체력 " + str(heal) + " 회복! (" +
                   str(int(ply.hp)) + "/" + str(int(ply.maxhp)) + ")")
    elif key == '2':
        ratio    = 0.60 + random() * 0.20
        exp_gain = int(ply.maxexp * ratio)
        lv_obj   = LV_(ply)
        lv_obj.Get_exp(ply, reward_exp=exp_gain)
        hook.check_level_up()
        _enter("  수련으로 " + str(exp_gain) + " 경험치 획득!")
    else:
        print("  잘못된 선택입니다.\n")


def _event_midboss():
    global mid_boss_cleared
    clear()
    print("=" * 45)
    print("  !! 중간 보스 등장 !!")
    print("=" * 45)
    print("\n  현재 Lv." + str(ply.lv) +
          "  HP:" + str(int(ply.hp)) + "/" + str(int(ply.maxhp)) + "\n")
    input("  [Enter]를 눌러 전투 시작...")

    cached = hook._get_cached_monsters("고블린")
    base   = cached.get("normal", (None, None))[0] if cached else None
    boss   = Make_MidBoss(ply.lv, base)
    print("\n  " + boss.name + " 등장! (HP: " + str(boss.hp) + ")\n")
    time.sleep(1.0)

    result = _run_battle(boss)
    if result == "win":
        _enter("\n  중간 보스를 처치했다!\n  보상: HP_L_potion 획득!")
        mid_boss_cleared = True
        _give_exp(boss)
        pl_item.append("HP_L_potion")
        # ── 전투 복기 피드백 ──
        _show_feedback(boss.name)
    elif result == "escaped":
        _enter("\n  도망쳤다! 보스는 아직 남아있다...")
    else:
        Game_over()


def _event_finalboss():
    clear()
    print("=" * 45)
    print("  !! 최종 보스 등장 !!")
    print("=" * 45)

    if ply.lv < 25:
        print("\n  현재 레벨 " + str(ply.lv) + " — 레벨 25 이상을 권장합니다.")
        print("  그래도 도전하시겠습니까? (Y/N)")
        while True:
            k = input("입력: ").strip().lower()
            if k == 'y':   break
            elif k == 'n':
                print("  더 강해져서 돌아오세요!\n")
                return
            else:
                print("  Y 또는 N을 입력하세요.")

    print("\n  현재 Lv." + str(ply.lv) +
          "  HP:" + str(int(ply.hp)) + "/" + str(int(ply.maxhp)) + "\n")
    input("  [Enter]를 눌러 최종 전투 시작...")

    cached = hook._get_cached_monsters("고블린")
    base   = cached.get("hard", (None, None))[0] if cached else None
    boss   = Make_FinalBoss(ply.lv, base)
    print("\n  " + boss.name + " 등장! (HP: " + str(boss.hp) + ")\n")
    time.sleep(1.0)

    result = _run_battle(boss, is_boss=True)
    if result == "win":
        clear()
        _show_feedback(boss.name)
        print("\n" + "=" * 45)
        print("  최종 보스 처치!")
        print("  당신은 세계를 구했습니다!")
        print("=" * 45)
        print("\n  " + ply.name + "  /  최종 Lv." + str(ply.lv))
        print("  잔여 HP: " + str(int(ply.hp)) + "/" + str(int(ply.maxhp)) + "\n")
        sys.exit()
    else:
        print("\n  패배했습니다...\n")
        Game_over()


# ── 전투 복기 피드백 ────────────────────────
def _show_feedback(enemy_name: str):
    """
    보스전 후 규칙 기반 피드백 출력.
    API 키 생기면 _fb = FeedbackEngine(use_llm=True, api_key="sk-...") 로 변경.
    """
    try:
        from ai.Battle_Engine import BattleEngine, EntitySnapshot
        from ai.Auto_AI import PlayerAI, EnemyAI
        import copy
        print("\n  [AI 전투 분석 중...]")
        time.sleep(1.0)
        # 피드백용 간이 스냅샷 생성
        p_snap = EntitySnapshot.from_player(ply)
        p_snap.learned_skills = list(ply.skill.learned_skills) if ply.skill else []
        _fb.run(
            player_result=type("R", (), {
                "logs": [],
                "winner": "player" if ply.hp > 0 else "enemy",
                "total_turns": 0,
                "final_player_hp": ply.hp,
                "player_name": ply.name,
                "enemy_name": enemy_name,
            })(),
            print_report=True
        )
    except Exception:
        pass  # 피드백 오류가 게임 흐름을 막지 않음
    input("  [Enter] 계속...")


# ── 게임 오버 / 재시작 ──────────────────────
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
    name = input("\n[재시작] 이름을 다시 입력하세요 ------> ").strip() or "용사"
    job  = _select_job()
    ply  = _init_player(name, job)
    pl_item = [
        "HP_S_potion", "HP_S_potion",
        "HP_M_potion",
        "MP_S_potion", "MP_S_potion",
    ]
    hook = BalanceHook(ply, pl_item, show_graph=True, verbose=True)  # graphs/ 폴더에 자동 저장
    mid_boss_cleared = False
    print("\n게임을 다시 시작합니다!\n")
    Trun(0)


# ── 메인 루프 ────────────────────────────────
def Trun(tn: int):
    global mid_boss_cleared

    while True:
        Game_over()

        if tn == 25 and not mid_boss_cleared:
            _event_midboss()
            tn += 1
            input("\n[Enter]를 눌러 계속...")
            continue

        if tn >= 50:
            _event_finalboss()
            break

        Trun_interface(tn, ply)
        key = input("입력: ").strip().lower()

        if key == '4':
            GameEmdKey()

        elif key == '1':
            print("앞으로 나아갑니다.\n")
            rd = randint(1, 20)

            if   1 <= rd <= 12:  _event_battle()
            elif 13 <= rd <= 15: _event_item()
            elif 16 <= rd <= 17: _event_rest()
            else:
                print("  조용하다... 아무 일도 일어나지 않았다.")

            tn += 1
            # 이벤트 결과 아래에 바로 남은 턴 표시 → 엔터 하나
            warn = "  !! 다음 턴 중간 보스 등장 !!" if (tn == 24 and not mid_boss_cleared) else ""
            turn_msg = "\n  진행: " + str(tn) + "/50턴  |  Lv." + str(ply.lv) + \
                       "  HP:" + str(int(ply.hp)) + "/" + str(int(ply.maxhp)) + \
                       "  MP:" + str(int(ply.mp)) + "/" + str(int(ply.maxmp))
            if warn:
                turn_msg += "\n" + warn
            input(turn_msg + "\n\n  [Enter]를 눌러 계속...")

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
            print("\n사용할 아이템 번호 선택 (취소: q)")
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


        elif key == 'g':
            print("  그래프 저장 중...\n")
            try:
                import os
                from ai.Visualizer import Visualizer
                _graph_dir = os.path.join(_ROOT, "graphs")
                viz = Visualizer(save_dir=_graph_dir)

                saved = False
                for _etype in ["고블린", "박쥐"]:
                    _monsters = hook._get_cached_monsters(_etype)
                    if _monsters:
                        viz.win_rate_bar(_monsters, ply.name + f" ({_etype})")
                        saved = True

                if not saved:
                    print("  시뮬레이션 완료 후 다시 시도하세요.\n")
                else:
                    print(f"  graphs/ 폴더에 저장 완료\n")
            except Exception as e:
                print("  그래프 오류: " + str(e) + "\n")
            input("[Enter] 계속...")

        else:
            print("  1~4, a(자동전투), g(그래프) 중 입력하세요.\n")


# ── 게임 시작 ────────────────────────────────
clear()
print("\n  환영합니다, " + ply.name + "님! (" + ply.job + ")")
print("  AI가 실력에 맞춰 몬스터를 자동 조정합니다.")
print("\n  [초기 아이템] HP_S×2, HP_M×1, MP_S×2 지급 완료")
print("  백그라운드에서 밸런스 분석 중...\n")
input("  [Enter]를 눌러 모험을 시작하세요...")

Trun(0)