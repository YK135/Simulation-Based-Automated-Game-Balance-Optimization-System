/* ═══════════════════════════════════════════════════════════
   main.js — 부트스트랩 + 이벤트 바인딩
   가장 마지막에 로드. 다른 모든 함수가 정의된 후 실행.
   - 시계 시작
   - 펜타곤 차트 초기 그리기
   - 모든 버튼/모달 onclick 바인딩
   - 키보드 단축키
   - 세션 자동 복구
   ═══════════════════════════════════════════════════════════ */

// ── 시계 시작 ──
setInterval(tick, 1000);
tick();

// ── 펜타곤 차트 초기 ──
drawPentagonBackground();
updatePentagon([0.7,0.7,0.7,0.7,0.7], [0.65,0.7,0.7,0.65,0.65]);

// ── 새 게임 모달 ──
// ═══════════════════════════════════════════════════════════
// 3단계 시작 모달 이벤트 바인딩
// ═══════════════════════════════════════════════════════════

// ── 모달 1 (entry): 즉시 / 이메일 플레이 선택 ──
document.getElementById('btn-entry-instant').onclick = () => {
    // 게스트 플레이 — 바로 직업 선택 모달로
    state.isEmailAuth = false;
    state.userEmail = null;
    showStartModal('modal-newgame');
    selectJob(state.selectedJob || '전사');  // 초기 미리보기
    term('instant play selected (guest)', 'ok');
};

document.getElementById('btn-entry-email').onclick = () => {
    // 이메일 인증 플레이 — 이메일 모달로
    showStartModal('modal-email');
    setTimeout(() => document.getElementById('input-email').focus(), 100);
    term('email play selected', 'ok');
};

// ── 모달 2 (email): 이메일 인증 ──
document.getElementById('btn-email-send').onclick = sendEmailCode;
document.getElementById('btn-email-verify').onclick = verifyEmailCode;
document.getElementById('btn-email-back').onclick = backToEntry;

// 엔터 키 지원: 이메일 입력 후 엔터 → 코드 전송, 코드 입력 후 엔터 → 인증
document.getElementById('input-email').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        sendEmailCode();
    }
});
document.getElementById('input-email-code').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        verifyEmailCode();
    }
});

// ── 모달 3 (newgame): 직업 선택 + 닉네임 ──
// 직업 버튼 4종 — 클릭 시 좌측 초상화/우측 설명 갱신
document.querySelectorAll('.job-btn').forEach(btn => {
    btn.onclick = () => selectJob(btn.dataset.job);
});

// 시작 버튼
document.getElementById('btn-newgame-confirm').onclick = () => {
    const name = document.getElementById('input-name').value.trim() || 'HERO';
    const job  = state.selectedJob || '전사';
    newGame(name, job);
};

// 닉네임 입력란에서 엔터 → 시작
document.getElementById('input-name').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        document.getElementById('btn-newgame-confirm').click();
    }
});

// ── 게임 종료 후 NEW GAME 버튼: 처음(entry)으로 돌아가기 ──
// 이전엔 modal-newgame을 바로 띄웠지만, 이제 시작 플로우 처음부터 다시.
document.getElementById('btn-restart').onclick = () => {
    showStartModal('modal-entry');
};

// ── 탐험 ──
document.getElementById('btn-explore').onclick = explore;

// ── 휴식 모달 (heal/train) ──
document.getElementById('btn-rest-heal').onclick  = () => performRest('heal');
document.getElementById('btn-rest-train').onclick = () => performRest('train');

// ── 전투 행동 ──
document.getElementById('btn-attack').onclick = () => battleAction(_withTarget('attack'));
document.getElementById('btn-skill').onclick  = () => {
    document.getElementById('skill-menu').classList.toggle('active');
    document.getElementById('item-menu').classList.remove('active');
};
document.getElementById('btn-item').onclick   = () => {
    document.getElementById('item-menu').classList.toggle('active');
    document.getElementById('skill-menu').classList.remove('active');
};

// ── 도망 모달 (Y/N) ──
document.getElementById('btn-escape').onclick = () => {
    if (state.battleState && state.battleState.is_boss) return;
    document.getElementById('modal-escape').classList.add('active');
};
document.getElementById('btn-escape-yes').onclick = () => {
    document.getElementById('modal-escape').classList.remove('active');
    battleAction('escape');
};
document.getElementById('btn-escape-no').onclick = () => {
    document.getElementById('modal-escape').classList.remove('active');
    term('escape canceled', 'warn');
};

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
document.getElementById('btn-sim-start').onclick = () => {
    term('manual sim start', 'ok');
    animateBalanceTuning();
};
document.getElementById('btn-sim-stop').onclick = () => {
    term('sim stopped', 'warn');
};

// ── 키보드 단축키 ──
document.addEventListener('keydown', (e) => {
    if (!state.inBattle) return;
    if (e.key === 'F1') { e.preventDefault(); document.getElementById('btn-skill').click(); }
    if (e.key === 'F2') { e.preventDefault(); document.getElementById('btn-item').click(); }
    if (e.key === '1')  { document.getElementById('btn-attack').click(); }
});

// ── 세션 자동 복구 ──
(async () => {
    term('booting...');
    const ok = await loadStatus();
    if (ok) {
        document.getElementById('modal-newgame').classList.remove('active');
        term('session restored', 'ok');
        toast(`다시 오신 걸 환영합니다, ${state.player.name}`);
    } else {
        term('no session, awaiting input');
    }
})();

safeBind('btn-ranking', () => {
    if (typeof openRankingModal === 'function') {
        openRankingModal();
    }
});