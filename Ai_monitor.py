"""
Ai_monitor.py — AI 밸런싱 모니터 창
파일 기반 IPC: /tmp/ai_monitor_pipe.txt 를 폴링해서 출력.
__DONE__ 수신 시 2초 후 종료.
"""
from __future__ import annotations
import sys, time, os

PIPE_FILE = "/tmp/ai_monitor_pipe.txt"
READ_FILE = "/tmp/ai_monitor_read.txt"  # 읽은 위치 추적

os.system('cls' if os.name == 'nt' else 'clear')
print("=" * 48)
print("    AI 밸런싱 모니터")
print("=" * 48)
print()
sys.stdout.flush()

# 기존 파일 초기화
for f in [PIPE_FILE, READ_FILE]:
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

# 시작 신호 대기 (최대 10초)
waited = 0
while not os.path.exists(PIPE_FILE) and waited < 10:
    time.sleep(0.2)
    waited += 0.2

read_pos = 0
done = False

try:
    while not done:
        time.sleep(0.15)
        if not os.path.exists(PIPE_FILE):
            continue
        try:
            with open(PIPE_FILE, "r", encoding="utf-8") as f:
                f.seek(read_pos)
                new_content = f.read()
                read_pos = f.tell()

            if new_content:
                for line in new_content.splitlines():
                    if line == "__DONE__":
                        done = True
                        break
                    print(line)
                    sys.stdout.flush()
        except Exception:
            pass

except KeyboardInterrupt:
    pass

print()
print("=" * 48)
print("    분석 완료 — 2초 후 창 닫힘")
print("=" * 48)
sys.stdout.flush()
time.sleep(2.0)

# 파일 정리
for f in [PIPE_FILE, READ_FILE]:
    try:
        os.remove(f)
    except Exception:
        pass