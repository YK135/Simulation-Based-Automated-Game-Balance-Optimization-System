"""Battle/ATB.py — ATBSystem"""
from __future__ import annotations



class ATBSystem:
    THRESHOLD = 100

    def __init__(self, spd_multiplier: float = 1.0, player_start: float = 0.0):
        # player_start: cross-battle ATB 이월(EntitySnapshot.atb_remainder) 시작값.
        # 적(enemy_pt)은 항상 0에서 시작 — 실전 규칙과 동일.
        self.player_pt: float = self._sanitize_start(player_start)
        self.enemy_pt: float = 0.0
        self.x = spd_multiplier

    # 정상 시나리오에서 이월값이 이 이상으로 커질 이유가 없다(매 tick 증가폭은
    # SPD 수준의 한 자릿수~두 자릿수, 초과분 이월도 THRESHOLD 단위) — 넉넉히
    # 10배로 잡아 상한을 둔다. 이 이상은 손상된 값으로 간주해 0으로 되돌린다.
    MAX_SANE_START = 1000.0

    @staticmethod
    def _sanitize_start(value) -> float:
        """player_start 방어적 정제 (BALANCE_PATCH_3 3~4차 검증 지적).

        atb_remainder는 Player.to_dict()/from_dict()를 거쳐 Redis/DB에
        저장·복원되므로(app/Shared.py의 세션 스냅샷 경유) 이론상 손상된
        세션 데이터가 여기까지 흘러들 수 있다 — None, 숫자로 변환할 수
        없는 값(예: "abc" — "37.5"처럼 숫자 형태 문자열은 float()가 정상
        변환하므로 그대로 허용됨), NaN, 무한대, 음수를 0.0으로 되돌린다.
        ★ 4차 검증 지적: 매우 큰 유한값(예: 1e308)은 애초 구현이 안 막고
        있었다 — float64 정밀도 한계상 `1e308 - THRESHOLD(100)`은 반올림
        오차로 그대로 1e308이 돼(관측 확인), tick()의 "초과분만 이월"
        로직이 사실상 무력화되고 매 tick 플레이어가 계속 행동 가능한
        상태가 된다. MAX_SANE_START로 상한도 함께 막는다."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if v != v or v in (float("inf"), float("-inf")):  # v != v → NaN
            return 0.0
        if v < 0.0 or v > ATBSystem.MAX_SANE_START:
            return 0.0
        return v

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