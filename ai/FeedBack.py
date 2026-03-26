from __future__ import annotations
from typing import Optional, List
"""
feedback.py
─────────────────────────────────────────────
전투 복기 및 피드백 생성 모듈.

구조:
  FeedbackEngine          ← 외부에서 쓰는 진입점
    ├── RuleBasedAnalyzer ← 현재 구현 (규칙 기반)
    └── LLMAnalyzer       ← 추후 API 키 생기면 이것만 교체

LLM 교체 방법:
  engine = FeedbackEngine(use_llm=True, api_key="sk-...")
  → 내부적으로 LLMAnalyzer 사용, 나머지 코드 변경 없음
"""

from dataclasses import dataclass
from ai.Battle_Engine import BattleResult, TurnLog


# ────────────────────────────────────────────
# 피드백 결과 데이터
# ────────────────────────────────────────────

@dataclass
class FeedbackReport:
    """복기 결과 패키지"""
    headline:    str          # 한 줄 총평
    good_plays:  List[str]    # 잘한 점 (최대 3개)
    bad_plays:   List[str]    # 아쉬운 점 (최대 3개)
    suggestions: List[str]    # 개선 제안 (최대 3개)
    score:       int          # 전투 점수 0~100

    def print(self):
        print("\n" + "=" * 50)
        print("  ◆ 전투 복기 리포트")
        print("=" * 50)
        print(f"\n  총평: {self.headline}")
        print(f"  전투 점수: {self.score} / 100\n")

        if self.good_plays:
            print("  ✅ 잘한 점")
            for g in self.good_plays:
                print(f"    · {g}")

        if self.bad_plays:
            print("\n  ❌ 아쉬운 점")
            for b in self.bad_plays:
                print(f"    · {b}")

        if self.suggestions:
            print("\n  💡 다음 전투 제안")
            for s in self.suggestions:
                print(f"    · {s}")

        print("\n" + "=" * 50)


# ────────────────────────────────────────────
# 로그 분석 공통 유틸
# ────────────────────────────────────────────

class _LogStats:
    """BattleResult에서 통계 지표 추출 — 분석기 공용"""

    def __init__(self, result: BattleResult):
        self.result = result
        self.p_logs = [l for l in result.logs if l.actor == "player"]
        self.e_logs = [l for l in result.logs if l.actor == "enemy"]

    # 플레이어 행동 카운트
    @property
    def attack_count(self)  -> int: return sum(1 for l in self.p_logs if l.action == "attack")
    @property
    def skill_count(self)   -> int: return sum(1 for l in self.p_logs if l.action == "skill")
    @property
    def item_count(self)    -> int: return sum(1 for l in self.p_logs if l.action == "item")
    @property
    def total_actions(self) -> int: return len(self.p_logs)

    # 데미지 통계
    @property
    def total_dmg(self)  -> int:   return sum(l.damage_dealt for l in self.p_logs)
    @property
    def total_taken(self)-> int:   return sum(l.damage_dealt for l in self.e_logs)
    @property
    def crit_count(self) -> int:   return sum(1 for l in self.p_logs if l.is_crit)
    @property
    def dodge_count(self)-> int:   return sum(1 for l in self.p_logs if l.is_dodge)

    # 아이템 관련
    @property
    def hp_potion_used(self) -> int:
        return sum(1 for l in self.p_logs
                   if l.action == "item" and "HP" in l.action_detail)
    @property
    def mp_potion_used(self) -> int:
        return sum(1 for l in self.p_logs
                   if l.action == "item" and "MP" in l.action_detail)

    # HP 위기 때 포션 안 쓴 횟수 추정
    def low_hp_no_potion(self, threshold: float = 0.3) -> int:
        """
        적 공격으로 HP가 임계값 이하로 떨어진 직후
        플레이어가 포션을 사용하지 않은 횟수
        """
        count = 0
        for i, log in enumerate(self.e_logs):
            if log.hp_after <= 0:
                continue
            # 다음 플레이어 행동 찾기
            next_p = next(
                (l for l in self.p_logs if l.turn > log.turn),
                None
            )
            if next_p and next_p.action != "item":
                # hp_after가 플레이어 HP인지 확인 (낮으면 위기)
                if log.hp_after < 60:   # 절대값 임계 (간이 판단)
                    count += 1
        return count

    # MP 낭비 판단: MP 포션 썼는데 스킬 없는 경우
    def mp_wasted(self) -> bool:
        for i, log in enumerate(self.p_logs):
            if log.action == "item" and "MP" in log.action_detail:
                # 이후 스킬 사용했는지 확인
                used_skill_after = any(
                    l.action == "skill" for l in self.p_logs[i+1:]
                )
                if not used_skill_after:
                    return True
        return False

    # 스킬 사용률
    @property
    def skill_rate(self) -> float:
        if self.total_actions == 0:
            return 0.0
        return self.skill_count / self.total_actions


