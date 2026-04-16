"""
LOG_Manager.py
─────────────────────────────────────────────
전투 로그 저장 · 불러오기 모듈.

로그 포맷 예시:
  [00:00:03] 홍길동 → 고블린에게 셰이드 1 사용 | 데미지: 126 | 적HP: 201→75
  [00:00:05] 고블린 → 홍길동에게 공격 | 데미지: 43 | 플레이어HP: 200→157
  [00:00:07] 홍길동 → HP_M_potion 사용 | 플레이어HP: 60→160
  [00:00:09] 홍길동 → 고블린에게 파이어볼 1 사용 ★크리! | 데미지: 189 | 적HP: 75→-114
  [전투종료] 홍길동 승리 | 총 4턴 | 잔여HP: 160
"""

from typing import Optional, List
import json
import os
import time
from datetime import datetime
from dataclasses import asdict

from ai.Battle_Engine import BattleResult, TurnLog


# ────────────────────────────────────────────
# 경로 설정 — 루트 디렉토리 기준
# ────────────────────────────────────────────

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))  # ai/
ROOT_DIR   = os.path.dirname(_THIS_DIR)                   # AI_RPG_ENGINE/
DATA_DIR   = os.path.join(ROOT_DIR, "data")
SIM_DIR    = os.path.join(DATA_DIR, "Simul_LOG")
PLAYER_DIR = os.path.join(DATA_DIR, "Player_LOG")

def _ensure_dirs():
    for d in [SIM_DIR, PLAYER_DIR]:
        os.makedirs(d, exist_ok=True)


# ────────────────────────────────────────────
# 로그 포맷터 — 사람이 읽기 좋은 텍스트 변환
# ────────────────────────────────────────────

