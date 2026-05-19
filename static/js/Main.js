/* ═══════════════════════════════════════════════════════════
   Main.js — 부트스트랩 + 이벤트 바인딩
   ★ 통째 교체용 ★

   변경:
   - safeBind 헬퍼 함수 정의 추가
   - 랭킹 버튼 바인딩 — 안전하게 (요소 없어도 부팅 안 멈춤)
   ═══════════════════════════════════════════════════════════ */

// ─────────────────────────────────────────────
// 헬퍼: 안전한 이벤트 바인딩
//   요소가 없으면 콘솔 경고만, 부팅 안 멈춤.
// ─────────────────────────────────────────────
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

// ── 펜타곤 차트 초기 ──
drawPentagonBackground();
updatePentagon([0.7,0.7,0.7,0.7,0.7], [0.65,0.7,0.7,0.65,0.65]);

// ═══════════════════════════════════════════════════════════
// 3단계 시작 모달 이벤트 바인딩
// ═══════════════════════════════════════════════════════════

// ── 모달 1 (entry): 즉시 / 이메일 플레이 ──
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

// ── 모달 2 (email): 이메일 인증 ──
safeBind('btn-email-send', typeof sendEmailCode === 'function' ? sendEmailCode : null);
safeBind('btn-email-verify', typeof verifyEmailCode === 'function' ? verifyEmailCode : null);
safeBind('btn-email-back', typeof backToEntry === 'function' ? backToEntry : null);

// 엔터 키 지원
const emailInput = document.getElementById('input-email');
if (emailInput) {
    emailInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (typeof sendEmailCode === 'function') sendEmailCode();
        }
    });
}
const emailCodeInput = document.getElementById('input-email-code');
if (emailCodeInput) {
    emailCodeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (typeof verifyEmailCode === 'function') verifyEmailCode();
        }
    });
}

// ── 모달 3 (newgame): 직업 선택 + 닉네임 ──
document.querySelectorAll('.job-btn').forEach(btn => {
    btn.onclick = () => {
        if (typeof selectJob === 'function') selectJob(btn.dataset.job);
    };
});

safeBind('btn-newgame-confirm', () => {
    const nameEl = document.getElementById('input-name');
    const name = nameEl ? (nameEl.value.trim() || 'HERO') : 'HERO';
    const job  = state.selectedJob || '전사';
    newGame(name, job);
});

// 닉네임 엔터
const nameInput = document.getElementById('input-name');
if (nameInput) {
    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const btn = document.getElementById('btn-newgame-confirm');
            if (btn) btn.click();
        }
    });
}

// ── 게임 종료 후 NEW GAME ──
safeBind('btn-restart', () => {
    if (typeof showStartModal === 'function') {
        showStartModal('modal-entry');
    } else {
        const m = document.getElementById('modal-newgame');
        if (m) m.classList.add('active');
    }
});

// ── 탐험 ──
safeBind('btn-explore', explore);

// ── 휴식 모달 ──
safeBind('btn-rest-heal',  () => performRest('heal'));
safeBind('btn-rest-train', () => performRest('train'));

// ── 전투 행동 ──
safeBind('btn-attack', () => battleAction(_withTarget('attack')));
safeBind('btn-skill', () => {
    const sm = document.getElementById('skill-menu');
    const im = document.getElementById('item-menu');
    if (sm) sm.classList.toggle('active');
    if (im) im.classList.remove('active');
});
safeBind('btn-item', () => {
    const sm = document.getElementById('skill-menu');
    const im = document.getElementById('item-menu');
    if (im) im.classList.toggle('active');
    if (sm) sm.classList.remove('active');
});

// ── 도망 모달 ──
safeBind('btn-escape', () => {
    if (state.battleState && state.battleState.is_boss) return;
    const m = document.getElementById('modal-escape');
    if (m) m.classList.add('active');
});
safeBind('btn-escape-yes', () => {
    const m = document.getElementById('modal-escape');
    if (m) m.classList.remove('active');
    battleAction('escape');
});
safeBind('btn-escape-no', () => {
    const m = document.getElementById('modal-escape');
    if (m) m.classList.remove('active');
    term('escape canceled', 'warn');
});

// ── AI Level 토글 ──
document.querySelectorAll('.ai-level-btn').forEach(btn => {
    btn.onclick = () => {
        document.querySelectorAll('.ai-level-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.aiLevel = btn.dataset.level;
        term(`AI level set: ${state.aiLevel}`);
    };
});

// ── 시뮬 컨트롤 ──
safeBind('btn-sim-start', () => {
    term('manual sim start', 'ok');
    if (typeof animateBalanceTuning === 'function') animateBalanceTuning();
});
safeBind('btn-sim-stop', () => {
    term('sim stopped', 'warn');
});

// ── ★ 랭킹 모달 열기 ──
safeBind('btn-ranking', () => {
    if (typeof openRankingModal === 'function') {
        openRankingModal();
    } else {
        console.warn('openRankingModal not loaded');
    }
});

// ── 키보드 단축키 ──
document.addEventListener('keydown', (e) => {
    if (!state.inBattle) return;
    if (e.key === 'F1') {
        e.preventDefault();
        const b = document.getElementById('btn-skill');
        if (b) b.click();
    }
    if (e.key === 'F2') {
        e.preventDefault();
        const b = document.getElementById('btn-item');
        if (b) b.click();
    }
    if (e.key === '1') {
        const b = document.getElementById('btn-attack');
        if (b) b.click();
    }
});

// ── 세션 자동 복구 ──
(async () => {
    term('booting...');
    try {
        const ok = await loadStatus();
        if (ok) {
            // 모든 시작 모달 닫기
            ['modal-entry', 'modal-email', 'modal-newgame'].forEach(id => {
                const m = document.getElementById(id);
                if (m) m.classList.remove('active');
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