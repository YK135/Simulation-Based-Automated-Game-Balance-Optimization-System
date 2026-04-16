# 시뮬레이션 기반 자동 밸런스 최적화 및 사용자 행동 분석 시스템

RPG 전투를 실험 환경으로 사용해 Monte Carlo 시뮬레이션, Binary Search, 플레이어 행동 로그 분석을 구현한
데이터 기반 의사결정 시스템입니다.

## 핵심 개념

- `BattleEngine`: 실전 전투와 시뮬레이션이 공유하는 단일 전투 엔진
- `BattleSimulator`: 같은 조건의 전투를 반복 실행해 승률을 계산하는 Monte Carlo 시뮬레이터
- `StatTuner`: 목표 승률에 맞도록 몬스터 스탯을 Binary Search로 역산하는 튜너
- `PlayerPowerIndex`: HP, MP, 스킬, 아이템, SPD를 반영한 동적 난이도 지표
- `BehaviorAnalyzer`: JSON 전투 로그를 집계해 플레이 패턴을 정량 분석하는 모듈
- `FeedbackEngine`: 분석 결과를 바탕으로 규칙 기반 플레이 피드백을 생성하는 모듈

## 실행

```bash
python3 Main.py
```

## 검증

```bash
PYTHONPYCACHEPREFIX=/tmp/ai_rpg_pycache python3 -m compileall Main.py ai core game interface
python3 -c 'from game.Player_Class import create_player_by_job; from game.Skill import Ply_Skill; from game.Enemy_Class import Make_Goblin; from ai.Battle_Engine import EntitySnapshot, BattleEngine; from ai.Auto_AI import PlayerAI, EnemyAI; p=create_player_by_job("테스트","전사"); p.skill=Ply_Skill("전사"); p.skill.update_skills(1); e=Make_Goblin(1,"중"); r=BattleEngine(EntitySnapshot.from_player(p), EntitySnapshot.from_enemy(e)).run(PlayerAI("balanced"), EnemyAI()); print(r.winner, r.total_turns)'
```

## 프로젝트 정체성

자세한 목표와 본질 정의는 [PROJECT_GOAL.md](PROJECT_GOAL.md)를 참고하세요.

## LLM 사용 범위

LLM은 핵심 판단 주체가 아닙니다. 승률 계산, 밸런스 역산, 행동 패턴 분석은 직접 구현한 규칙과 통계 로직이 담당하며,
LLM은 결과를 자연어로 설명하는 보조 역할로만 사용합니다.
