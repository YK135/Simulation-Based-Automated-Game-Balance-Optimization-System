# -*- coding: utf-8 -*-
"""
scripts/view_errors.py — core/ErrorLog.py가 쌓은 서버 에러 조회
─────────────────────────────────────────────
이 앱엔 로그인/관리자 권한 시스템이 없어서 웹 페이지로 노출하지 않고,
로컬에서 이 스크립트로 직접 조회한다. DATABASE_URL 환경변수를 Render의
Postgres 연결 문자열로 설정하고 실행하면 운영 환경 에러도 그대로 볼 수 있음
(로컬 SQLite로 실행하면 로컬에서 쌓인 것만 보임).

실행:
    python3 scripts/view_errors.py                # 최근 20건
    python3 scripts/view_errors.py 50              # 최근 50건
    python3 scripts/view_errors.py --context shop_buy   # context로 필터
    python3 scripts/view_errors.py --full 3         # 최근 3건, traceback 전체 출력

운영 DB 조회 예:
    DATABASE_URL="postgresql://..." python3 scripts/view_errors.py
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DB import get_session as db_session
from DB.Models import ErrorLog


def main():
    args = sys.argv[1:]
    show_full = "--full" in args
    if show_full:
        args.remove("--full")

    context_filter = None
    if "--context" in args:
        idx = args.index("--context")
        context_filter = args[idx + 1]
        del args[idx:idx + 2]

    limit = int(args[0]) if args else 20

    with db_session() as db:
        q = db.query(ErrorLog).order_by(ErrorLog.created_at.desc())
        if context_filter:
            q = q.filter(ErrorLog.context == context_filter)
        rows = q.limit(limit).all()

        if not rows:
            print("에러 로그가 없습니다" +
                  (f" (context={context_filter})" if context_filter else "") + ".")
            return

        print(f"최근 {len(rows)}건" +
              (f" (context={context_filter})" if context_filter else "") + ":\n")

        for row in rows:
            ts = row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "?"
            where = f"{row.request_method} {row.request_path}" if row.request_path else "(요청 밖)"
            user = f"user={row.user_id}" if row.user_id else "guest"
            print(f"[{ts}] {row.context} — {row.error_type} | {where} | {user}")
            print(f"  {row.error_message}")
            if show_full and row.traceback:
                print("  " + row.traceback.replace("\n", "\n  "))
            print()

        # context별 집계 — 어떤 종류가 가장 자주 나는지 한눈에
        from collections import Counter
        all_contexts = [r.context for r in db.query(ErrorLog.context).all()]
        if all_contexts:
            print("─" * 40)
            print("전체 context별 건수:")
            for ctx, cnt in Counter(all_contexts).most_common():
                print(f"  {ctx}: {cnt}건")


if __name__ == "__main__":
    main()
