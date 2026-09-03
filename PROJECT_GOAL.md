# 프로젝트 본질 정의 (현재 상태 기준 — 2026-09-03 재작성)

> 이 문서는 원래 "시뮬레이션 기반 자동 밸런스 최적화 및 사용자 행동 분석 시스템"이라는
> 이름으로 훨씬 야심찬 시스템을 서술하고 있었다. 실제 코드(`app/`, `ai/`, `core/`)를
> 전수 추적한 결과 그 핵심 구성요소 중 일부가 **정의만 되어 있고 실제 서비스 흐름에
> 연결되어 있지 않다**는 것이 확인되어, 지금 실제로 동작하는 것과 그렇지 않은 것을
> 정직하게 구분해 다시 썼다.
>
> **정정 (같은 날 재작성)**: 처음 이 문서를 쓸 때 `StatTuner`/`PlayerPowerIndex`도
> 미연결이라고 적었는데, 이건 `core/Balance_Hook.py`에서 클래스명을 직접 검색해서
> 놓친 잘못된 판단이었다. 실제로는 `MonsterFactory`(이미 사용 중으로 확인했던 클래스)가
> 내부에서 이 둘을 생성·호출하고 있어서 **이미 매 몬스터 조우마다 실전에서 돌고
> 있었다.** 아래 표는 이 정정을 반영했다. 실제로 미연결이었던 건
> `BehaviorAnalyzer`/`FeedbackEngine` 하나뿐이었고, 이 문서를 쓴 뒤 바로 그 연결
> 작업(after_battle() 배선)까지 완료했다 — 그래서 아래엔 "미연결" 항목이 없다.

## 프로젝트명

시뮬레이션 기반 자동 밸런스 최적화 및 사용자 행동 분석 시스템 — 아래 "지금 실제로
동작하는 것"이 이 이름의 각 구성요소(자동 밸런스 최적화 = `StatTuner`+`PlayerPowerIndex`,
사용자 행동 분석 = `BehaviorAnalyzer`+`FeedbackEngine`)와 실제로 대응한다. 원래
이름을 그대로 되찾은 것 — 아래 "격차가 생긴 이유"에 있던 컴포넌트들을 실제로
연결했다.

## 지금 실제로 동작하는 것

1. **Flask 기반 텍스트 RPG** — 노드맵 탐험(`app/Map.py`, `game/Map.py`) + ATB 기반
   턴제 전투(`ai/battle/`, `ai/Battlesession.py`). 실제 플레이어가 접속해서 처음부터
   끝까지 플레이 가능한 완성된 게임.
2. **자동 밸런스 튜닝 — Binary Search + 플레이어 상태 반영** — 몬스터를 처음 마주치면
   `core/Balance_Hook.py`의 `get_enemy()` → `_start_background_sim()`이 백그라운드
   스레드에서 `ai/Simulator.py`의 `MonsterFactory.generate_all()`을 실행한다. 이
   내부에서 `PlayerPowerIndex.calc()`가 플레이어의 HP/MP/스킬/포션 보유량/스탯을
   0.4~2.0 지수로 환산하고, `StatTuner.tune()`이 그 지수로 보정한 목표 승률에
   수렴할 때까지 **진짜 이진 탐색**(최대 20회 반복, 매 회 `BattleSimulator`로
   300~500회 전투 시뮬레이션)으로 몬스터 스탯을 조정한다 — 몬스터를 만날 때마다,
   레벨업할 때마다 실제로 이 과정이 돈다.
   또한 `game/Enemy_Class.py`의 `GRADE_MULT`/`_level_curve_mult`, `app/Map.py`의
   `STAT_SCALE`/`_early_game_multi_scale`처럼 **사람(혹은 AI 어시스턴트)이 직접
   정한 배율**도 별도 층으로 함께 곱해진다 — 이건 `StatTuner`의 자동 역산과 달리
   `TestFile/montecarlo.py` 스타일 전수 스윕(전 레벨 × 전 몬스터 × 전 직업)을 반복
   돌려가며 사람이 수동으로 맞춘 것 (가장 최근: 2026-09-01, 6회 전체 스윕). 즉 이
   프로젝트의 밸런스는 "자동 역산 층 + 수동 튜닝 층"이 함께 쌓인 구조이며, 후자를
   "AI가 전부 자동으로 한다"고 말하면 과장이다.
