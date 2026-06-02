/* ═══════════════════════════════════════════════════════════
   UI_Player.js — 좌측 플레이어 패널 갱신
   ═══════════════════════════════════════════════════════════ */

const JOB_ICONS = {
    '전사': '⚔', '마법사': '✦', '탱커': '⛨', '도적': '🗡'
};

function refreshPlayer() {
    if (!state.player) return;
    const p = state.player;
    document.getElementById('player-id').textContent = `${p.name} (LV ${p.lv} ${p.job})`;

    // ── 이모지 폴백 동기화 ──
    const iconEl = document.getElementById('player-icon');
    if (iconEl) iconEl.textContent = JOB_ICONS[p.job] || '?';

    // ── 좌측 패널 얼굴 이미지 ──
    if (typeof setCharState === 'function') {
        setCharState('player_panel', 'idle');
    }

    // ── 좌측 게이지 HP/MP/EXP ──
    document.getElementById('hp-cur').textContent = Math.round(p.hp);
    document.getElementById('hp-max').textContent = p.maxhp;
    document.getElementById('mp-cur').textContent = Math.round(p.mp);
    document.getElementById('mp-max').textContent = p.maxmp;
    document.getElementById('hp-fill').style.height = (p.hp / p.maxhp * 100) + '%';
    document.getElementById('mp-fill').style.height = (p.mp / p.maxmp * 100) + '%';

    const expEl = document.getElementById('exp-fill');
    if (expEl) {
        const expRatio = p.maxexp > 0 ? (p.exp / p.maxexp * 100) : 0;
        expEl.style.height = expRatio + '%';
        document.getElementById('exp-cur').textContent = Math.round(p.exp || 0);
        document.getElementById('exp-max').textContent = p.maxexp || 0;
    }

    // ── 능력치 표 ──
    document.getElementById('stat-grid').innerHTML = `
        <div class="stat-row"><span>STG</span><span class="v">${p.stg}</span></div>
        <div class="stat-row"><span>SP</span><span class="v">${p.sp}</span></div>
        <div class="stat-row"><span>ARM</span><span class="v">${p.arm}</span></div>
        <div class="stat-row"><span>SPARM</span><span class="v">${p.sparm}</span></div>
        <div class="stat-row"><span>SPD</span><span class="v">${p.spd}</span></div>
        <div class="stat-row"><span>LUC</span><span class="v">${p.luc}</span></div>
    `;

    // ── 탐험 모드 정보 카드 (UI_Explore.js 로드된 경우에만 호출) ──
    if (typeof refreshExploreInfo === 'function') {
        refreshExploreInfo();
    }
}


// 스킬 이름에 따른 아이콘 매핑
function skillIcon(sk) {
    if (sk.includes('파이어')) return '🔥';
    if (sk.includes('힐'))    return '✚';
    if (sk.includes('실드'))  return '⛨';
    if (sk.includes('강타'))  return '⚒';
    if (sk.includes('연속'))  return '⚔';
    if (sk.includes('찌르기')) return '⚡';
    if (sk.includes('아이스')) return '❄';
    if (sk.includes('라이트닝')) return '⚡';
    if (sk.includes('수비'))  return '⛨';
    if (sk.includes('몸통'))  return '◆';
    if (sk.includes('추진력')) return '➤';
    if (sk.includes('급소'))  return '✦';
    if (sk.includes('홀리'))  return '✝';
    if (sk.includes('축복'))  return '★';
    if (sk.includes('셰이드')) return '🌑';
    return '★';
}