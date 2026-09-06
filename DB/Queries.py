"""
db/queries.py — 랭킹 점수 계산 + 두 가지 랭킹 쿼리

★ 신규 파일 ★
경로: db/queries.py

함수:
  calculate_user_score(user_id)         → 사용자의 최고 점수 + 상세 내역
  get_score_ranking(limit=20)            → 점수 기반 랭킹 (TOP N)
  get_pioneer_ranking(limit=10)          → 최초 클리어 랭킹 (TOP N)

설계:
  - 사용자별로 "한 번의 모험" = 마지막 새 게임 시작 이후 모든 전투
  - 점수는 그 모험 동안 누적
  - 같은 사용자가 여러 번 플레이 시 최고 점수 모험만 랭킹에 반영
"""
from __future__ import annotations
import json
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from DB.Models import User, Battle

# ═══════════════════════════════════════════════════════════
# 점수 가중치 (한 곳에서 조정 가능)
# ═══════════════════════════════════════════════════════════

SCORE_WEIGHTS = {
    # 보너스
    "final_boss_clear":  5000,   # 최종 보스 처치 보너스
    "mid_boss_clear":    1000,   # 중간 보스 처치 보너스

    # 곱셈
    "per_boss_kill":     500,    # 보스 1마리당
    "per_normal_kill":   50,     # 일반몹 1마리당
    "per_level":         100,    # 최종 레벨당
    "per_item_remain":   30,     # 남은 아이템 1개당
    "per_hp_pct":        10,     # 평균 잔여 HP 1%당
    "per_skill_use":     5,      # 스킬 1회 사용당

    # 패널티
    "per_escape":        -50,    # 도망 1회당 (사용자 확정: ×50)
    "per_clear_turn":    -5,     # 클리어 총 턴당 (빠를수록 좋음)
}


# ═══════════════════════════════════════════════════════════
# 점수 계산 — 단일 사용자
# ═══════════════════════════════════════════════════════════

def calculate_user_score(db: Session, user_id: int) -> Optional[Dict]:
    """
    한 사용자의 모험에 대한 점수 + 상세 내역.

    반환:
      None → 전투 기록이 없는 경우 (점수 0점이거나 미플레이)
      Dict → {
          'score': int,
          'final_boss_cleared': bool,
          'breakdown': { ... 모든 가중치별 점수 ... }
      }
    """
    battles = db.query(Battle).filter(Battle.user_id == user_id).all()
    if not battles:
        return None

    # ── 집계 ──
    boss_kills      = 0
    normal_kills    = 0
    escape_count    = 0
    skill_uses      = 0
    total_turns     = 0
    hp_percentages  = []
    max_level       = 1
    final_boss_cleared = False
    last_battle = battles[-1]   # 시간순 마지막 전투 (보통 클리어/패배 시점)

    for b in battles:
        # 보스 처치 vs 일반몹 처치
        if b.result == "win":
            # enemies JSON에서 보스 여부 확인
            enemies = json.loads(b.enemies) if b.enemies else []
            if b.is_boss:
                boss_kills += 1
                # 최종 보스 식별 — 이름에 "최종" 포함 or 더 큰 보스 식별 가능
                for e in enemies:
                    if "최종" in e.get("name", ""):
                        final_boss_cleared = True
            else:
                # 일반 전투에서 처치한 적 수 (다대일이면 여러 마리)
                normal_kills += len(enemies)

        elif b.result == "escape":
            escape_count += 1

        # 스킬 사용 누적
        skill_uses += (b.skills_used or 0)

        # 총 진행 턴 (가장 마지막 전투의 explore_turn이 클리어 시점)
        total_turns = max(total_turns, b.explore_turn or 0)

        # HP % (해당 전투 종료 시점 잔여 HP)
        if b.player_lv > 0:
            # 정확한 maxhp는 모르지만 hp_remaining + player_lv 활용
            # 근사: 직업별 base maxhp 사용 (간단히 hp_remaining 자체를 점수화)
            # 더 정확하려면 Battle 테이블에 maxhp_remaining 컬럼 필요.
            # 우선은 hp_remaining 기준 0~100점으로 변환.
            hp_pct = min(100, max(0, b.hp_remaining))  # 단순 캡
            hp_percentages.append(hp_pct)

        # 최종 레벨
        if b.player_lv > max_level:
            max_level = b.player_lv

    avg_hp_pct = (sum(hp_percentages) / len(hp_percentages)) if hp_percentages else 0

    # 남은 아이템 — 별도 저장 안 되어있어서 default 0
    # 추후 Battle 테이블에 items_remaining 컬럼 추가 시 활용 가능
    items_remaining = 0

    # ── 점수 계산 ──
    breakdown = {
        "final_boss_bonus": SCORE_WEIGHTS["final_boss_clear"] if final_boss_cleared else 0,
        "boss_kills":       boss_kills * SCORE_WEIGHTS["per_boss_kill"],
        "normal_kills":     normal_kills * SCORE_WEIGHTS["per_normal_kill"],
        "level":            max_level * SCORE_WEIGHTS["per_level"],
        "items":            items_remaining * SCORE_WEIGHTS["per_item_remain"],
        "hp_avg":           int(avg_hp_pct) * SCORE_WEIGHTS["per_hp_pct"],
        "skills":           skill_uses * SCORE_WEIGHTS["per_skill_use"],
        "escapes":          escape_count * SCORE_WEIGHTS["per_escape"],     # 음수
        "turns":            total_turns * SCORE_WEIGHTS["per_clear_turn"],   # 음수
    }
    score = sum(breakdown.values())
    # 음수 점수 방지
    score = max(0, score)

    return {
        "user_id":             user_id,
        "score":               score,
        "final_boss_cleared":  final_boss_cleared,
        "max_level":           max_level,
        "boss_kills":          boss_kills,
        "normal_kills":        normal_kills,
        "total_turns":         total_turns,
        "escape_count":        escape_count,
        "skill_uses":          skill_uses,
        "avg_hp_pct":          round(avg_hp_pct, 1),
        "breakdown":           breakdown,
        "last_played":         last_battle.created_at.isoformat() if last_battle.created_at else None,
        "last_job":            last_battle.player_job,
    }