3. **전투 후 행동 분석 → 피드백 생성** — 패배 시 `app/Battle.py`의 `_finish_battle()`이
   `BattleSession.to_battle_result()`로 그 전투의 턴별 로그를 `BattleResult`로
   변환하고, `core/Balance_Hook.py`의 `after_battle()`을 호출한다. 이게
   `ai/BehaviorAnalyzer.py`(행동 비율/플레이 스타일 분류)와 `ai/FeedBack.py`의
   `FeedbackEngine`(규칙 기반 복기 리포트: 총평/잘한 점/아쉬운 점/제안/점수)을 실행해
   `/api/battle/action` 응답의 `feedback` 필드에 싣고, 게임오버 화면에 실제로
   표시한다. `sim_result`로 방금 그 몬스터를 상대로 한 "AI 최적 플레이" 시뮬레이션과
   비교까지 한다 — 다만 다대일 전투에서는 이 비교가 근사치라는 한계가 있다(1:1
   프레이밍으로 설계된 모듈이라).
4. **실전 행동 로그 수집** — 실제 전투마다 `(state, action, result)` 레코드가
   `app/Shared.py`의 `_save_rl_log()`를 통해 DB `BattleLog` 테이블에 쌓인다
   (`TestFile/test_rl_log.py`로 검증됨). 향후 모방학습/RL 연구를 위한 원천 데이터.
5. **점수/선구자 랭킹 보드** — DB 기반, 실제 동작.

## 원래 있던 서술 중 지금도 사실과 다른 것

- **"LLM은 로그를 자연어로 해석하는 보조 도구로만 사용한다"** (이 문서와
  `README.md` "LLM 사용 범위" 공통 서술) — 여전히 사실과 다르다. `StatTuner`가
  담당하는 자동 역산과 별개로, `game/Enemy_Class.py`/`app/Map.py`의 수동 배율
  (`GRADE_MULT`/`_level_curve_mult`/`STAT_SCALE`/`_early_game_multi_scale`)은
  승률 목표에 맞춰 값을 직접 정하고 반복 조정하는 **핵심 판단**을 LLM(Claude)이
  수행한 것이다. 이 문서는 이번에 실제 상태에 맞게 갱신했지만, `README.md`는
  아직 이 서술을 그대로 갖고 있다 — 함께 손볼지는 결정이 필요하다.

## 격차가 있었던 이유 (기록용 — 지금은 해소됨)

`StatTuner`/`PlayerPowerIndex`가 미연결이라는 최초 판단은 오류였고(위 정정 참고),
실제로 미연결이었던 `BehaviorAnalyzer`/`FeedbackEngine`은 이 문서를 쓴 직후
`app/Battle.py`의 `_finish_battle()` → `core/Balance_Hook.py`의 `after_battle()`
경로로 연결을 완료했다(`TestFile/test_after_battle_feedback.py`로 회귀 테스트
고정, `CLAUDE.md`에 아키텍처 문서화). 격차가 왜 생겼었는지는 여전히 참고할
가치가 있다: 초기 CLI/시뮬레이터 시절(`README.md`가 지금은 없는 `Main.py`/
`ai.Battle_Engine`을 여전히 실행법으로 안내하는 것도 같은 흔적) 설계된
`after_battle()` 호출부가 Flask 기반 실서비스로 리팩터링되면서 재연결되지
않은 채 남아 있었던 것으로 보인다 — "왜 이 프로젝트에 이렇게 됐는지"를 설명할
때 참고할 것.