# ────────────────────────────────────────────
# 규칙 기반 분석기
# ────────────────────────────────────────────

class RuleBasedAnalyzer:
    """
    전투 로그를 규칙으로 분석해 피드백 생성.
    LLMAnalyzer와 동일한 인터페이스(analyze 메서드)를 제공.
    """

    def analyze(
        self,
        player_result: BattleResult,
        sim_result:    Optional[BattleResult] = None,
    ) -> FeedbackReport:
        st = _LogStats(player_result)
        won = (player_result.winner == "player")

        good_plays  = []
        bad_plays   = []
        suggestions = []
        score       = 50  # 기본 점수

        # ── 잘한 점 판단 ──────────────────────

        if st.skill_rate >= 0.4:
            good_plays.append(
                f"스킬을 적극적으로 활용했습니다 (전체 행동의 {st.skill_rate*100:.0f}%)"
            )
            score += 10

        if st.crit_count >= 2:
            good_plays.append(f"크리티컬이 {st.crit_count}회 발생했습니다")
            score += 5

        if st.hp_potion_used > 0 and won:
            good_plays.append(
                f"HP 포션을 {st.hp_potion_used}회 적절히 사용해 생존했습니다"
            )
            score += 8

        if won and player_result.final_player_hp > 100:
            good_plays.append(
                f"여유 있는 승리였습니다 (잔여 HP: {int(player_result.final_player_hp)})"
            )
            score += 7

        if player_result.total_turns <= 5:
            good_plays.append(f"{player_result.total_turns}턴 만에 빠르게 처치했습니다")
            score += 5

        # ── 아쉬운 점 판단 ────────────────────

        if not won:
            bad_plays.append("이번 전투에서 패배했습니다")
            score -= 20

        if st.skill_count == 0 and st.total_actions >= 3:
            bad_plays.append(
                "스킬을 한 번도 사용하지 않았습니다 — 스킬이 일반 공격보다 효율적입니다"
            )
            score -= 12

        if st.skill_rate < 0.2 and st.skill_count > 0:
            bad_plays.append(
                f"스킬 사용이 적었습니다 ({st.skill_count}회) — "
                f"MP가 남아있을 때 스킬을 우선 사용하세요"
            )
            score -= 8

        lhnp = st.low_hp_no_potion()
        if lhnp >= 1:
            bad_plays.append(
                f"HP가 위험할 때 포션을 사용하지 않은 순간이 {lhnp}번 있었습니다"
            )
            score -= 10

        if st.mp_wasted():
            bad_plays.append(
                "MP 포션을 사용하고도 이후 스킬을 사용하지 않았습니다 — "
                "MP 포션은 스킬 직전에 사용하는 것이 효율적입니다"
            )
            score -= 7

        # ── AI 시뮬 비교 (있을 때) ────────────

        if sim_result:
            sim_st = _LogStats(sim_result)

            if sim_st.skill_count > st.skill_count + 1:
                diff = sim_st.skill_count - st.skill_count
                bad_plays.append(
                    f"AI는 스킬을 {diff}회 더 사용했습니다 "
                    f"(AI: {sim_st.skill_count}회 / 플레이어: {st.skill_count}회)"
                )
                score -= 5

            if sim_result.total_turns < player_result.total_turns - 2:
                bad_plays.append(
                    f"AI는 {sim_result.total_turns}턴에 종료했지만 "
                    f"플레이어는 {player_result.total_turns}턴이 걸렸습니다"
                )
                score -= 5

            if sim_st.total_dmg > st.total_dmg * 1.2:
                bad_plays.append(
                    f"AI의 총 피해량({sim_st.total_dmg})이 "
                    f"플레이어({st.total_dmg})보다 높았습니다 — "
                    f"공격 효율을 높이세요"
                )
                score -= 5

        # ── 개선 제안 ─────────────────────────

        if st.skill_count == 0:
            suggestions.append(
                "다음 전투에서는 MP가 30% 이상일 때 스킬을 우선 사용해보세요"
            )

        if not won:
            suggestions.append(
                "HP가 최대 HP의 30% 이하로 떨어지면 즉시 HP 포션을 사용하세요"
            )

        if st.skill_rate > 0.5 and not won:
            suggestions.append(
                "스킬 사용은 좋았습니다 — "
                "몬스터 난이도를 낮추거나 레벨업 후 재도전하세요"
            )

        if st.mp_potion_used == 0 and st.skill_count < 2:
            suggestions.append(
                "MP 포션을 사용해 스킬을 더 많이 활용하는 전략을 시도해보세요"
            )

        # 중복 제거 및 최대 3개 제한
        good_plays  = list(dict.fromkeys(good_plays))[:3]
        bad_plays   = list(dict.fromkeys(bad_plays))[:3]
        suggestions = list(dict.fromkeys(suggestions))[:3]

        # 점수 클램프
        score = max(0, min(100, score))

        # 총평 생성
        headline = self._headline(score, won, st)

        return FeedbackReport(
            headline    = headline,
            good_plays  = good_plays,
            bad_plays   = bad_plays,
            suggestions = suggestions,
            score       = score,
        )

    def _headline(self, score: int, won: bool, st: _LogStats) -> str:
        if won and score >= 80:
            return f"완벽한 전투였습니다! 스킬과 아이템을 효율적으로 활용했습니다."
        elif won and score >= 60:
            return f"승리했지만 개선할 부분이 있습니다. 스킬 활용도를 높여보세요."
        elif won:
            return f"아슬아슬한 승리였습니다. 다음에는 더 효율적인 전략을 시도해보세요."
        elif score >= 40:
            return f"아쉬운 패배입니다. 포션과 스킬 타이밍을 개선하면 이길 수 있습니다."
        else:
            return f"전략적 개선이 필요합니다. 스킬과 아이템을 적극적으로 활용하세요."


