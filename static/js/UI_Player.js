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

    // ── 골드 ──
    const goldEl = document.getElementById('player-gold');
    if (goldEl) goldEl.textContent = `${state.gold || 0} G`;

    // ── 아이템 패널 (노드 선택 필드 전용) ──
    refreshInventoryPanel(p);

    // ── 버프/디버프는 UI_Battle.js의 refreshPlayerStatusList가 전투 중 처리 ──
    if (typeof refreshExploreInfo === 'function') refreshExploreInfo();
}

/** 왼쪽 패널 아이템 렌더링 (포션 클릭 사용 가능, 특수 표시만) */
function refreshInventoryPanel(p) {
    const panel = document.getElementById('player-inventory-panel');

    // 전투 중에는 아이템 패널 숨김 (액션 메뉴에서 사용)
    if (state.inBattle) {
        if (panel) panel.style.display = 'none';
        return;
    }
    if (panel) panel.style.display = '';

    const potionEl  = document.getElementById('player-potion-list');
    const specialEl = document.getElementById('player-special-list');
    if (!potionEl && !specialEl) return;

    const inv     = (p && p.inventory) || {};
    const potions = inv.potions || [];
    const special = inv.special || [];

    // ── 포션 목록 ──
    if (potionEl) {
        potionEl.innerHTML = '';
        if (potions.length === 0) {
            potionEl.innerHTML = '<div class="pip-empty">포션 없음</div>';
        } else {
            potions.forEach(({ name, count }) => {
                const row = document.createElement('div');
                // 전투 중에는 클릭 비활성
                const usable = !state.inBattle;
                row.className = `pip-item${usable ? ' usable' : ''}`;
                row.innerHTML = `<span class="pip-item-name">${name}</span><span class="pip-item-count">×${count}</span>`;
                if (usable) {
                    row.onclick = () => usePotionFromPanel(name);
                    row.title = '클릭하여 사용';
                } else {
                    row.title = '전투 중에는 액션 메뉴에서 사용하세요';
                }
                potionEl.appendChild(row);
            });
        }
    }

    // ── 특수 아이템 (표시만, 클릭 비활성) ──
    if (specialEl) {
        specialEl.innerHTML = '';
        if (special.length === 0) {
            specialEl.innerHTML = '<div class="pip-empty">특수 없음</div>';
        } else {
            special.forEach(name => {
                const row = document.createElement('div');
                row.className = 'pip-item pip-special';
                row.innerHTML = `<span class="pip-item-name">${name}</span><span class="pip-item-badge">★</span>`;
                row.title = '필드에서 사용 불가';
                specialEl.appendChild(row);
            });
        }
    }
}

/** 필드에서 포션 사용 */
async function usePotionFromPanel(itemName) {
    if (state.inBattle) {
        toast('전투 중에는 액션 메뉴에서 사용하세요.', 'warn');
        return;
    }
    if (typeof useItemInField !== 'function') {
        console.warn('[usePotionFromPanel] useItemInField not found');
        return;
    }
    await useItemInField(itemName);
    // useItemInField 내부에서 state.player 갱신 + refreshPlayer() 호출됨
}

// 스킬 아이콘 매핑
function skillIcon(sk) {
    if (sk.includes('파이어'))   return '🔥';
    if (sk.includes('힐'))       return '✚';
    if (sk.includes('실드'))     return '⛨';
    if (sk.includes('강타'))     return '⚒';
    if (sk.includes('연속'))     return '⚔';
    if (sk.includes('찌르기'))   return '⚡';
    if (sk.includes('아이스'))   return '❄';
    if (sk.includes('라이트닝')) return '⚡';
    if (sk.includes('수비'))     return '⛨';
    if (sk.includes('몸통'))     return '◆';
    if (sk.includes('추진력'))   return '➤';
    if (sk.includes('급소'))     return '✦';
    if (sk.includes('홀리'))     return '✝';
    if (sk.includes('축복'))     return '★';
    if (sk.includes('셰이드'))   return '🌑';
    return '★';
}