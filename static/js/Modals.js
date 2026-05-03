/* ═══════════════════════════════════════════════════════════
   modals.js — 모달 동작 + 시뮬 가시화 애니메이션
   - 휴식 모달: showRestModal, performRest
   - 도망 모달: 표시는 main.js에서 (모달 오픈만)
     실제 도망 시도는 actions.js의 battleAction
   - animateBalanceTuning: 시뮬 binary search 애니메이션
   ═══════════════════════════════════════════════════════════ */

// 휴식 이벤트 모달 표시
function showRestModal() {
    const modal = document.getElementById('modal-rest');
    if (modal) modal.classList.add('active');
}

// 휴식 선택 (heal | train) → /api/rest 호출
async function performRest(choice) {
    const r = await api('/rest', { choice });
    if (!r.ok) {
        toast(r.error || '휴식 실패', 'error');
        return;
    }
    if (r.player) { state.player = r.player; refreshPlayer(); }
    const icon = choice === 'heal' ? '✚' : '⚡';
    if (r.message) {
        logLine(`${icon} ${r.message}`, 'heal');
        term(`rest: ${choice}`, 'ok');
        toast(r.message);
    }
    document.getElementById('modal-rest').classList.remove('active');
}

// ── 시뮬 가시화 (시각 효과) ──
// 실시간으로 시뮬레이터가 binary search로 수렴하는 모습 보여주기.
// 우측 패널의 win rate 바 + state tuner + iter 카운터를
// 0.2초 간격으로 8회 진행하며 목표 승률에 점차 수렴.
function animateBalanceTuning() {
    let iter = 0;
    let wrPlayer = 50;
    const targetWR = state.aiLevel === 'hard' ? 45 :
                     state.aiLevel === 'easy' ? 70 : 60;
    const interval = setInterval(() => {
        iter++;
        wrPlayer = wrPlayer + (targetWR - wrPlayer) * 0.4 + (Math.random()-0.5)*8;
        const wrEnemy = 100 - wrPlayer;
        document.getElementById('wr-player').style.width = wrPlayer + '%';
        document.getElementById('wr-player-pct').textContent = Math.round(wrPlayer) + '%';
        document.getElementById('wr-enemy').style.width = wrEnemy + '%';
        document.getElementById('wr-enemy-pct').textContent = Math.round(wrEnemy) + '%';
        document.getElementById('sim-iter').textContent = iter;
        document.getElementById('sim-avg-turns').textContent = (12 + Math.random()*8).toFixed(0);

        const hpT = 50 + Math.sin(iter * 0.5) * 30;
        const dmgT = 50 + Math.cos(iter * 0.7) * 25;
        document.getElementById('tuner-hp').style.width = hpT + '%';
        document.getElementById('tuner-dmg').style.width = dmgT + '%';

        const err = Math.abs(wrPlayer - targetWR);
        document.getElementById('error-margin').textContent = '±' + err.toFixed(1) + '%';

        if (iter >= 8) {
            clearInterval(interval);
            term(`sim_${iter*250} converged. target=${targetWR}%`, 'ok');
        }
    }, 200);
}