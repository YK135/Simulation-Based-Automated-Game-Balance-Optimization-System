# -*- coding: utf-8 -*-
"""
scripts/backfill_rl_log.py — data/RL_LOG/*.json → BattleLog 테이블 1회성 백필
─────────────────────────────────────────────
_save_rl_log()가 로컬 파일 대신 DB에 쓰도록 바뀌면서, 그 전에 이미 쌓여있던
data/RL_LOG/user_{id}/*.json 파일들을 DB로 옮기기 위한 스크립트.
반복 실행해도 안전(같은 파일을 중복 저장하지 않도록 파일 경로를 기록해서 스킵).

실행: python3 scripts/backfill_rl_log.py
"""
import sys, os, json, glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DB import get_session as db_session
from DB.Models import BattleLog

RL_LOG_DIR = os.path.join("data", "RL_LOG")


def main():
    files = sorted(glob.glob(os.path.join(RL_LOG_DIR, "user_*", "*.json")))
    if not files:
        print(f"[백필] {RL_LOG_DIR} 아래에 백필할 파일이 없습니다.")
        return

    inserted, skipped, failed = 0, 0, 0

    with db_session() as db:
        # 이미 백필된 파일은 meta_json 안에 _backfill_src로 기록해서 중복 방지
        existing_srcs = set()
        for row in db.query(BattleLog.meta_json).all():
            if not row[0] or '"_backfill_src"' not in row[0]:
                continue
            try:
                src = json.loads(row[0]).get("_backfill_src")
                if src:
                    existing_srcs.add(src)
            except Exception:
                pass

    for path in files:
        if path in existing_srcs:
            skipped += 1
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            print(f"  [실패] {path}: {e}")
            failed += 1
            continue

        meta = payload.get("meta", {})
        records = payload.get("records", [])

        # 게스트/실유저 구분 없이 파일명에서 user_id 추출 (user_{id} 폴더명 기준)
        user_dir = os.path.basename(os.path.dirname(path))
        uid_str = user_dir.replace("user_", "")
        user_id = int(uid_str) if uid_str.isdigit() else None

        meta = dict(meta)
        meta["_backfill_src"] = path

        try:
            with db_session() as db:
                db.add(BattleLog(
                    user_id=user_id,
                    meta_json=json.dumps(meta, ensure_ascii=False),
                    records_json=json.dumps(records, ensure_ascii=False),
                ))
            inserted += 1
        except Exception as e:
            print(f"  [실패] {path}: {e}")
            failed += 1

    print(f"[백필 완료] 총 {len(files)}개 중 삽입 {inserted} / 스킵(이미 백필됨) {skipped} / 실패 {failed}")


if __name__ == "__main__":
    main()
