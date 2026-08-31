/* ═══════════════════════════════════════════════════════════
   Main.js — 부트스트랩 + 이벤트 바인딩
   ═══════════════════════════════════════════════════════════ */

function safeBind(id, handler) {
    const el = document.getElementById(id);
    if (el) {
        el.onclick = handler;
    } else {
        console.warn(`[safeBind] element not found: #${id}`);
    }
}

// ── 시계 시작 ──
setInterval(tick, 1000);
tick();

// ═══════════════════════════════════════════════════════════
// 3단계 시작 모달 이벤트 바인딩
// ═══════════════════════════════════════════════════════════

safeBind('btn-entry-instant', () => {
    state.isEmailAuth = false;
    state.userEmail = null;
    if (typeof showStartModal === 'function') showStartModal('modal-newgame');
    if (typeof selectJob === 'function') selectJob(state.selectedJob || '전사');
    term('instant play selected (guest)', 'ok');
});

safeBind('btn-entry-email', () => {
    if (typeof showStartModal === 'function') showStartModal('modal-email');
    const input = document.getElementById('input-email');
    if (input) setTimeout(() => input.focus(), 100);
    term('email play selected', 'ok');
});

safeBind('btn-email-send',   typeof sendEmailCode   === 'function' ? sendEmailCode   : null);
safeBind('btn-email-verify', typeof verifyEmailCode === 'function' ? verifyEmailCode : null);
safeBind('btn-email-back',   typeof backToEntry     === 'function' ? backToEntry     : null);

const emailInput = document.getElementById('input-email');
if (emailInput) {
    emailInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); if (typeof sendEmailCode === 'function') sendEmailCode(); }
    });
}
const emailCodeInput = document.getElementById('input-email-code');
if (emailCodeInput) {
    emailCodeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); if (typeof verifyEmailCode === 'function') verifyEmailCode(); }
    });
}

document.querySelectorAll('.job-btn').forEach(btn => {
    btn.onclick = () => { if (typeof selectJob === 'function') selectJob(btn.dataset.job); };
});

safeBind('btn-newgame-confirm', () => {
    const nameEl = document.getElementById('input-name');
    const name = nameEl ? (nameEl.value.trim() || 'HERO') : 'HERO';
    const job  = state.selectedJob || '전사';
    newGame(name, job);
});

const nameInput = document.getElementById('input-name');
if (nameInput) {
    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); document.getElementById('btn-newgame-confirm')?.click(); }
    });
}

// ── 게임 종료 후 NEW GAME ──
// (게임 클리어/게임 오버 오버레이의 재시작 버튼도 동일 로직 사용 — restartGame())
function restartGame() {
    if (typeof showStartModal === 'function') showStartModal('modal-entry');
    else document.getElementById('modal-newgame')?.classList.add('active');
}
safeBind('btn-restart', restartGame);

// ── 휴식 모달 ──
safeBind('btn-rest-heal',  () => performRest('heal'));
safeBind('btn-rest-train', () => performRest('train'));

// ── 전투 행동 ──
safeBind('btn-attack', () => battleAction(_withTarget('attack')));
safeBind('btn-skill', () => {
    document.getElementById('skill-menu')?.classList.toggle('active');
    document.getElementById('item-menu')?.classList.remove('active');
});
safeBind('btn-item', () => {
    document.getElementById('item-menu')?.classList.toggle('active');
    document.getElementById('skill-menu')?.classList.remove('active');
});

// ── 도망 모달 ──
safeBind('btn-escape', () => {
    if (state.battleState && state.battleState.is_boss) return;
    document.getElementById('modal-escape')?.classList.add('active');
});
safeBind('btn-escape-yes', () => {
    document.getElementById('modal-escape')?.classList.remove('active');
    battleAction('escape');
});
safeBind('btn-escape-no', () => {
    document.getElementById('modal-escape')?.classList.remove('active');
    term('escape canceled', 'warn');
});

// ── 랭킹 모달 ──
safeBind('btn-ranking', () => {
    if (typeof openRankingModal === 'function') openRankingModal();
    else console.warn('openRankingModal not loaded');
});

// ── 키보드 단축키 ──
document.addEventListener('keydown', (e) => {
    if (!state.inBattle) return;
    if (e.key === 'F1') { e.preventDefault(); document.getElementById('btn-skill')?.click(); }
    if (e.key === 'F2') { e.preventDefault(); document.getElementById('btn-item')?.click(); }
    if (e.key === '1')  { document.getElementById('btn-attack')?.click(); }
});

// ── 세션 자동 복구 ──
(async () => {
    term('booting...');
    try {
        const ok = await loadStatus();
        if (ok) {
            ['modal-entry', 'modal-email', 'modal-newgame'].forEach(id => {
                document.getElementById(id)?.classList.remove('active');
            });
            term('session restored', 'ok');
            toast(`다시 오신 걸 환영합니다, ${state.player.name}`);
        } else {
            term('no session, awaiting input');
        }
    } catch (e) {
        console.warn('session restore failed:', e);
        term('booting failed', 'error');
    }
})();