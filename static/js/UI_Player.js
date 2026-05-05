/* ═══════════════════════════════════════════════════════════
   ui-player.js — 좌측 PLAYER 패널 UI 갱신
   - refreshPlayer: state.player 기반 좌측 패널 전체 갱신
     (HP/MP/EXP 게이지, 능력치 표, 스킬북, 캐릭터 아이콘)
   - 스킬 아이콘 매핑
   ═══════════════════════════════════════════════════════════ */

function refreshPlayer() {
    if (!state.player) return;
    const p = state.player;
    document.getElementById('player-id').textContent = `${p.name} (LV ${p.lv} ${p.job})`;
    document.getElementById('player-icon').textContent = JOB_ICONS[p.job] || '?';

    // ── 좌측 게이지: HP/MP/EXP ──
    document.getElementById('hp-cur').textContent = Math.round(p.hp);
    document.getElementById('hp-max').textContent = p.maxhp;
    document.getElementById('mp-cur').textContent = Math.round(p.mp);
    document.getElementById('mp-max').textContent = p.maxmp;
    document.getElementById('hp-fill').style.height = (p.hp/p.maxhp*100) + '%';
    document.getElementById('mp-fill').style.height = (p.mp/p.maxmp*100) + '%';

    // EXP 게이지 (노란색)
    const expEl = document.getElementById('exp-fill');
    if (expEl) {
        const expRatio = p.maxexp > 0 ? (p.exp / p.maxexp * 100) : 0;
        expEl.style.height = expRatio + '%';
        document.getElementById('exp-cur').textContent = Math.round(p.exp || 0);
        document.getElementById('exp-max').textContent = p.maxexp || 0;
    }

    // ── 능력치 표 (좌측 패널) ──
    document.getElementById('stat-grid').innerHTML = `
        <div class="stat-row"><span>STG</span><span class="v">${p.stg}</span></div>
        <div class="stat-row"><span>SP</span><span class="v">${p.sp}</span></div>
        <div class="stat-row"><span>ARM</span><span class="v">${p.arm}</span></div>
        <div class="stat-row"><span>SPARM</span><span class="v">${p.sparm}</span></div>
        <div class="stat-row"><span>SPD</span><span class="v">${p.spd}</span></div>
        <div class="stat-row"><span>LUC</span><span class="v">${p.luc}</span></div>
    `;

    // ── 좌측 스킬북 제거됨 ──
    // 좌측 패널은 능력치까지만. 스킬 목록은 탐험 모드 SKILLS 카드에서 표시.

    // ── 탐험 모드 정보 카드 (인벤토리/스탯/스킬) ──
    refreshExploreInfo();
}

// 스킬 이름에 따른 아이콘 매핑
function skillIcon(sk) {
    if (sk.includes('파이어')) return '🔥';
    if (sk.includes('힐')) return '✚';
    if (sk.includes('실드')) return '⛨';
    if (sk.includes('강타')) return '⚒';
    if (sk.includes('연속')) return '⚔';
    if (sk.includes('찌르기')) return '⚡';
    if (sk.includes('아이스')) return '❄';
    if (sk.includes('라이트닝')) return '⚡';
    if (sk.includes('수비')) return '⛨';
    if (sk.includes('몸통')) return '◆';
    if (sk.includes('추진력')) return '➤';
    if (sk.includes('급소')) return '✦';
    return '★';
}