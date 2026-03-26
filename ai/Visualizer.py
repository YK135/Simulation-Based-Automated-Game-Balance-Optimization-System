"""
visualizer.py
─────────────────────────────────────────────
시뮬레이션 결과 시각화 모듈.

출력 그래프 3종:
  1. win_rate_bar     : 난이도별 승률 막대 그래프
  2. hp_timeline      : 턴별 HP 변화 (플레이어 vs 적)
  3. stat_radar       : 플레이어 vs 몬스터 스탯 방사형 비교

사용 예시:
  viz = Visualizer()
  viz.win_rate_bar(monsters)        # MonsterFactory 결과
  viz.hp_timeline(battle_result)    # BattleResult
  viz.stat_radar(player, enemy)     # EntitySnapshot 둘
  viz.show()                        # 전부 출력
"""

import os
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

import platform
def _set_korean_font():
    s = platform.system()
    if s == 'Windows': matplotlib.rcParams['font.family'] = 'Malgun Gothic'
    elif s == 'Darwin': matplotlib.rcParams['font.family'] = 'AppleGothic'
    else:
        try:
            from matplotlib import font_manager
            fl = [f.name for f in font_manager.fontManager.ttflist]
            for c in ['NanumGothic','NanumBarunGothic','Noto Sans KR']:
                if c in fl: matplotlib.rcParams['font.family'] = c; break
        except Exception: pass
_set_korean_font()
matplotlib.rcParams['axes.unicode_minus'] = False

from ai.Battle_Engine import BattleResult, EntitySnapshot
# SimulationResult는 사용 시점에 import (순환 import 방지)


# ────────────────────────────────────────────
# 색상 팔레트
# ────────────────────────────────────────────

COLORS = {
    "hard":   "#E24B4A",   # 강함 — 레드
    "normal": "#EF9F27",   # 중간 — 앰버
    "easy":   "#1D9E75",   # 약함 — 틸
    "player": "#378ADD",   # 플레이어 — 블루
    "enemy":  "#D85A30",   # 적 — 코랄
    "bg":     "#F8F8F6",
    "grid":   "#E0DED6",
    "text":   "#2C2C2A",
    "sub":    "#888780",
}

DIFF_LABELS = {
    "hard":   "강함 (목표 45%)",
    "normal": "중간 (목표 55%)",
    "easy":   "약함 (목표 65%)",
}


# ────────────────────────────────────────────
# Visualizer
# ────────────────────────────────────────────

