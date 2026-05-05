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
document.getElementById('btn-newgame-confirm').onclick = () => {
    const name = document.getElementById('input-name').value.trim() || 'HERO';
    const job = document.getElementById('input-job').value;
    newGame(name, job);
};
document.getElementById('btn-restart').onclick = () => {
    document.getElementById('modal-newgame').classList.add('active');
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