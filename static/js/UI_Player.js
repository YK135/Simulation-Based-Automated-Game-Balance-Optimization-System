/* ═══════════════════════════════════════════════════════════
   UI_Player.js — 좌측 플레이어 패널 갱신
   ═══════════════════════════════════════════════════════════ */

function refreshPlayer() {
    if (!state.player) return;
    const p = state.player;
    document.getElementById('player-id').textContent = `${p.name} (LV ${p.lv} ${p.job})`;

    const iconEl = document.getElementById('player-icon');
    if (iconEl) iconEl.textContent = JOB_ICONS[p.job] || '?';

    if (typeof setCharState === 'function') setCharState('player_panel', 'idle');

    // ── HP/MP/EXP 게이지 ──
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

    // ── 골드 표시 ──
    const goldEl = document.getElementById('player-gold');
    if (goldEl) goldEl.textContent = `${state.gold || 0} G`;

    // ── 버프/디버프 표시 ──
    refreshStatusChips(p);

    if (typeof refreshExploreInfo === 'function') refreshExploreInfo();
}

/** 버프/디버프 칩 렌더링 */
function refreshStatusChips(p) {
    const buffsEl   = document.getElementById('player-buffs');
    const debuffsEl = document.getElementById('player-debuffs');
    if (!buffsEl || !debuffsEl) return;

    // 전투 상태에서 buffs/debuffs 가져오기
    const bs = state.battleState || null;

    buffsEl.innerHTML   = '';
    debuffsEl.innerHTML = '';

    // 전투 중: BattleSession 상태에서 읽음
    if (bs && bs.player_buffs) {
        bs.player_buffs.forEach(buff => {
            const chip = _makeChip(buff.name || buff, buff.turns, 'buff');
            buffsEl.appendChild(chip);
        });
    }

    if (bs && bs.player_debuffs) {
        bs.player_debuffs.forEach(debuff => {
            const chip = _makeChip(debuff.name || debuff.stat || debuff, debuff.turns, 'debuff');
            debuffsEl.appendChild(chip);
        });
    }

    // 전투 외: player 객체에 status_effects가 있으면 표시
    if (!bs && p.status_effects) {
        p.status_effects.forEach(eff => {
            const type = eff.type === 'buff' ? 'buff' : 'debuff';
            const chip = _makeChip(eff.name || eff.stat, eff.turns, type);
            (type === 'buff' ? buffsEl : debuffsEl).appendChild(chip);
        });
    }
}

function _makeChip(label, turns, type) {
    const chip = document.createElement('span');
    chip.className = `status-chip ${type}`;
    const turnsText = turns ? `<span class="turns">${turns}T</span>` : '';
    chip.innerHTML = `${label}${turnsText}`;
    return chip;
}

// 스킬 아이콘 매핑
function skillIcon(sk) {
    if (sk.includes('파이어'))    return '🔥';
    if (sk.includes('힐'))        return '✚';
    if (sk.includes('실드'))      return '⛨';
    if (sk.includes('강타'))      return '⚒';
    if (sk.includes('연속'))      return '⚔';
    if (sk.includes('찌르기'))    return '⚡';
    if (sk.includes('아이스'))    return '❄';
    if (sk.includes('라이트닝'))  return '⚡';
    if (sk.includes('수비'))      return '⛨';
    if (sk.includes('몸통'))      return '◆';
    if (sk.includes('추진력'))    return '➤';
    if (sk.includes('급소'))      return '✦';
    if (sk.includes('홀리'))      return '✝';
    if (sk.includes('축복'))      return '★';
    if (sk.includes('셰이드'))    return '🌑';
    return '★';
}