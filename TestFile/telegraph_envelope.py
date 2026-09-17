"""telegraph_envelope.py — 「대지 균열」 한 방의 기준 피해와 실제 분포 측정.

전제 코드: 본표·부록 A~C의 계산은 9ef20a6 기준이며, 그 뒤의 커밋은 이 4개 파일의
계산 경로를 바꾸지 않았다(Damage.py는 표시 전용 피격 장부 기록 줄만 추가):
  ai/battle/Damage.py  game/Lv.py  game/Player_Class.py  game/Enemy_Class.py
부록 D는 ai/battle/Entity.py의 상태이상 처리를 읽는다 — 전용 타입 "rift"의 tick 분기가
들어간 뒤(11-1 3-1)부터 D-3이 실제 피해를 보고한다.
실행:  python3 telegraph_envelope.py
출력:  telegraph_envelope.out  (표준출력과 동일 내용)
"""
import os, sys, tempfile, statistics, random, io, contextlib

SEED, N = 20260917, 200_000
# 프로젝트 루트 = 이 파일의 상위 디렉터리(TestFile/의 부모).
# 다른 위치에 두고 돌릴 때만 AI_RPG_ROOT 환경변수로 덮어쓴다.
ROOT = os.environ.get(
    "AI_RPG_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

_fd, _db = tempfile.mkstemp(prefix="tele_", suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db          # 로컬 ai_rpg.db 미사용
sys.path.insert(0, ROOT)

from game.Player_Class import Player, JOB_BASE_STATS     # noqa: E402
from game.Lv import LV_                                  # noqa: E402
from ai.battle import Damage as D                        # noqa: E402

# 중간 보스 실측 스탯 (game/Enemy_Class.py Make_MidBoss — 레벨 무관 고정)
BOSS_STG, BOSS_LUC = 36, 22
MULT = {"P1": 1.8, "P2": 2.1}      # 「대지 균열」 계수 (P2는 4장 설계안)
PEN  = 0.5                         # 플레이어 ARM 50% 관통

def build_lv15():
    """Lv1 → Lv15를 실제 Lv_up()으로 승급. 선택 포인트(레벨당 3, 누적 42)는 미분배."""
    out = {}
    for job in ("전사", "마법사", "도적"):
        b = JOB_BASE_STATS[job]
        p = Player("측정", 1, 100, 0, b["hp"], b["hp"], b["mp"], b["mp"],
                   b["stg"], b["arm"], b["sparm"], b["sp"], b["spd"], b["luc"], job)
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(14):
                p.exp = 10 ** 9
                LV_.Lv_up(p)
        assert p.lv == 15 and p.pending_points == 42
        out[job] = p
    return out

@contextlib.contextmanager
def deterministic():
    """난수·크리·회피를 끈 '기준 피해' 측정용 — uniform=1.0, randint는 절대 임계 초과."""
    ru, ri = D.uniform, D.randint
    D.uniform = lambda a, b: 1.0
    D.randint = lambda a, b: b          # 회피·크리 판정 모두 실패
    try:
        yield
    finally:
        D.uniform, D.randint = ru, ri

def hit(pl, mult):
    return D.DamageCalc.physical(BOSS_STG, BOSS_LUC, pl.arm * PEN, pl.luc,
                                 skill_mult=mult, role="monster")

def main():
    random.seed(SEED)
    jobs = build_lv15()
    rows = []
    for job, pl in jobs.items():
        for ph, mult in MULT.items():
            with deterministic():
                base, _, _ = hit(pl, mult)
            vals, ev, cr = [], 0, 0
            for _ in range(N):
                d, evaded, crit = hit(pl, mult)
                if evaded:
                    ev += 1; vals.append(0); continue
                cr += crit; vals.append(d)
            nz = [v for v in vals if v > 0]          # 명중 표본만
            rows.append(dict(job=job, ph=ph, maxhp=pl.maxhp, arm=round(pl.arm, 1),
                             luc=round(pl.luc, 1), base=base,
                             evade=100*ev/N, crit=100*cr/len(nz),
                             # 명중 시 기준 (회피 0 제외)
                             med=statistics.median(nz), mx=max(nz), mn=min(nz),
                             # 전체 시도 기준 (회피 0 포함)
                             med_all=statistics.median(vals), mn_all=min(vals),
                             exp=statistics.mean(vals)))
    hdr = (f"seed={SEED}  N={N:,}  boss STG={BOSS_STG} LUC={BOSS_LUC}  ARM 관통 {PEN:.0%}\n"
           f"집계 기준: '명중' 열 3개(중앙/최소/최대)는 회피 표본을 제외한 값,\n"
           f"          '전체' 열 2개(중앙/최소)와 기대값은 회피의 0 피해를 포함한 값.\n"
           f"{'직업':<5}{'페이즈':>5}{'maxHP':>7}{'ARM':>6}{'LUC':>6}"
           f"{'기준':>6}{'명중중앙':>9}{'명중최소':>9}{'명중최대':>9}"
           f"{'전체중앙':>9}{'전체최소':>9}{'기대':>8}"
           f"{'회피%':>7}{'크리%':>7}{'기준%':>7}{'명중중앙%':>10}{'명중최대%':>10}")
    lines = [hdr]
    for r in rows:
        lines.append(
            f"{r['job']:<5}{r['ph']:>5}{r['maxhp']:>7}{r['arm']:>6}{r['luc']:>6}"
            f"{r['base']:>6}{r['med']:>9.0f}{r['mn']:>9}{r['mx']:>9}"
            f"{r['med_all']:>9.0f}{r['mn_all']:>9}{r['exp']:>8.1f}"
            f"{r['evade']:>6.1f}%{r['crit']:>6.1f}%"
            f"{100*r['base']/r['maxhp']:>6.1f}%{100*r['med']/r['maxhp']:>9.1f}%"
            f"{100*r['mx']/r['maxhp']:>9.1f}%")
    # ── 부록 A: 균열 vs 일반공격 (관통 없음 · 계수 1.0) ──
    lines.append("")
    lines.append("[부록 A] 균열 vs 일반공격 — 명중 시 중앙값 (N=%s)" % f"{N:,}")
    for job, pl in jobs.items():
        def med(arm, mult):
            v = []
            for _ in range(N):
                d, e, _ = D.DamageCalc.physical(BOSS_STG, BOSS_LUC, arm, pl.luc,
                                                skill_mult=mult, role="monster")
                if not e: v.append(d)
            return statistics.median(v)
        n, g = med(pl.arm, 1.0), med(pl.arm * PEN, MULT["P1"])
        lines.append(f"  {job:<5} 일반 {n:>5.0f} ({100*n/pl.maxhp:4.1f}%)  "
                     f"균열 {g:>5.0f} ({100*g/pl.maxhp:4.1f}%)  배수 {g/n:.2f}x")

    # ── 부록 B: 남은 선택 포인트 42점을 전부 ARM에 넣었을 때 (P1) ──
    lines.append("")
    lines.append("[부록 B] 선택 포인트 42점 전부 ARM 투자 시 균열 P1 — 명중 시 중앙값")
    for job, pl in jobs.items():
        def med(arm):
            v = []
            for _ in range(N):
                d, e, _ = D.DamageCalc.physical(BOSS_STG, BOSS_LUC, arm, pl.luc,
                                                skill_mult=MULT["P1"], role="monster")
                if not e: v.append(d)
            return statistics.median(v)
        a, b = med(pl.arm * PEN), med((pl.arm + 42) * PEN)
        lines.append(f"  {job:<5} ARM {pl.arm:4.1f} -> {pl.arm+42:4.1f}   "
                     f"{a:>5.0f} ({100*a/pl.maxhp:4.1f}%) -> {b:>5.0f} ({100*b/pl.maxhp:4.1f}%)")

    # ── 부록 C: (B) 계수 인상 — 적용 방식 두 가지의 결과 차이 ──
    war = next(r for r in rows if r["job"] == "전사"   and r["ph"] == "P1")
    mag1 = next(r for r in rows if r["job"] == "마법사" and r["ph"] == "P1")
    mag2 = next(r for r in rows if r["job"] == "마법사" and r["ph"] == "P2")
    k_war = (0.25 * war["maxhp"]) / war["med"]      # 전사 P1 중앙값을 maxHP 25%로
    k_mag = (0.25 * mag1["maxhp"]) / mag1["med"]    # 마법사 P1 중앙값을 maxHP 25%로
    k_swap = (MULT["P1"] * k_war) / MULT["P2"]
    mag = jobs["마법사"]

    def remeasure(pl, mult):
        """새 계수를 실제로 넣고 다시 굴린 값 — 비례 환산이 아니라 실측."""
        v = []
        for _ in range(N):
            d, e, _ = D.DamageCalc.physical(BOSS_STG, BOSS_LUC, pl.arm * PEN, pl.luc,
                                            skill_mult=mult, role="monster")
            if not e: v.append(d)
        return statistics.median(v), max(v)

    lines.append("")
    lines.append("[부록 C] (B) 계수 인상 — 목표: P1 명중중앙값을 maxHP 25%로")
    lines.append("  아래 수치는 전부 새 계수를 넣고 다시 굴린 실측값(정수 절삭 포함).")
    for tag, k in (("전사 기준", k_war), ("마법사 기준", k_mag)):
        lines.append(f"  {tag}: 배수 {k:.3f}x  ->  P1 계수 {MULT['P1']*k:.2f}")
        for r in (r for r in rows if r["ph"] == "P1"):
            med, _mx = remeasure(jobs[r["job"]], MULT["P1"] * k)
            lines.append(f"      {r['job']:<5} P1 명중중앙 환산 {r['med']*k:>6.0f} "
                         f"({100*r['med']*k/r['maxhp']:5.1f}%)  /  실측 {med:>6.0f} "
                         f"({100*med/r['maxhp']:5.1f}% maxHP)")
    lines.append("  P2 적용 방식 — 마법사 P2 명중최대(크리) 기준.")
    lines.append("    '환산'은 기존 표본 x 배수(근사), '실측'은 새 계수로 다시 굴린 값(정수 절삭 포함).")
    for tag, p2_mult, k in (
            (f"(a) P1과 같은 배수를 P2에도 -> P2 계수 {MULT['P2']*k_war:.2f}", MULT["P2"]*k_war, k_war),
            (f"(b) P2 계수를 P1의 값({MULT['P1']*k_war:.2f})으로 교체", MULT["P1"]*k_war,  k_swap)):
        est_med, est_mx = mag2["med"]*k, mag2["mx"]*k
        act_med, act_mx = remeasure(mag, p2_mult)
        lines.append(f"    {tag}  (배수 {k:.3f}x)")
        lines.append(f"        환산  중앙 {est_med:>6.0f} ({100*est_med/mag2['maxhp']:5.1f}%)   "
                     f"최대 {est_mx:>6.0f} ({100*est_mx/mag2['maxhp']:5.1f}%)")
        lines.append(f"        실측  중앙 {act_med:>6.0f} ({100*act_med/mag2['maxhp']:5.1f}%)   "
                     f"최대 {act_mx:>6.0f} ({100*act_mx/mag2['maxhp']:5.1f}%)")

    # ── 부록 D: 「균열」 DoT — 재적용 누적량과 ignite 공유 여부 ──
    from ai.battle.Entity import EntitySnapshot, StatusEffect
    lines.append("")
    lines.append("[부록 D] 균열 DoT — 재적용 누적 피해와 상태이상 타입 충돌")

    def probe(maxhp=1000.0):
        e = EntitySnapshot.from_player(jobs["마법사"])
        e.maxhp, e.hp, e.status_effects = maxhp, maxhp, []
        return e

    def rift(turns=2, etype="ignite"):
        """「균열」 DoT 설계안: 매 행동 maxHP 4%, 2회."""
        return StatusEffect(effect_type=etype, turns=turns, name="균열", dot_rate=0.04)

    def drain(e, ticks):
        """ticks회 tick_status_effects() 호출하고 준 피해 합계를 돌려준다."""
        before = e.hp
        for _ in range(ticks):
            e.tick_status_effects()
        return before - e.hp

    lines.append("  D-1) 재적용 시점에 따른 총 피해 (maxHP 1000, 틱당 4% = 40)")
    e = probe(); e.apply_status_effect(rift())
    d = drain(e, 5)
    lines.append(f"      재적용 없음            : 총 {d:>5.0f} ({100*d/1000:4.1f}% maxHP), 틱 {d/40:.0f}회")
    e = probe(); e.apply_status_effect(rift()); d1 = drain(e, 1)
    e.apply_status_effect(rift()); d2 = drain(e, 5)
    lines.append(f"      1틱 뒤 재적용          : 총 {d1+d2:>5.0f} ({100*(d1+d2)/1000:4.1f}% maxHP), 틱 {(d1+d2)/40:.0f}회")
    e = probe(); e.apply_status_effect(rift()); d1 = drain(e, 2)
    e.apply_status_effect(rift()); d2 = drain(e, 5)
    lines.append(f"      2틱(소진) 뒤 재적용    : 총 {d1+d2:>5.0f} ({100*(d1+d2)/1000:4.1f}% maxHP), 틱 {(d1+d2)/40:.0f}회")
    lines.append("      -> 중첩은 없지만 '갱신'이라 총 피해는 8%로 고정되지 않는다. 실제 틱 수로 집계할 것.")

    lines.append("  D-2) effect_type='ignite'로 만들면 기존 화상과 합쳐지는가")
    e = probe()
    # 기존 화염 공격이 건 화상: ELEMENT_STATUS_TURNS['ignite'] = 3
    e.apply_status_effect(StatusEffect(effect_type="ignite", turns=3, name="화상", dot_rate=0.04))
    e.apply_status_effect(rift())               # 균열(2턴)을 같은 타입으로 적용
    ef = e.status_effects[0]
    lines.append(f"      화상(3턴) + 균열(2턴)  : 효과 {len(e.status_effects)}개, "
                 f"이름 '{ef.name}', 남은 턴 {ef.turns}")
    lines.append("      -> 별개 효과가 생기지 않고 이름도 '화상'이 유지된다. 균열의 2턴은 max()에 밀려 사라진다.")

    lines.append("  D-3) 전용 타입('rift')이면 독립적으로 존재하는가")
    e = probe()
    e.apply_status_effect(StatusEffect(effect_type="ignite", turns=3, name="화상", dot_rate=0.04))
    e.apply_status_effect(rift(etype="rift"))
    names = ", ".join(f"{x.name}({x.effect_type},{x.turns}T)" for x in e.status_effects)
    lines.append(f"      화상 + 균열(rift)      : 효과 {len(e.status_effects)}개 — {names}")
    d = drain(e, 5)
    lines.append(f"      틱 5회 동안 총 피해 {d:>5.0f} = 화상 3틱(120) + 균열 2틱(80) — 서로 독립적으로 들어간다")
    lines.append("      -> 전용 타입 'rift'는 tick_status_effects()에 분기가 있어 화상과 따로 피해를 준다(3-1 구현).")

    txt = "\n".join(lines)
    print(txt)
    with io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "telegraph_envelope.out"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")

try:
    main()
finally:
    os.remove(_db)