# ────────────────────────────────────────────
# LLM 분석기 — 추후 교체용 슬롯
# ────────────────────────────────────────────

class LLMAnalyzer:
    """
    API 키 생기면 이 클래스만 구현하면 된다.
    RuleBasedAnalyzer와 동일한 인터페이스.

    TODO: api_key 받아서 Anthropic 클라이언트 초기화
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        # self.client = anthropic.Anthropic(api_key=api_key)

    def analyze(
        self,
        player_result: BattleResult,
        sim_result:    Optional[BattleResult] = None,
    ) -> FeedbackReport:
        """
        TODO: 프롬프트 구성 → API 호출 → FeedbackReport 파싱
        
        프롬프트 구조 (토큰 최소화):
          - 플레이어 로그 요약 (턴별 행동 텍스트)
          - AI 시뮬 로그 요약 (있을 때)
          - "잘한 점 1~3개, 아쉬운 점 1~3개, 제안 1~3개, 점수(0~100)를
             JSON으로만 반환해라"
        """
        raise NotImplementedError("API 키 연동 후 구현 예정")


# ────────────────────────────────────────────
# 진입점 — 외부에서 이것만 쓰면 됨
# ────────────────────────────────────────────

class FeedbackEngine:
    """
    use_llm=False → RuleBasedAnalyzer (현재)
    use_llm=True  → LLMAnalyzer      (API 키 준비 후)
    """

    def __init__(self, use_llm: bool = False, api_key: str = None):
        if use_llm and api_key:
            self.analyzer = LLMAnalyzer(api_key)
        else:
            self.analyzer = RuleBasedAnalyzer()

    def run(
        self,
        player_result: BattleResult,
        sim_result:    Optional[BattleResult] = None,
        print_report:  bool = True,
    ) -> FeedbackReport:
        """
        player_result : 플레이어 실전 전투 결과
        sim_result    : AI 시뮬레이션 최적 전투 결과 (없으면 None)
        """
        report = self.analyzer.analyze(player_result, sim_result)
        if print_report:
            report.print()
        return report


# ────────────────────────────────────────────
# 테스트
# ────────────────────────────────────────────

if __name__ == "__main__":
    from ai.Battle_Engine import BattleEngine, EntitySnapshot
    from Auto_AI import PlayerAI, EnemyAI
    from Simulator import BASE_ENEMIES

    player = EntitySnapshot(
        name="홍길동", hp=200, maxhp=200, mp=25, maxmp=25,
        stg=7, arm=5, sparm=5, sp=5, luc=15, lv=3,
        learned_skills=["셰이드 1", "파이어볼 1"],
        items=["HP_S_potion", "HP_M_potion"],
    )
    enemy = BASE_ENEMIES["고블린"]

    print("=== 케이스 1: 플레이어 전투 (스킬 사용) ===")
    engine = BattleEngine(player, enemy)
    p_result = engine.run(PlayerAI("balanced"), EnemyAI())

    print("=== AI 시뮬레이션 ===")
    sim_engine = BattleEngine(player, enemy)
    s_result = sim_engine.run(PlayerAI("aggressive"), EnemyAI())

    print("\n=== 피드백 리포트 ===")
    fb = FeedbackEngine(use_llm=False)
    fb.run(p_result, sim_result=s_result)

    print("\n\n=== 케이스 2: 스킬 없는 플레이어 (패배 시뮬) ===")
    weak_player = EntitySnapshot(
        name="초보용사", hp=80, maxhp=80, mp=0, maxmp=0,
        stg=3, arm=3, sparm=3, sp=0, luc=5, lv=1,
        learned_skills=[], items=[],
    )
    strong_enemy = EntitySnapshot(
        name="강화고블린", hp=300, maxhp=300, mp=0, maxmp=0,
        stg=15, arm=20, sparm=0, sp=0, luc=10, lv=5,
    )
    engine2 = BattleEngine(weak_player, strong_enemy)
    p_result2 = engine2.run(PlayerAI("balanced"), EnemyAI())

    fb.run(p_result2, sim_result=None)