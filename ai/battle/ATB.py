"""Battle/ATB.py — ATBSystem"""
from __future__ import annotations



class ATBSystem:
    THRESHOLD = 100

    def __init__(self, spd_multiplier: float = 1.0):
        self.player_pt: float = 0.0
        self.enemy_pt: float = 0.0
        self.x = spd_multiplier

    def tick(self, player_spd: float, enemy_spd: float) -> list[str]:
        self.player_pt += max(1.0, player_spd * self.x)
        self.enemy_pt += max(1.0, enemy_spd * self.x)

        candidates = []
        if self.player_pt >= self.THRESHOLD:
            candidates.append(("player", self.player_pt))
        if self.enemy_pt >= self.THRESHOLD:
            candidates.append(("enemy", self.enemy_pt))

        candidates.sort(key=lambda x: (x[1], 1 if x[0] == "player" else 0), reverse=True)
        actors = [c[0] for c in candidates]

        # ★ 100을 "전부 0으로 초기화"하지 않고 초과분을 이월한다 — 실전
        #   (ai/Battlesession.py의 `self.player_atb -= 100.0` 등)은 SPD가 높아
        #   한 번에 100을 크게 넘긴 잔여분을 다음 행동에 그대로 반영하는데,
        #   여기서 매번 완전히 0으로 리셋하면 그 초과분이 사라져 고SPD 빌드의
        #   추가 행동 빈도를 실전보다 낮게 측정하게 된다.
        if "player" in actors:
            self.player_pt -= self.THRESHOLD
        if "enemy" in actors:
            self.enemy_pt -= self.THRESHOLD

        return actors


# ────────────────────────────────────────────
# 데미지 계산
# ────────────────────────────────────────────