class LogFormatter:
    """
    TurnLog 리스트 → 읽기 좋은 텍스트 로그로 변환.

    포맷:
      [경과시간] 행동자 → 대상에게 행동 | 데미지: N | HP 변화
    """

    @staticmethod
    def format_log(
        logs: list,
        player_name: str,
        enemy_name:  str,
        winner:      str,
        start_time:  float = None,   # time.time() 기준 시작 시각
        total_turns: int   = 0,
        final_player_hp: float = 0,
    ) -> str:
        lines = []
        lines.append(f"{'='*55}")
        lines.append(f"  전투 로그 — {player_name} vs {enemy_name}")
        lines.append(f"  기록 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"{'='*55}")

        # HP 추적 (로그에서 역산)
        # 각 TurnLog의 hp_after 활용
        prev_enemy_hp  = None
        prev_player_hp = None

        for log in logs:
            # 경과 시간 (시작 시각 없으면 턴 번호로 대체)
            time_tag = f"[턴{log.turn:>3}]"

            tag = ""
            if log.is_crit:  tag += " ★크리!"
            if log.is_dodge: tag += " (회피)"

            if log.actor == "player":
                actor  = player_name
                target = enemy_name

                if log.action == "attack":
                    action_str = "공격"
                    if log.is_dodge:
                        line = f"{time_tag} {actor} → {target}에게 {action_str}{tag} | 회피당함"
                    else:
                        hp_before = round(log.hp_after + log.damage_dealt, 1)
                        line = (f"{time_tag} {actor} → {target}에게 {action_str}{tag} "
                                f"| 데미지: {log.damage_dealt} "
                                f"| 적HP: {hp_before}→{round(log.hp_after,1)}")

                elif log.action == "skill":
                    if log.is_dodge:
                        line = f"{time_tag} {actor} → {target}에게 {log.action_detail}{tag} | 회피당함"
                    else:
                        hp_before = round(log.hp_after + log.damage_dealt, 1)
                        line = (f"{time_tag} {actor} → {target}에게 {log.action_detail} 사용{tag} "
                                f"| 데미지: {log.damage_dealt} "
                                f"| 적HP: {hp_before}→{round(log.hp_after,1)}")

                elif log.action == "item":
                    line = (f"{time_tag} {actor} → {log.action_detail} 사용 "
                            f"| 플레이어HP: →{round(log.hp_after,1)} "
                            f"(MP: {round(log.mp_after,1)})")

                else:
                    line = f"{time_tag} {actor} → 대기"

            else:  # enemy
                actor  = enemy_name
                target = player_name

                if log.action == "attack":
                    if log.is_dodge:
                        line = f"{time_tag} {actor} → {target}에게 공격{tag} | 회피"
                    else:
                        hp_before = round(log.hp_after + log.damage_dealt, 1)
                        line = (f"{time_tag} {actor} → {target}에게 공격{tag} "
                                f"| 데미지: {log.damage_dealt} "
                                f"| 플레이어HP: {hp_before}→{round(log.hp_after,1)}")
                else:
                    line = f"{time_tag} {actor} → 행동"

            lines.append(line)

        # 전투 종료 요약
        winner_name = player_name if winner == "player" else enemy_name
        lines.append(f"{'─'*55}")
        lines.append(f"[전투종료] {winner_name} 승리 | 총 {total_turns}턴 "
                     f"| 플레이어 잔여HP: {round(final_player_hp,1)}")
        lines.append(f"{'='*55}")

        return "\n".join(lines)


# ────────────────────────────────────────────
# 직렬화 / 역직렬화
# ────────────────────────────────────────────

class LogSerializer:

    @staticmethod
    def result_to_dict(result: BattleResult, extra: dict = None) -> dict:
        data = {
            "winner":          result.winner,
            "total_turns":     result.total_turns,
            "final_player_hp": result.final_player_hp,
            "final_enemy_hp":  result.final_enemy_hp,
            "player_name":     result.player_name,
            "enemy_name":      result.enemy_name,
            "final_player_items": list(getattr(result, "final_player_items", [])),
            "logs": [
                {
                    "turn":          log.turn,
                    "actor":         log.actor,
                    "action":        log.action,
                    "action_detail": log.action_detail,
                    "damage_dealt":  log.damage_dealt,
                    "hp_after":      log.hp_after,
                    "mp_after":      log.mp_after,
                    "is_dodge":      log.is_dodge,
                    "is_crit":       log.is_crit,
                    "debuff_applied": log.debuff_applied,
                    "escaped":       log.escaped,
                    "player_pt":     log.player_pt,
                    "enemy_pt":      log.enemy_pt,
                }
                for log in result.logs
            ],
        }
        if extra:
            data.update(extra)
        return data

    @staticmethod
    def dict_to_result(data: dict) -> BattleResult:
        logs = [
            TurnLog(
                turn=e["turn"], actor=e["actor"],
                action=e["action"], action_detail=e["action_detail"],
                damage_dealt=e["damage_dealt"], hp_after=e["hp_after"],
                mp_after=e["mp_after"], is_dodge=e["is_dodge"], is_crit=e["is_crit"],
                debuff_applied=e.get("debuff_applied", ""),
                escaped=e.get("escaped", False),
                player_pt=e.get("player_pt", 0.0),
                enemy_pt=e.get("enemy_pt", 0.0),
            )
            for e in data["logs"]
        ]
        return BattleResult(
            winner=data["winner"], total_turns=data["total_turns"],
            final_player_hp=data["final_player_hp"],
            final_enemy_hp=data["final_enemy_hp"],
            player_name=data["player_name"], enemy_name=data["enemy_name"],
            logs=logs,
            final_player_items=data.get("final_player_items", []),
        )


# ────────────────────────────────────────────
# 로그 매니저
# ────────────────────────────────────────────

class LogManager:

    def __init__(self):
        _ensure_dirs()

    # ── 저장 ──────────────────────────────────

    def save_sim_log(
        self,
        result:        BattleResult,
        player_lv:     int,
        difficulty:    str,
        win_rate:      float,
        monster_stats: dict = None,
    ) -> str:
        """시뮬레이션 로그 저장 — JSON + 텍스트 동시 저장"""
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        base     = f"{result.player_name}_lv{player_lv}_{result.enemy_name}_{difficulty}_{ts}"
        json_path = os.path.join(SIM_DIR, base + ".json")
        txt_path  = os.path.join(SIM_DIR, base + ".txt")

        extra = {
            "log_type": "simulation", "difficulty": difficulty,
            "player_lv": player_lv, "win_rate": win_rate,
            "timestamp": ts, "monster_stats": monster_stats or {},
        }

        # JSON 저장
        data = LogSerializer.result_to_dict(result, extra)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 텍스트 로그 저장
        txt = LogFormatter.format_log(
            logs=result.logs,
            player_name=result.player_name,
            enemy_name=result.enemy_name,
            winner=result.winner,
            total_turns=result.total_turns,
            final_player_hp=result.final_player_hp,
        )
        # 헤더에 시뮬레이션 정보 추가
        header = (f"[시뮬레이션 로그] 난이도: {difficulty} | "
                  f"승률: {win_rate*100:.1f}% | LV{player_lv}\n")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(header + txt)

        return json_path

    def save_player_log(
        self,
        result:     BattleResult,
        player_lv:  int,
        items_used: list = None,
    ) -> str:
        """플레이어 실전 로그 저장 — JSON + 텍스트 동시 저장"""
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        base      = f"{result.player_name}_lv{player_lv}_{result.enemy_name}_{ts}"
        json_path = os.path.join(PLAYER_DIR, base + ".json")
        txt_path  = os.path.join(PLAYER_DIR, base + ".txt")

        extra = {
            "log_type": "player", "player_lv": player_lv,
            "timestamp": ts, "items_used": items_used or [],
        }

        # JSON 저장
        data = LogSerializer.result_to_dict(result, extra)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 텍스트 로그 저장
        txt = LogFormatter.format_log(
            logs=result.logs,
            player_name=result.player_name,
            enemy_name=result.enemy_name,
            winner=result.winner,
            total_turns=result.total_turns,
            final_player_hp=result.final_player_hp,
        )
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(txt)

        return json_path

    # ── 불러오기 ─────────────────────────────

    def load_latest_sim_log(
        self, enemy_name: str, difficulty: str, player_lv: int,
    ) -> Optional[BattleResult]:
        candidates = self._find_logs(SIM_DIR, enemy_name=enemy_name,
                                     difficulty=difficulty, player_lv=player_lv,
                                     ext=".json")
        if not candidates:
            return None
        return self._load_file(os.path.join(SIM_DIR, sorted(candidates)[-1]))

    def load_latest_player_log(
        self, enemy_name: str, player_lv: int, winner: str = None,
    ) -> Optional[BattleResult]:
        candidates = self._find_logs(PLAYER_DIR, enemy_name=enemy_name,
                                     player_lv=player_lv, ext=".json")
        if not candidates:
            return None
        for filename in sorted(candidates, reverse=True):
            result = self._load_file(os.path.join(PLAYER_DIR, filename))
            if result and (winner is None or result.winner == winner):
                return result
        return None

    def load_all_player_logs(
        self, player_name: str = None, enemy_name: str = None,
    ) -> List[BattleResult]:
        results = []
        if not os.path.exists(PLAYER_DIR):
            return results
        for filename in sorted(os.listdir(PLAYER_DIR)):
            if not filename.endswith(".json"):
                continue
            if player_name and player_name not in filename: continue
            if enemy_name  and enemy_name  not in filename: continue
            r = self._load_file(os.path.join(PLAYER_DIR, filename))
            if r:
                results.append(r)
        return results

    # ── 내부 유틸 ────────────────────────────

    def _find_logs(self, directory, enemy_name=None, difficulty=None,
                   player_lv=None, ext=".json") -> List[str]:
        result = []
        if not os.path.exists(directory):
            return result
        for filename in os.listdir(directory):
            if not filename.endswith(ext): continue
            if enemy_name  and enemy_name  not in filename: continue
            if difficulty  and difficulty  not in filename: continue
            if player_lv   and f"lv{player_lv}" not in filename: continue
            result.append(filename)
        return result

    def _load_file(self, path: str) -> Optional[BattleResult]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return LogSerializer.dict_to_result(data)
        except Exception:
            return None

    def print_summary(self, result: BattleResult):
        print(LogFormatter.format_log(
            logs=result.logs,
            player_name=result.player_name,
            enemy_name=result.enemy_name,
            winner=result.winner,
            total_turns=result.total_turns,
            final_player_hp=result.final_player_hp,
        ))
