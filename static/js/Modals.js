/* ═══════════════════════════════════════════════════════════
   modals.js — 모달 동작 + 시뮬 가시화 애니메이션
   - 휴식 모달: showRestModal, performRest
   - 도망 모달: 표시는 main.js에서 (모달 오픈만)
     실제 도망 시도는 actions.js의 battleAction
   - animateBalanceTuning: 시뮬 binary search 애니메이션
   ═══════════════════════════════════════════════════════════ */

// 개발 모드 (배포 시 false로)
const IS_DEV = location.hostname === 'localhost' ||
               location.hostname === '127.0.0.1' ||
               location.hostname.startsWith('192.168.');

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

// ═══════════════════════════════════════════════════════════
// 3단계 시작 모달 — 전환 + 직업 미리보기 + 이메일 인증
// ═══════════════════════════════════════════════════════════

// ── 모달 전환 헬퍼 ──
// 시작 플로우 모달 3개 중 하나만 active. 나머지는 모두 비활성.
// 휴식/도망 같은 게임 중 모달은 영향 없음 (별도 ID).
function showStartModal(modalId) {
    ['modal-entry', 'modal-email', 'modal-newgame'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('active');
    });
    const target = document.getElementById(modalId);
    if (target) target.classList.add('active');
}


// ─────────────────────────────────────────────
// 모달 3: 직업 선택 시 초상화/설명 동적 갱신
// ─────────────────────────────────────────────

function selectJob(job) {
    if (!JOB_DATA[job]) return;
    state.selectedJob = job;

    const data = JOB_DATA[job];

    // 좌측 초상화 (현재는 아이콘 텍스트, 이미지로 교체 시 아래 분기)
    const iconEl = document.getElementById('job-icon');
    const nameEl = document.getElementById('job-name-display');
    if (iconEl) iconEl.textContent = data.icon;
    if (nameEl) nameEl.textContent = data.name;

    // 이미지로 교체 시:
    // const imgEl = document.getElementById('job-portrait-img');
    // if (imgEl && data.portrait_image) imgEl.src = data.portrait_image;

    // 우측 설명
    const descEl = document.getElementById('job-description');
    if (descEl) {
        const tagsHtml = (data.tags || [])
            .map(t => `<span class=\"job-tag\">${t}</span>`)
            .join('');
        descEl.innerHTML = `
            <div class=\"job-title\">${data.name} · ${job}</div>
            <div>${tagsHtml}</div>
            <div style=\"margin-top:8px;\">${data.description}</div>
            <div class=\"job-passive\">${data.passive}</div>
        `;
    }

    // 직업 버튼 active 토글
    document.querySelectorAll('.job-btn').forEach(btn => {
        if (btn.dataset.job === job) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}


// ─────────────────────────────────────────────
// 모달 2: 이메일 인증 (Mock — 실제 API 붙일 때 교체)
// ─────────────────────────────────────────────

// ── Step 2-1: 이메일 입력 후 코드 발송 ──
// 현재 mock: 이메일 형식만 검증 + 필수 동의 체크 + 코드 입력란 표시.
// 실제 API 연결 시: /api/email/send_code 호출 → 백엔드가 Gmail SMTP로 발송.
async function sendEmailCode() {
    const emailInput = document.getElementById('input-email');
    const email = emailInput.value.trim();

    // 이메일 형식 검증
    if (!email || !/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email)) {
        toast('올바른 이메일 형식을 입력해주세요.', 'warn');
        emailInput.focus();
        return;
    }

    // 필수 동의 체크
    const req1 = document.getElementById('consent-required-1').checked;
    const req2 = document.getElementById('consent-required-2').checked;
    if (!req1 || !req2) {
        toast('필수 동의 항목을 모두 체크해주세요.', 'warn');
        return;
    }

    // ── 백엔드 API 호출 자리 (현재 mock) ──
    // const r = await api('/email/send_code', { email });
    // if (!r.ok) { toast(r.error || '코드 발송 실패', 'error'); return; }

    // Mock: 0.5초 대기 후 코드 입력란 표시
    toast('인증 코드를 전송했습니다.');
    term(`email code sent to ${email}`, 'ok');
    await _sleep(500);

    // 코드 입력란 표시 + 이메일 입력란 비활성화
    document.getElementById('email-code-row').style.display = 'block';
    emailInput.disabled = true;
    emailInput.style.opacity = '0.6';

    // 버튼 전환: 완료 → 인증 완료
    document.getElementById('btn-email-send').style.display = 'none';
    document.getElementById('btn-email-verify').style.display = 'block';

    // 코드 입력란에 자동 포커스
    document.getElementById('input-email-code').focus();

    if (IS_DEV) {
    console.log('[MOCK] 인증 코드:', '123456');
    console.log('[MOCK] 실제 환경에서는 이메일로 발송됨');
    }
    /*
    // mock: 개발자 콘솔에 임시 코드 출력 (실제 발송 전 확인용)
    console.log('[MOCK] 인증 코드: 123456 (실제로는 이메일로 전송됨)');
    */
}


// ── Step 2-2: 코드 검증 ──
// 현재 mock: 아무 6자리 숫자 입력하면 통과.
// 실제 API 연결 시: /api/email/verify 호출.
async function verifyEmailCode() {
    const codeInput = document.getElementById('input-email-code');
    const code = codeInput.value.trim();

    if (!/^[0-9]{6}$/.test(code)) {
        toast('6자리 숫자 코드를 입력해주세요.', 'warn');
        codeInput.focus();
        return;
    }

    // ── 백엔드 API 호출 자리 (현재 mock) ──
    // const email = document.getElementById('input-email').value.trim();
    // const r = await api('/email/verify', { email, code });
    // if (!r.ok) {
    //     toast(r.error || '인증 실패', 'error');
    //     codeInput.value = '';
    //     codeInput.focus();
    //     return;
    // }

    // Mock: 무조건 성공
    const email = document.getElementById('input-email').value.trim();
    state.isEmailAuth = true;
    state.userEmail = email;
    toast('이메일 인증 완료!');
    term(`email verified: ${email}`, 'ok');

    // 직업 선택 모달로 이동
    showStartModal('modal-newgame');
    // 첫 진입 시 기본 직업(전사) 데이터로 미리보기 초기화
    selectJob(state.selectedJob || '전사');
}


// ── 모달 2의 BACK 버튼 — 1번 모달로 돌아가기 ──
function backToEntry() {
    // 입력값 초기화
    document.getElementById('input-email').value = '';
    document.getElementById('input-email').disabled = false;
    document.getElementById('input-email').style.opacity = '';
    document.getElementById('input-email-code').value = '';
    document.getElementById('email-code-row').style.display = 'none';
    document.getElementById('btn-email-send').style.display = 'block';
    document.getElementById('btn-email-verify').style.display = 'none';
    document.getElementById('consent-required-1').checked = false;
    document.getElementById('consent-required-2').checked = false;
    document.getElementById('consent-optional').checked = false;

    showStartModal('modal-entry');
}


// ── 헬퍼: sleep ──
// Actions.js에 이미 _sleep이 있으면 그쪽 사용. 없으면 여기서 정의.
if (typeof _sleep === 'undefined') {
    function _sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}