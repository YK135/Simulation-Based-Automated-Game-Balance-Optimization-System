"""
BehaviorAnalyzer.py
─────────────────────────────────────────────
전투 로그 기반 사용자 행동 패턴 분석 모듈.

목표:
  - JSON 로그를 BattleResult로 불러온 뒤 플레이어 행동을 정량화
  - 자동전투/피드백에 사용할 수 있는 플레이 스타일 라벨 생성
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ai.Battle_Engine import BattleResult


@dataclass
class BehaviorSummary:
    battles: int
    wins: int
    win_rate: float
    avg_turns: float
    attack_rate: float
    skill_rate: float
    item_rate: float
    escape_rate: float
    avg_damage_dealt: float
    avg_damage_taken: float
    avg_final_hp: float
    play_style: str

    def to_lines(self) -> list[str]:
        return [
            f"전투 수: {self.battles}",
            f"승률: {self.win_rate * 100:.1f}%",
            f"평균 턴: {self.avg_turns:.1f}",
            f"행동 비율: 공격 {self.attack_rate * 100:.1f}% / 스킬 {self.skill_rate * 100:.1f}% / 아이템 {self.item_rate * 100:.1f}% / 도망 {self.escape_rate * 100:.1f}%",
            f"평균 가한 피해: {self.avg_damage_dealt:.1f}",
            f"평균 받은 피해: {self.avg_damage_taken:.1f}",
            f"평균 잔여 HP: {self.avg_final_hp:.1f}",
            f"플레이 스타일: {self.play_style}",
        ]


class BehaviorAnalyzer:
    """BattleResult 목록을 사용자 행동 지표로 변환한다."""

    def analyze(self, results: Iterable[BattleResult]) -> BehaviorSummary:
        result_list = list(results)
        if not result_list:
            return BehaviorSummary(
                battles=0,
                wins=0,
                win_rate=0.0,
                avg_turns=0.0,
                attack_rate=0.0,
                skill_rate=0.0,
                item_rate=0.0,
                escape_rate=0.0,
                avg_damage_dealt=0.0,
                avg_damage_taken=0.0,
                avg_final_hp=0.0,
                play_style="데이터 부족",
            )

        player_logs = [
            log
            for result in result_list
            for log in result.logs
            if log.actor == "player"
        ]
        enemy_logs = [
            log
            for result in result_list
            for log in result.logs
            if log.actor == "enemy"
        ]

        total_actions = max(1, len(player_logs))
        attack_count = sum(1 for log in player_logs if log.action == "attack")
        skill_count = sum(1 for log in player_logs if log.action == "skill")
        item_count = sum(1 for log in player_logs if log.action == "item")
        escape_count = sum(1 for log in player_logs if log.action == "escape" or log.escaped)

        attack_rate = attack_count / total_actions
        skill_rate = skill_count / total_actions
        item_rate = item_count / total_actions
        escape_rate = escape_count / total_actions

        wins = sum(1 for result in result_list if result.winner == "player")
        avg_turns = sum(result.total_turns for result in result_list) / len(result_list)
        avg_final_hp = sum(max(0, result.final_player_hp) for result in result_list) / len(result_list)
        avg_damage_dealt = sum(log.damage_dealt for log in player_logs) / len(result_list)
        avg_damage_taken = sum(log.damage_dealt for log in enemy_logs) / len(result_list)

        return BehaviorSummary(
            battles=len(result_list),
            wins=wins,
            win_rate=wins / len(result_list),
            avg_turns=avg_turns,
            attack_rate=attack_rate,
            skill_rate=skill_rate,
            item_rate=item_rate,
            escape_rate=escape_rate,
            avg_damage_dealt=avg_damage_dealt,
            avg_damage_taken=avg_damage_taken,
            avg_final_hp=avg_final_hp,
            play_style=self._classify(attack_rate, skill_rate, item_rate, escape_rate),
        )

    def _classify(
        self,
        attack_rate: float,
        skill_rate: float,
        item_rate: float,
        escape_rate: float,
    ) -> str:
        if escape_rate >= 0.15:
            return "위험 회피형"
        if item_rate >= 0.20:
            return "생존 관리형"
        if skill_rate >= 0.45:
            return "스킬 중심형"
        if attack_rate >= 0.70:
            return "기본 공격 중심형"
        return "균형형"


def print_player_summary(player_name: str | None = None, enemy_name: str | None = None):
    from ai.LOG_Manager import LogManager

    logs = LogManager().load_all_player_logs(
        player_name=player_name,
        enemy_name=enemy_name,
    )
    summary = BehaviorAnalyzer().analyze(logs)
    print("\n".join(summary.to_lines()))
    return summary


if __name__ == "__main__":
    print_player_summary()