class Visualizer:

    def __init__(self, save_dir: str = None):
        """
        save_dir 지정 시 show() 대신 PNG 파일로 저장.
        None 이면 plt.show() 로 화면 출력.
        """
        self.save_dir = save_dir
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
        self._fig_count = 0

    # ── 1. 난이도별 승률 막대 그래프 ────────

    def win_rate_bar(
        self,
        monsters: dict,       # {"hard": (snap, SimResult), ...}
        player_name: str = "플레이어",
    ):
        """
        난이도 3종의 실제 승률을 목표값과 함께 표시.
        monsters: MonsterFactory.generate_all() 반환값
        """
        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor(COLORS["bg"])
        ax.set_facecolor(COLORS["bg"])

        diffs      = ["hard", "normal", "easy"]
        targets    = [0.45, 0.55, 0.65]
        actuals    = [monsters[d][1].win_rate for d in diffs]
        labels     = [DIFF_LABELS[d] for d in diffs]
        bar_colors = [COLORS[d] for d in diffs]

        x     = np.arange(len(diffs))
        width = 0.35

        # 실제 승률 막대
        bars = ax.bar(x, actuals, width, color=bar_colors,
                      alpha=0.85, label="실제 승률", zorder=3)

        # 목표 승률 점선
        for i, (xi, tgt) in enumerate(zip(x, targets)):
            ax.plot(
                [xi - width/2 - 0.05, xi + width/2 + 0.05],
                [tgt, tgt],
                color=COLORS["text"], linewidth=1.5,
                linestyle="--", zorder=4
            )
            ax.text(xi + width/2 + 0.08, tgt,
                    f"목표 {tgt*100:.0f}%",
                    va="center", fontsize=9, color=COLORS["sub"])

        # 막대 위 수치 표시
        for bar, val in zip(bars, actuals):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.01,
                f"{val*100:.1f}%",
                ha="center", va="bottom",
                fontsize=11, fontweight="bold",
                color=COLORS["text"]
            )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10)
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("플레이어 승률", fontsize=10, color=COLORS["sub"])
        ax.set_title(
            f"{player_name} — 난이도별 몬스터 승률",
            fontsize=13, fontweight="bold",
            color=COLORS["text"], pad=14
        )
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda y, _: f"{y*100:.0f}%")
        )
        ax.grid(axis="y", color=COLORS["grid"], linewidth=0.8, zorder=0)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(colors=COLORS["sub"])

        # 시뮬 횟수 표기
        n = monsters["hard"][1].total_runs
        fig.text(0.99, 0.01, f"시뮬레이션 {n}회 기준",
                 ha="right", fontsize=8, color=COLORS["sub"])

        plt.tight_layout()
        self._output(fig, "win_rate_bar")

    # ── 2. 턴별 HP 변화 ─────────────────────

    def hp_timeline(
        self,
        result: BattleResult,
        title:  str = None,
    ):
        """
        전투 로그에서 턴별 HP 변화를 꺾은선 그래프로 표시.
        플레이어 HP(파랑) / 적 HP(레드) 두 선.
        """
        # 로그에서 HP 시계열 추출
        player_hp = [result.final_player_hp]  # 역순으로 쌓고 뒤집기
        enemy_hp  = [result.final_enemy_hp]
        turns     = [result.total_turns]

        # 턴 역순 재구성: 로그를 거슬러 올라가며 hp_after 복원
        # 플레이어 행동 → 적 HP 변화 / 적 행동 → 플레이어 HP 변화
        p_hp_seq = []
        e_hp_seq = []

        # 초기값 추정 (로그 첫 턴 이전 HP 역산)
        p_hp = result.final_player_hp
        e_hp = result.final_enemy_hp

        turn_data = {}
        for log in result.logs:
            turn_data.setdefault(log.turn, []).append(log)

        # 턴 순서대로 HP 재구성
        p_hp_points = []
        e_hp_points = []
        turn_points = []

        # 시작 HP 추정 (첫 공격 전 역산)
        first_logs = turn_data.get(1, [])
        start_p = result.final_player_hp
        start_e = result.final_enemy_hp
        for log in result.logs:
            if log.actor == "player":
                start_e += log.damage_dealt
            elif log.actor == "enemy":
                start_p += log.damage_dealt
        p_hp_points.append(round(start_p))
        e_hp_points.append(round(start_e))
        turn_points.append(0)

        # 턴별 누적 HP
        cur_p = start_p
        cur_e = start_e
        for t in sorted(turn_data.keys()):
            for log in turn_data[t]:
                if log.actor == "player":
                    cur_e -= log.damage_dealt
                elif log.actor == "enemy":
                    cur_p -= log.damage_dealt
            p_hp_points.append(round(cur_p))
            e_hp_points.append(round(cur_e))
            turn_points.append(t)

        fig, ax = plt.subplots(figsize=(9, 5))
        fig.patch.set_facecolor(COLORS["bg"])
        ax.set_facecolor(COLORS["bg"])

        ax.plot(turn_points, p_hp_points,
                color=COLORS["player"], linewidth=2.2,
                marker="o", markersize=5, label=result.player_name, zorder=3)
        ax.plot(turn_points, e_hp_points,
                color=COLORS["enemy"], linewidth=2.2,
                marker="s", markersize=5, label=result.enemy_name, zorder=3)

        # HP=0 기준선
        ax.axhline(0, color=COLORS["grid"], linewidth=1, linestyle="--", zorder=1)

        # 승패 결과 표기
        winner_txt = (
            f"{result.player_name} 승리 🏆"
            if result.winner == "player"
            else f"{result.enemy_name} 승리"
        )
        ax.text(
            0.99, 0.97, winner_txt,
            transform=ax.transAxes,
            ha="right", va="top",
            fontsize=10, color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.3",
                      facecolor="white", alpha=0.7, edgecolor="none")
        )

        ax.set_xlabel("턴", fontsize=10, color=COLORS["sub"])
        ax.set_ylabel("HP", fontsize=10, color=COLORS["sub"])
        ax.set_title(
            title or f"{result.player_name} vs {result.enemy_name} — 전투 HP 변화",
            fontsize=13, fontweight="bold",
            color=COLORS["text"], pad=14
        )
        ax.legend(fontsize=10)
        ax.grid(color=COLORS["grid"], linewidth=0.8, zorder=0)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(colors=COLORS["sub"])

        plt.tight_layout()
        self._output(fig, "hp_timeline")

    # ── 3. 스탯 방사형 비교 ──────────────────

    def stat_radar(
        self,
        player: EntitySnapshot,
        enemy:  EntitySnapshot,
        title:  str = None,
    ):
        """
        플레이어와 몬스터의 주요 스탯을 방사형 차트로 비교.
        """
        categories = ["HP", "STG", "ARM", "SP", "SPARM", "LUC"]
        p_vals_raw = [player.maxhp, player.stg, player.arm,
                      player.sp,    player.sparm, player.luc]
        e_vals_raw = [enemy.maxhp,  enemy.stg,   enemy.arm,
                      enemy.sp,     enemy.sparm,  enemy.luc]

        # 0~1 정규화 (두 값 중 큰 값 기준)
        def normalize(p, e):
            m = max(p, e, 1)
            return p / m, e / m

        p_norm, e_norm = zip(*[normalize(p, e)
                                for p, e in zip(p_vals_raw, e_vals_raw)])

        N     = len(categories)
        angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
        angles += angles[:1]

        p_vals = list(p_norm) + [p_norm[0]]
        e_vals = list(e_norm) + [e_norm[0]]

        fig, ax = plt.subplots(figsize=(6, 6),
                               subplot_kw=dict(polar=True))
        fig.patch.set_facecolor(COLORS["bg"])
        ax.set_facecolor(COLORS["bg"])

        ax.plot(angles, p_vals,
                color=COLORS["player"], linewidth=2, label=player.name)
        ax.fill(angles, p_vals,
                color=COLORS["player"], alpha=0.20)

        ax.plot(angles, e_vals,
                color=COLORS["enemy"], linewidth=2, label=enemy.name)
        ax.fill(angles, e_vals,
                color=COLORS["enemy"], alpha=0.20)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, fontsize=10, color=COLORS["text"])
        ax.set_yticklabels([])
        ax.grid(color=COLORS["grid"], linewidth=0.8)

        # 실제 수치를 꼭짓점 근처에 표시
        for i, (angle, pv, ev, pr, er) in enumerate(
            zip(angles[:-1], p_norm, e_norm, p_vals_raw, e_vals_raw)
        ):
            offset = 0.15
            ax.text(angle, max(pv, ev) + offset,
                    f"P:{int(pr)} / E:{int(er)}",
                    ha="center", va="center",
                    fontsize=7.5, color=COLORS["sub"])

        ax.set_title(
            title or f"스탯 비교 — {player.name} vs {enemy.name}",
            fontsize=12, fontweight="bold",
            color=COLORS["text"], pad=20
        )
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=9)

        plt.tight_layout()
        self._output(fig, "stat_radar")

    # ── 4. 시뮬레이션 전체 요약 ─────────────

    def sim_summary(
        self,
        monsters:    dict,
        player:      EntitySnapshot,
        sample_result: BattleResult = None,
    ):
        """
        win_rate_bar + stat_radar 를 한 번에.
        sample_result 있으면 hp_timeline 도 추가.
        """
        self.win_rate_bar(monsters, player.name)
        hard_snap = monsters["hard"][0]
        self.stat_radar(player, hard_snap,
                        title=f"스탯 비교 — {player.name} vs 강한 {hard_snap.name}")
        if sample_result:
            self.hp_timeline(sample_result)

    # ── 내부 유틸 ────────────────────────────

    def _output(self, fig, name: str):
        if self.save_dir:
            path = os.path.join(self.save_dir, f"{name}.png")
            fig.savefig(path, dpi=150, bbox_inches="tight",
                        facecolor=fig.get_facecolor())
            print(f"  그래프 저장: {path}")
            plt.close(fig)
        else:
            plt.show()
        self._fig_count += 1

    def show(self):
        """save_dir 없을 때 남은 figure 전부 출력"""
        plt.show()