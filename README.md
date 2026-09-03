# 시뮬레이션 기반 자동 밸런스 최적화 및 사용자 행동 분석 시스템

한국어 텍스트 RPG(Flask 백엔드 + 순수 JS 프론트엔드)를 실험 환경으로 삼아,
Binary Search 기반 자동 밸런싱과 사용자 행동 로그 분석을 실제 플레이 흐름에
연결한 시스템입니다. 게임 자체가 목적이 아니라, 실제 플레이 데이터를 쌓아
이후 모방학습/RL 연구에 쓰는 것이 최종 목표입니다 — 자세한 배경은
[PROJECT_GOAL.md](PROJECT_GOAL.md) 참고.

## 핵심 개념

전부 실제 라이브 서비스에 연결되어 있는 구성요소입니다 (문서와 실제 코드
사이의 괴리가 있었던 이력은 `PROJECT_GOAL.md`에 정직하게 기록해뒀습니다):

- **`BattleEngine`** (`ai/battle/Engine.py`) — 실전 전투와 시뮬레이션이 공유하는
  단일 전투 엔진. 밸런스 결론이 시뮬레이션에서 실제 플레이로 그대로 전이되도록,
  이 엔진 하나만 쓴다.
- **`BattleSimulator`** (`ai/Simulator.py`) — 같은 조건의 전투를 반복 실행해
  승률을 계산하는 Monte Carlo 시뮬레이터.
- **`StatTuner`** (`ai/Simulator.py`) — 목표 승률에 맞도록 몬스터 스탯을 Binary
  Search로 역산하는 튜너. `core/Balance_Hook.py`의 `get_enemy()`가 몬스터를 처음
  마주칠 때(또는 레벨업 시) 백그라운드 스레드에서 실제로 실행한다 — 반복마다
  `BattleSimulator`로 300~500회 시뮬레이션.
- **`PlayerPowerIndex`** (`ai/Simulator.py`) — HP/MP 비율, 스킬 기대 데미지,
  포션 보유량, 스탯, SPD를 반영한 동적 난이도 지표(0.4~2.0). `StatTuner`의
  목표 승률을 이 지수로 보정한다.
- **`BehaviorAnalyzer`** (`ai/BehaviorAnalyzer.py`) — 전투 로그를 집계해 플레이
  패턴(공격/스킬/아이템/도망 비율 → 플레이 스타일 분류)을 정량 분석하는 모듈.
- **`FeedbackEngine`** (`ai/FeedBack.py`) — 분석 결과를 바탕으로 규칙 기반 복기
  리포트(총평/잘한 점/아쉬운 점/제안/점수)를 생성하는 모듈. 실제 패배 시
  `app/Battle.py` → `core/Balance_Hook.py`의 `after_battle()`을 거쳐 게임오버
  화면에 표시된다.

밸런스는 이 자동 역산 층 위에, `game/Enemy_Class.py`/`app/Map.py`의 손으로 정한
배율(등급/레벨/다인원 보정)이 한 층 더 곱해지는 구조입니다 — 후자는 자동이
아니라 전수 시뮬레이션 스윕으로 검증하며 사람이 반복 조정한 값입니다. 자세한
구조는 [CLAUDE.md](CLAUDE.md)의 "Balance-curve stacking" 섹션 참고.

## 실행

```bash
python3 App.py     # http://localhost:5000
```

프로덕션 실행 방식, 환경변수, DB 초기화 등은 [CLAUDE.md](CLAUDE.md)의
Commands 섹션 참고.

## 검증

pytest가 아니라 `TestFile/*.py`의 독립 실행 스크립트로 회귀를 검증합니다:

```bash
python3 TestFile/test_element_fix.py          # 파일 하나만
for f in TestFile/test_*.py; do python3 "$f"; done   # 전체 스위트
```

`TestFile/montecarlo.py`는 전체 밸런스 검증용 장시간 시뮬레이션 스크립트라
(수천 회 전투) 위 회귀 스위트에 포함하지 않습니다. 세부 규칙은
[CLAUDE.md](CLAUDE.md) 참고.

## 프로젝트 정체성

자세한 목표와 본질 정의는 [PROJECT_GOAL.md](PROJECT_GOAL.md)를 참고하세요.

## LLM 사용 범위

**런타임에는 LLM 호출이 없습니다.** 게임이 실제로 플레이되는 동안 돌아가는
밸런스 역산(`StatTuner`)과 행동 분석/피드백(`BehaviorAnalyzer`,
`FeedbackEngine`의 `RuleBasedAnalyzer`)은 전부 직접 구현한 통계/규칙 기반
로직이며, 서버가 API 요청을 처리하는 도중 외부 LLM API를 부르는 코드 경로는
없습니다 (`ai/FeedBack.py`에 `LLMAnalyzer`가 대안 구현으로 준비돼 있지만
`use_llm=False`가 기본값이라 비활성 상태입니다).

다만 **개발 과정에서는 LLM(Claude Code)이 핵심적인 역할을 했습니다** — 이
프로젝트의 코드 대부분은 Claude Code로 작성/수정됐고, 몬스터 밸런스 배율
(`GRADE_MULT`/`_level_curve_mult`/`STAT_SCALE` 등)처럼 승률 목표에 맞춰 구체적인
수치를 정하고 시뮬레이션 결과를 보며 반복 조정하는 판단도 LLM이 수행했습니다.
"런타임에 LLM을 안 쓴다"와 "개발 과정에 LLM을 안 썼다"는 서로 다른 주장이며,
이 프로젝트는 전자만 사실입니다.