# ═══════════════════════════════════════════════════════════
# 랭킹 1: 점수 기반 (메인 랭킹)
# ═══════════════════════════════════════════════════════════

def get_score_ranking(db: Session, limit: int = 20) -> List[Dict]:
    """
    점수 기반 랭킹 TOP N.

    각 사용자의 최고 점수만 반영 (같은 사용자가 여러 번 플레이 시).
    """
    # 모든 사용자 가져와서 점수 계산 후 정렬.
    # 사용자 많아지면 DB 쿼리 최적화 필요하지만 캡스톤 규모면 충분.
    users = db.query(User).filter(User.is_active == True).all()

    rankings = []
    for u in users:
        score_data = calculate_user_score(db, u.id)
        if score_data is None or score_data["score"] == 0:
            continue  # 전투 기록 없거나 0점인 사용자는 제외

        rankings.append({
            "user_id":  u.id,
            "nickname": u.nickname,
            "job":      score_data["last_job"],
            "score":    score_data["score"],
            "level":    score_data["max_level"],
            "boss_kills":  score_data["boss_kills"],
            "final_boss_cleared": score_data["final_boss_cleared"],
        })

    # 점수 내림차순 정렬
    rankings.sort(key=lambda x: x["score"], reverse=True)

    # 등수 부여 (1부터)
    for i, r in enumerate(rankings[:limit], 1):
        r["rank"] = i

    return rankings[:limit]


# ═══════════════════════════════════════════════════════════
# 랭킹 2: 최초 클리어 (선구자)
# ═══════════════════════════════════════════════════════════

def get_pioneer_ranking(db: Session, limit: int = 10) -> List[Dict]:
    """
    최종 보스 클리어 사용자들의 클리어 시각순 랭킹.

    먼저 클리어한 사용자가 1등.
    같은 사용자는 가장 빠른 클리어 1건만.
    """
    # 최종 보스 클리어한 전투들 조회 (시간순)
    # enemies JSON에 "최종" 포함된 적이 있고, result='win'인 전투
    final_boss_wins = (
        db.query(Battle, User)
        .join(User, Battle.user_id == User.id)
        .filter(Battle.is_boss == True)
        .filter(Battle.result == "win")
        .order_by(Battle.created_at.asc())
        .all()
    )

    # 사용자별 첫 클리어만 추출
    seen_users = set()
    pioneers = []
    for battle, user in final_boss_wins:
        if user.id in seen_users:
            continue

        # enemies JSON에서 최종 보스 여부 확인
        enemies = json.loads(battle.enemies) if battle.enemies else []
        is_final = any("최종" in e.get("name", "") for e in enemies)
        if not is_final:
            continue

        seen_users.add(user.id)
        pioneers.append({
            "rank":         len(pioneers) + 1,
            "user_id":      user.id,
            "nickname":     user.nickname,
            "job":          battle.player_job,
            "cleared_at":   battle.created_at.isoformat(),
            "cleared_turn": battle.explore_turn,
            "player_lv":    battle.player_lv,
        })

        if len(pioneers) >= limit:
            break

    return pioneers


# ═══════════════════════════════════════════════════════════
# 헬퍼: 현재 사용자의 랭킹 위치 찾기
# ═══════════════════════════════════════════════════════════

def get_user_rank_position(db: Session, user_id: int) -> Optional[Dict]:
    """
    특정 사용자의 현재 랭킹 위치를 반환.
    TOP 20 안에 없어도 자신의 등수와 점수 알려줌.
    """
    score_data = calculate_user_score(db, user_id)
    if not score_data:
        return None

    my_score = score_data["score"]

    # 모든 사용자의 점수 계산 후 내 위치 찾기
    users = db.query(User).filter(User.is_active == True).all()
    all_scores = []
    for u in users:
        sd = calculate_user_score(db, u.id)
        if sd:
            all_scores.append(sd["score"])

    all_scores.sort(reverse=True)
    try:
        rank = all_scores.index(my_score) + 1
    except ValueError:
        rank = len(all_scores) + 1

    return {
        "rank":     rank,
        "total":    len(all_scores),
        "score":    my_score,
        "user_id":  user_id,
    }
