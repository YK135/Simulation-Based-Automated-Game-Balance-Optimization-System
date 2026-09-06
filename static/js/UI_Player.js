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

    // ── 마스터 모드 패널 (전투 중 버튼 비활성화 동기화) ──
    if (typeof refreshMasterPanel === 'function') refreshMasterPanel();

    // ── 버프/디버프는 UI_Battle.js의 refreshPlayerStatusList가 전투 중 처리 ──
}

/** 좌측 패널 "ITEMS" 버튼 표시 여부 + (팝업이 열려 있으면) 내용 갱신.
 *  실제 목록/용량 렌더링은 refreshItemModal()로 옮김 — 예전엔 좁은 인라인
 *  목록이 스크롤돼야 할 정도로 비좁다는 피드백이 있어서, 클릭해서 여는
 *  팝업(#modal-item-inventory)으로 옮기고 여긴 버튼 진입점만 남김. */
function refreshInventoryPanel(p) {
    const btn = document.getElementById('btn-open-items');
    // 전투 중엔 액션 메뉴에서 아이템을 쓰므로 진입 버튼 자체를 숨김(기존 동작 유지)
    if (btn) btn.style.display = state.inBattle ? 'none' : '';

    const modal = document.getElementById('modal-item-inventory');
    if (modal && modal.classList.contains('active')) refreshItemModal(p);
}

/** 아이템 팝업(#modal-item-inventory) 내용 렌더링 — 용량 표기 + n×2 그리드.
 *  포션은 클릭 시 필드에서 즉시 사용(기존 인라인 목록의 usePotionFromPanel
 *  그대로 재사용), 특수는 표시만(전투 중에만 사용 가능). */
function refreshItemModal(p) {
    const inv     = (p && p.inventory) || {};
    const potions = inv.potions || [];
    const special = inv.special || [];

    const potCapEl = document.getElementById('ii-potion-capacity');
    if (potCapEl) {
        const used = inv.potion_used ?? potions.reduce((sum, x) => sum + x.count, 0);
        potCapEl.textContent = `${used}/${inv.potion_capacity ?? 6}`;
    }
    const specCapEl = document.getElementById('ii-special-capacity');
    if (specCapEl) {
        specCapEl.textContent = `${inv.special_used ?? special.length}/${inv.special_capacity ?? 3}`;
    }

    const makeCell = (name, { count, isSpecial, usable } = {}) => {
        const cell = document.createElement('div');
        cell.className = `ii-item${isSpecial ? ' ii-special' : ''}${usable ? ' usable' : ''}`;
        cell.dataset.tooltipItem = name;
        if (typeof renderIconWithFallback === 'function') {
            cell.appendChild(renderIconWithFallback(
                (typeof ITEM_ICONS !== 'undefined' ? ITEM_ICONS[name] : null) || { icon: '□' },
                'item-icon'));
        }
        const nameSp = document.createElement('span');
        nameSp.className = 'ii-item-name';
        nameSp.textContent = name;
        cell.appendChild(nameSp);
        if (isSpecial) {
            const badge = document.createElement('span');
            badge.className = 'ii-item-badge';
            badge.textContent = '★';
            cell.appendChild(badge);
            cell.title = ((typeof itemDesc === 'function' && itemDesc(name)) ? itemDesc(name) + ' — ' : '') + '필드에서 사용 불가 (전투 중 사용)';
        } else {
            const countSp = document.createElement('span');
            countSp.className = 'ii-item-count';
            countSp.textContent = `×${count}`;
            cell.appendChild(countSp);
            if (usable) {
                cell.onclick = () => usePotionFromPanel(name);
                cell.title = ((typeof itemDesc === 'function' && itemDesc(name)) ? itemDesc(name) + ' — ' : '') + '클릭하여 사용';
            } else {
                cell.title = ((typeof itemDesc === 'function' && itemDesc(name)) ? itemDesc(name) + ' — ' : '') + '전투 중에는 액션 메뉴에서 사용하세요';
            }
        }
        return cell;
    };

    const potGrid = document.getElementById('ii-potion-grid');
    if (potGrid) {
        potGrid.innerHTML = '';
        const usable = !state.inBattle && !(state.player && state.player.hp <= 0);
        if (potions.length === 0) {
            potGrid.innerHTML = '<div class="ii-empty">포션 없음</div>';
        } else {
            potions.forEach(({ name, count }) => potGrid.appendChild(makeCell(name, { count, usable })));
        }
    }

    const specGrid = document.getElementById('ii-special-grid');
    if (specGrid) {
        specGrid.innerHTML = '';
        if (special.length === 0) {
            specGrid.innerHTML = '<div class="ii-empty">특수 없음</div>';
        } else {
            special.forEach(name => specGrid.appendChild(makeCell(name, { isSpecial: true })));
        }
    }
}

function openItemModal() {
    refreshItemModal(state.player);
    document.getElementById('modal-item-inventory')?.classList.add('active');
}

function closeItemModal() {
    document.getElementById('modal-item-inventory')?.classList.remove('active');
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-open-items')?.addEventListener('click', openItemModal);
    document.getElementById('btn-close-items')?.addEventListener('click', closeItemModal);
});

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
