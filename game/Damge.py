from random import randint

# 일반 공격 함수
def stg_Attack(a_stg, a_luc, b_arm, b_luc):
    rd_1 = randint(1, 10)
    rd = randint(1, rd_1)

    dodge_roll = randint(1, 100)
    if dodge_roll <= b_luc:
        return 0

    base_dmg = (a_stg * 100 / (100 + b_arm) * 10) + rd

    crit_roll = randint(1, 100)
    if crit_roll <= a_luc:
        base_dmg *= 1.5

    return int(base_dmg)

def magic_Attack(a_sp, a_luc, b_sparm, b_luc):
    rd_1 = randint(1, 10)
    rd = randint(1, rd_1)

    dodge_roll = randint(1, 100)
    if dodge_roll <= b_luc:
        return 0

    base_dmg = (a_sp * 100 / (100 + b_sparm) * 10) + rd

    crit_roll = randint(1, 100)
    if crit_roll <= a_luc:
        base_dmg *= 1.5

    return int(base_dmg)

def Magic_mp(p_mp, e_n, e_hp, x, m_mp):
    if p_mp < m_mp:
        return e_hp, p_mp
    else:
        print(f"{e_n}에게 {x}의 데미지!\n")
        e_hp -= x
        p_mp -= m_mp
        return e_hp, p_mp

def Stg_massege_e(e_n, e_h, e_d):
    print(f"{e_n}에게 물리공격!")
    if e_d == 0:
        print(f"{e_n}은 공격을 회피했다!\n")
    else:
        e_h -= e_d
        print(f"{e_n}에게 {e_d}의 데미지!\n")
    return e_h

def Stg_massege_p(e_n, p_n, p_h, p_d):
    if p_d == 0:
        print(f"{p_n}은 공격을 회피했다!\n")
    else:
        p_h -= p_d
        print(f"{e_n}은 {p_n}에게 {p_d}의 데미지!\n")
    return p_h

# 스킬 데미지 함수
def Shade(p_stg, p_luc, e_arm, e_luc):
    d1 = int(stg_Attack(p_stg, p_luc, e_arm, e_luc) * 0.7)
    d2 = int(stg_Attack(p_stg, p_luc, e_arm, e_luc) * 0.7)
    print("\n셰이드 1 을(를) 사용하였다!")
    print(f"{d1}\n{d2}")
    return d1 + d2

def Shade_2(p_stg, p_luc, e_arm, e_luc):
    d1 = int(stg_Attack(p_stg, p_luc, e_arm, e_luc) * 0.7)
    d2 = int(stg_Attack(p_stg, p_luc, e_arm, e_luc) * 0.7)
    d3 = int(stg_Attack(p_stg, p_luc, e_arm, e_luc) * 0.7)
    print("\n셰이드 2 을(를) 사용했다!")
    print(f"{d1}\n{d2}\n{d3}")
    return d1 + d2 + d3

def Fierball1(p_sp, p_luc, e_sparm, e_luc):
    return int(magic_Attack(p_sp, p_luc, e_sparm, e_luc) * 1.4)

def Fierball2(p_sp, p_luc, e_sparm, e_luc):
    return int(magic_Attack(p_sp, p_luc, e_sparm, e_luc) * 1.6)

def Fierball3(p_sp, p_luc, e_sparm, e_luc):
    return int(magic_Attack(p_sp, p_luc, e_sparm, e_luc) * 1.8)

def Frozebolt1(p_sp, p_luc, e_sparm, e_luc):
    return int(magic_Attack(p_sp, p_luc, e_sparm, e_luc) * 1.5)

def Frozebolt2(p_sp, p_luc, e_sparm, e_luc):
    return int(magic_Attack(p_sp, p_luc, e_sparm, e_luc) * 1.7)

def Frozebolt3(p_sp, p_luc, e_sparm, e_luc):
    return int(magic_Attack(p_sp, p_luc, e_sparm, e_luc) * 2.0)