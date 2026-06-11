/* ═══════════════════════════════════════════════════════════
   utils.js — 공통 UI 유틸
   - tick: 상단 시계
   - toast: 우상단 토스트 알림
   - term: 우측 시스템 터미널 로그
   - logLine: 중앙 배틀 로그
   - clearLog: 배틀 로그 비우기
   ═══════════════════════════════════════════════════════════ */

// ── 상단 시계 ──
function tick() {
    const d = new Date();
    document.getElementById('clock').textContent =
        String(d.getHours()).padStart(2,'0') + ':' +
        String(d.getMinutes()).padStart(2,'0') + ':' +
        String(d.getSeconds()).padStart(2,'0');
}

// ── 토스트 알림 (우상단) ──
let toastTimer;
function toast(msg, type='') {
    const t = document.getElementById('toast');
    t.className = 'toast active' + (type ? ' '+type : '');
    t.textContent = msg;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('active'), 2500);
}

// ── 시스템 터미널 (우측 하단) ──
function term(msg, type='') {
    const t = document.getElementById('terminal');
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
    const l = document.getElementById('log-area');
    const d = new Date();
    const ts = String(d.getHours()).padStart(2,'0') + ':' +
               String(d.getMinutes()).padStart(2,'0') + ':' +
               String(d.getSeconds()).padStart(2,'0');
    const line = document.createElement('div');
    line.className = 'log-line ' + type;
    line.innerHTML = `<span class="ts">[${ts}]</span> ${msg}`;
    l.appendChild(line);
    l.scrollTop = l.scrollHeight;
    while (l.children.length > 50) l.removeChild(l.firstChild);
}

function clearLog() {
    document.getElementById('log-area').innerHTML = '';
}


// ── 공통 아이콘 렌더 (이미지 우선 + 이모지 fallback) ──
//   meta: { icon: 이모지, img: 경로 } | undefined
//   className: wrap 클래스 (예 'item-icon')
function renderIconWithFallback(meta, className) {
    const wrap = document.createElement('span');
    wrap.className = className || 'icon-wrap';

    const fallback = document.createElement('span');
    fallback.className = 'icon-fallback';
    fallback.textContent = (meta && meta.icon) || '?';

    if (meta && meta.img) {
        const img = document.createElement('img');
        img.className = 'icon-img';
        img.src = meta.img;
        img.alt = '';
        img.draggable = false;
        img.addEventListener('error', () => {
            img.style.display = 'none';
            fallback.style.display = '';
        });
        img.addEventListener('load', () => {
            fallback.style.display = 'none';
        });
        wrap.appendChild(img);
    }
    wrap.appendChild(fallback);
    return wrap;
}