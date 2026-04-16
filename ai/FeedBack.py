"""
FeedBack.py
─────────────────────────────────────────────
전투 복기 및 피드백 생성 모듈.

구조:
  FeedbackEngine          ← 외부에서 쓰는 진입점
    ├── RuleBasedAnalyzer ← 현재 동작 (규칙 기반)
    └── LLMAnalyzer       ← API 키 생기면 이것만 교체

LLM 교체 방법:
  1. LLMAnalyzer.__init__ 안에 API 키 입력
  2. engine = FeedbackEngine(use_llm=True, api_key="sk-...")
  → 나머지 코드 변경 없음
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List

from ai.Battle_Engine import BattleResult, TurnLog


# ────────────────────────────────────────────
# 피드백 결과 데이터
# ────────────────────────────────────────────

@dataclass
class FeedbackReport:
    headline:    str
    good_plays:  List[str]
    bad_plays:   List[str]
    suggestions: List[str]
    score:       int

    def print(self):
        print("\n" + "=" * 50)
        print("  ◆ 전투 복기 리포트")
        print("=" * 50)
        print("\n  총평: " + self.headline)
        print("  전투 점수: " + str(self.score) + " / 100\n")

        if self.good_plays:
            print("  [잘한 점]")
            for g in self.good_plays:
                print("    · " + g)

        if self.bad_plays:
            print("\n  [아쉬운 점]")
            for b in self.bad_plays:
                print("    · " + b)

        if self.suggestions:
            print("\n  [다음 전투 제안]")
            for s in self.suggestions:
                print("    · " + s)

        print("\n" + "=" * 50 + "\n")


# ────────────────────────────────────────────
# 로그 분석 공통 유틸
# ────────────────────────────────────────────

class _LogStats:
    def __init__(self, result: BattleResult):
        self.result = result
        self.p_logs = [l for l in result.logs if l.actor == "player"]
        self.e_logs = [l for l in result.logs if l.actor == "enemy"]

    @property
    def attack_count(self)  -> int: return sum(1 for l in self.p_logs if l.action == "attack")
    @property
    def skill_count(self)   -> int: return sum(1 for l in self.p_logs if l.action == "skill")
    @property
    def item_count(self)    -> int: return sum(1 for l in self.p_logs if l.action == "item")
    @property
    def total_actions(self) -> int: return len(self.p_logs)
    @property
    def total_dmg(self)     -> int: return sum(l.damage_dealt for l in self.p_logs)
    @property
    def total_taken(self)   -> int: return sum(l.damage_dealt for l in self.e_logs)
    @property
    def crit_count(self)    -> int: return sum(1 for l in self.p_logs if l.is_crit)
    @property
    def skill_rate(self)    -> float:
        return self.skill_count / self.total_actions if self.total_actions else 0.0

    def to_summary_text(self) -> str:
        """LLM 프롬프트용 전투 요약 텍스트"""
        lines = [
            "승패: " + ("승리" if self.result.winner == "player" else "패배"),
            "총 턴: " + str(self.result.total_turns),
            "잔여 HP: " + str(int(self.result.final_player_hp)),
            "일반 공격: " + str(self.attack_count) + "회",
            "스킬 사용: " + str(self.skill_count) + "회",
            "아이템 사용: " + str(self.item_count) + "회",
            "크리티컬: " + str(self.crit_count) + "회",
            "총 가한 데미지: " + str(self.total_dmg),
            "총 받은 데미지: " + str(self.total_taken),
        ]
        # 턴별 행동 요약 (최대 10턴)
        lines.append("--- 턴별 행동 ---")
        for log in self.p_logs[:10]:
            action = log.action_detail if log.action_detail else log.action
            lines.append(
                "턴" + str(log.turn) + " " + action +
                (" +" + str(log.damage_dealt) + "dmg" if log.damage_dealt > 0 else "")
            )
        return "\n".join(lines)


# ────────────────────────────────────────────
# 규칙 기반 분석기 (현재 사용)
# ────────────────────────────────────────────

class RuleBasedAnalyzer:
    def analyze(
        self,
        player_result: BattleResult,
        sim_result:    Optional[BattleResult] = None,
    ) -> FeedbackReport:
        st   = _LogStats(player_result)
        won  = (player_result.winner == "player")
        good = []
        bad  = []
        sugg = []
        score = 50

        # 잘한 점
        if st.skill_rate >= 0.4:
            good.append("스킬을 적극적으로 활용했습니다 (" + str(int(st.skill_rate*100)) + "%)")
            score += 10
        if st.crit_count >= 2:
            good.append("크리티컬이 " + str(st.crit_count) + "회 발생했습니다")
            score += 5
        if won and player_result.final_player_hp > 100:
            good.append("여유 있는 승리였습니다 (잔여 HP: " + str(int(player_result.final_player_hp)) + ")")
            score += 7
        if player_result.total_turns <= 5:
            good.append(str(player_result.total_turns) + "턴 만에 빠르게 처치했습니다")
            score += 5

        # 아쉬운 점
        if not won:
            bad.append("이번 전투에서 패배했습니다")
            score -= 20
        if st.skill_count == 0 and st.total_actions >= 3:
            bad.append("스킬을 한 번도 사용하지 않았습니다")
            score -= 12
        elif st.skill_rate < 0.2 and st.skill_count > 0:
            bad.append("스킬 사용이 적었습니다 (" + str(st.skill_count) + "회)")
            score -= 8

        # AI 비교
        if sim_result:
            sim_st = _LogStats(sim_result)
            if sim_st.skill_count > st.skill_count + 1:
                bad.append(
                    "AI는 스킬을 " + str(sim_st.skill_count - st.skill_count) +
                    "회 더 사용했습니다 (AI: " + str(sim_st.skill_count) +
                    "회 / 플레이어: " + str(st.skill_count) + "회)"
                )
                score -= 5
            if sim_result.total_turns < player_result.total_turns - 2:
                bad.append(
                    "AI는 " + str(sim_result.total_turns) + "턴에 종료했지만 " +
                    "플레이어는 " + str(player_result.total_turns) + "턴이 걸렸습니다"
                )
                score -= 5

        # 제안
        if st.skill_count == 0:
            sugg.append("MP가 30% 이상일 때 스킬을 먼저 사용해보세요")
        if not won:
            sugg.append("HP가 30% 이하로 떨어지면 즉시 포션을 사용하세요")
        if st.skill_rate > 0.5 and not won:
            sugg.append("스킬 활용은 좋았습니다 — 레벨업 후 재도전해보세요")

        good  = list(dict.fromkeys(good))[:3]
        bad   = list(dict.fromkeys(bad))[:3]
        sugg  = list(dict.fromkeys(sugg))[:3]
        score = max(0, min(100, score))

        if won and score >= 80:
            headline = "완벽한 전투였습니다! 스킬과 아이템을 효율적으로 활용했습니다."
        elif won and score >= 60:
            headline = "승리했지만 개선할 부분이 있습니다. 스킬 활용도를 높여보세요."
        elif won:
            headline = "아슬아슬한 승리였습니다. 더 효율적인 전략을 시도해보세요."
        elif score >= 40:
            headline = "아쉬운 패배입니다. 포션과 스킬 타이밍을 개선하면 이길 수 있습니다."
        else:
            headline = "전략적 개선이 필요합니다. 스킬과 아이템을 적극적으로 활용하세요."

        return FeedbackReport(headline=headline, good_plays=good,
                              bad_plays=bad, suggestions=sugg, score=score)


# ────────────────────────────────────────────
# LLM 분석기 — API 키 생기면 여기만 채우면 됨
# ────────────────────────────────────────────

class LLMAnalyzer:
    """
    ┌─────────────────────────────────────────┐
    │  TODO: API 키 생기면 아래 3단계만 작업   │
    │                                         │
    │  1. api_key 파라미터 확인               │
    │  2. self.client 주석 해제               │
    │  3. analyze() 본문 구현                 │
    └─────────────────────────────────────────┘
    """

    def __init__(self, api_key: str):
        self.api_key = api_key

        # ── STEP 1: 클라이언트 초기화 (주석 해제) ──────────────
        # import anthropic
        # self.client = anthropic.Anthropic(api_key=api_key)
        # ───────────────────────────────────────────────────────

    def analyze(
        self,
        player_result: BattleResult,
        sim_result:    Optional[BattleResult] = None,
    ) -> FeedbackReport:

        # ── STEP 2: 프롬프트 구성 ──────────────────────────────
        # p_summary = _LogStats(player_result).to_summary_text()
        # s_summary = _LogStats(sim_result).to_summary_text() if sim_result else "없음"
        #
        # prompt = f"""
        # 아래는 RPG 게임 전투 로그입니다. 간결하게 한국어로 피드백을 JSON으로만 반환하세요.
        #
        # [플레이어 전투]
        # {p_summary}
        #
        # [AI 최적 전투]
        # {s_summary}
        #
        # 반환 형식 (JSON만, 설명 없이):
        # {{
        #   "headline": "한 줄 총평",
        #   "good_plays": ["잘한 점1", "잘한 점2"],
        #   "bad_plays": ["아쉬운 점1", "아쉬운 점2"],
        #   "suggestions": ["제안1", "제안2"],
        #   "score": 75
        # }}
        # """
        # ───────────────────────────────────────────────────────

        # ── STEP 3: API 호출 + 파싱 ────────────────────────────
        # response = self.client.messages.create(
        #     model="claude-opus-4-5",
        #     max_tokens=500,
        #     messages=[{"role": "user", "content": prompt}]
        # )
        # import json
        # data = json.loads(response.content[0].text)
        # return FeedbackReport(
        #     headline    = data["headline"],
        #     good_plays  = data.get("good_plays", []),
        #     bad_plays   = data.get("bad_plays", []),
        #     suggestions = data.get("suggestions", []),
        #     score       = int(data.get("score", 50)),
        # )
        # ───────────────────────────────────────────────────────

        raise NotImplementedError(
            "LLM 피드백은 API 키 연동 후 사용 가능합니다.\n"
            "FeedBack.py 의 LLMAnalyzer.analyze() 주석을 해제하세요."
        )


# ────────────────────────────────────────────
# 진입점 — 외부에서 이것만 쓰면 됨
# ────────────────────────────────────────────

class FeedbackEngine:
    """
    use_llm=False  → RuleBasedAnalyzer (현재 기본)
    use_llm=True   → LLMAnalyzer      (API 키 준비 후)
    """

    def __init__(self, use_llm: bool = False, api_key: str = None):
        if use_llm and api_key:
            self.analyzer = LLMAnalyzer(api_key)
            self._mode    = "LLM"
        else:
            self.analyzer = RuleBasedAnalyzer()
            self._mode    = "규칙 기반"

    def run(
        self,
        player_result: BattleResult,
        sim_result:    Optional[BattleResult] = None,
        print_report:  bool = True,
    ) -> FeedbackReport:
        report = self.analyzer.analyze(player_result, sim_result)
        if print_report:
            report.print()
        return report