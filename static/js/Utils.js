/* ═══════════════════════════════════════════════════════════
   Utils.js — 공통 UI 유틸 (null 안전 가드)
   ★ 통째 교체용 ★

   변경: terminal / clock / toast / log-area 요소가 없을 때
         조용히 무시. 다음 코드가 멈추지 않게.
   ═══════════════════════════════════════════════════════════ */

// ── 상단 시계 ──
function tick() {
    const el = document.getElementById('clock');
    if (!el) return;   // ★ 안전 가드
    const d = new Date();
    el.textContent =
        String(d.getHours()).padStart(2,'0') + ':' +
        String(d.getMinutes()).padStart(2,'0') + ':' +
        String(d.getSeconds()).padStart(2,'0');
}

// ── 토스트 알림 (우상단) ──
let toastTimer;
function toast(msg, type='') {
    const t = document.getElementById('toast');
    if (!t) {
        console.log('[toast]', msg);   // ★ fallback: 콘솔 출력
        return;
    }
    t.className = 'toast active' + (type ? ' '+type : '');
    t.textContent = msg;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('active'), 2500);
}

// ── 시스템 터미널 (우측 하단) ──
function term(msg, type='') {
    const t = document.getElementById('terminal');
    if (!t) {
        // ★ 안전 가드: 터미널 div가 없으면 콘솔에만 출력
        console.log(`[term]`, msg);
        return;
    }
    const d = new Date();
    const ts = String(d.getHours()).padStart(2,'0') + ':' +
               String(d.getMinutes()).padStart(2,'0') + ':' +
               String(d.getSeconds()).padStart(2,'0');
    const line = document.createElement('div');
    line.className = 'terminal-line ' + type;
    line.innerHTML = `<span class="ts">[${ts}]</span> ${msg}`;
    t.appendChild(line);
    t.scrollTop = t.scrollHeight;
    while (t.children.length > 30) t.removeChild(t.firstChild);
}

// ── 배틀 로그 (중앙) ──
function logLine(msg, type='') {
    // 두 가지 ID 모두 시도 — 옛(#log-area) / 새(#battle-log)
    const l = document.getElementById('log-area') || document.getElementById('battle-log');
    if (!l) {
        console.log('[log]', msg);   // ★ 안전 가드
        return;
    }
    const d = new Date();
    const ts = String(d.getHours()).padStart(2,'0') + ':' +
               String(d.getMinutes()).padStart(2,'0') + ':' +
               String(d.getSeconds()).padStart(2,'0');
    const line = document.createElement('div');
    line.className = 'log-line ' + type;
    line.innerHTML = `<span class="log-time">[${ts}]</span> ${msg}`;
    l.appendChild(line);
    l.scrollTop = l.scrollHeight;
    while (l.children.length > 50) l.removeChild(l.firstChild);
}

function clearLog() {
    const l = document.getElementById('log-area') || document.getElementById('battle-log');
    if (l) l.innerHTML = '';
}