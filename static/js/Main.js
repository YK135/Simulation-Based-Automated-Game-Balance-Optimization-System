/* ═══════════════════════════════════════════════════════════
   main.js — 부트스트랩 + 이벤트 바인딩
   가장 마지막에 로드. 다른 모든 함수가 정의된 후 실행.
   - 시계 시작
   - 펜타곤 차트 초기 그리기
   - 모든 버튼/모달 onclick 바인딩
   - 키보드 단축키
   - 세션 자동 복구
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
// 안전 가드: clock 요소가 없으면 tick 호출 자체를 스킵
try {
    if (document.getElementById('clock')) {
        setInterval(tick, 1000);
        tick();
    }
} catch (e) { console.warn('clock init:', e); }
 
 
// ── 펜타곤 차트 초기 ──
try {
    if (typeof drawPentagonBackground === 'function') {
        drawPentagonBackground();
    }
    if (typeof updatePentagon === 'function') {
        updatePentagon([0.7,0.7,0.7,0.7,0.7], [0.65,0.7,0.7,0.65,0.65]);
    }
} catch (e) { console.warn('pentagon init:', e); }
 
 
// ═══════════════════════════════════════════════════════════
// 시작 모달 — 옛 단일 모달 + 새 3단계 모달 모두 지원
// ═══════════════════════════════════════════════════════════
 
// 옛: 단일 모달 (input-name + input-job 드롭다운)
safeBind('btn-newgame-confirm', () => {
    const nameEl = document.getElementById('input-name');
    const jobEl  = document.getElementById('input-job');
    const name = nameEl ? (nameEl.value.trim() || 'HERO') : 'HERO';
    // 옛 드롭다운 또는 새 직업 선택 버튼의 state.selectedJob
    const job = jobEl ? jobEl.value : (state.selectedJob || '전사');
    newGame(name, job);
});
 
// 새: 모달 1 (entry) - 즉시 / 이메일 플레이 선택
safeBind('btn-entry-instant', () => {
    if (typeof showStartModal === 'function') {
        state.isEmailAuth = false;
        state.userEmail = null;
        showStartModal('modal-newgame');
        if (typeof selectJob === 'function') selectJob(state.selectedJob || '전사');
    }
});
 
safeBind('btn-entry-email', () => {
    if (typeof showStartModal === 'function') {
        showStartModal('modal-email');
        const input = document.getElementById('input-email');
        if (input) setTimeout(() => input.focus(), 100);
    }
});
 
// 새: 모달 2 (email)
safeBind('btn-email-send', typeof sendEmailCode === 'function' ? sendEmailCode : null);
safeBind('btn-email-verify', typeof verifyEmailCode === 'function' ? verifyEmailCode : null);
safeBind('btn-email-back', typeof backToEntry === 'function' ? backToEntry : null);
 
// 새: 직업 버튼 4종
document.querySelectorAll('.job-btn').forEach(btn => {
    if (typeof selectJob === 'function') {
        btn.onclick = () => selectJob(btn.dataset.job);
    }
});
 
 
// ── 다시 시작 (NEW GAME) ──
safeBind('btn-restart', () => {
    // 새 3단계 모달이 있으면 entry 모달부터, 없으면 단일 modal-newgame
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
    if (typeof animateBalanceTuning === 'function') {
        animateBalanceTuning();
    }
});
 
safeBind('btn-sim-stop', () => {
    term('sim stopped', 'warn');
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
 
    // 새 모달 3 미리보기 초기화 (있을 때만)
    if (typeof selectJob === 'function') {
        try { selectJob('전사'); } catch(e) {}
    }
 
    try {
        const ok = await loadStatus();
        if (ok) {
            // 모든 시작 모달 닫기 (옛 + 새)
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
        console.warn('session restore:', e);
        term('booting failed, see console', 'error');
    }
})();