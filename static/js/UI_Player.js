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

// ═══════════════════════════════════════════════════════════
// 인벤토리 팝업(#modal-item-inventory) — view / overflow 공용
// ───────────────────────────────────────────────────────────
// view    : 보유 아이템 확인 + 필드 포션 사용 (기존 동작)
// overflow: 가방이 꽉 차서 새 아이템을 못 받을 때, 버릴 아이템을 선택해
//           교체를 확정하는 화면 — 예전엔 별도의 세로 목록형 #modal-inv-swap
//           (InventorySwap.js)이 담당했는데, 같은 이름의 아이템이 여러 개면
//           한 행만 클릭해도 동일 이름의 다른 행들까지 전부 "선택됨"으로
//           표시되는 버그가 있어(이름 문자열 하나로 선택 상태를 저장했기
//           때문) 제거하고 이 그리드로 통합했다. 클릭할 때마다 그 아이템의
//           선택 수량이 0→1→2→...→보유수량→0으로 순환한다.
// ═══════════════════════════════════════════════════════════

let _iiMode = 'view';            // 'view' | 'overflow'
let _iiOverflow = null;          // {ticketId, incomingItem, candidates, selected: Map(name->count)}
let _iiResolvePending = null;    // openInvSwap()이 반환한 Promise의 resolve

/** 아이템 팝업 내용 렌더링 — 용량 표기 + n×2 그리드.
 *  view: 포션 클릭 시 필드에서 즉시 사용. special은 표시만.
 *  overflow: candidates에 속한(= 대기 중인 새 아이템과 같은 슬롯의) 셀만
 *  클릭 가능, 클릭마다 선택 수량이 순환한다. */
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

    const isOverflow = _iiMode === 'overflow' && _iiOverflow;
    const candidateSet = isOverflow ? new Set(_iiOverflow.candidates) : null;

    const makeCell = (name, { count, isSpecial, usable } = {}) => {
        const cell = document.createElement('div');
        const selectable = isOverflow && candidateSet.has(name);
        const selectedCount = isOverflow ? (_iiOverflow.selected.get(name) || 0) : 0;
        cell.className = `ii-item${isSpecial ? ' ii-special' : ''}` +
            `${usable ? ' usable' : ''}${selectable ? ' selectable' : ''}${selectedCount > 0 ? ' selected' : ''}`;
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

        if (isOverflow) {
            const countSp = document.createElement('span');
            countSp.className = 'ii-item-count';
            countSp.textContent = `×${count}`;
            cell.appendChild(countSp);
            if (selectable) {
                if (selectedCount > 0) {
                    const badge = document.createElement('span');
                    badge.className = 'ii-selected-badge';
                    badge.textContent = `선택 ×${selectedCount}`;
                    cell.appendChild(badge);
                }
                cell.onclick = () => _iiCycleSelect(name, count);
                cell.title = `클릭할 때마다 버릴 개수가 늘어납니다 (보유 ${count}개, 현재 ×${selectedCount})`;
            } else {
                cell.title = '새로 받을 아이템과 종류가 달라 버릴 수 없습니다.';
            }
            return cell;
        }

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
        const usable = !isOverflow && !state.inBattle && !(state.player && state.player.hp <= 0);
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
            // ★ overflow 모드에선 special도 후보(candidateSet)일 수 있으므로 개수를
            //   세어서 넘긴다 — view 모드에선 원래처럼 배지(★)만 표시.
            const specCounts = {};
            special.forEach(name => { specCounts[name] = (specCounts[name] || 0) + 1; });
            Object.keys(specCounts).forEach(name =>
                specGrid.appendChild(makeCell(name, { isSpecial: true, count: specCounts[name] })));
        }
    }

    if (isOverflow) _updateOverflowConfirmState();
}

function _iiOverflowTotalSelected() {
    if (!_iiOverflow) return 0;
    let total = 0;
    _iiOverflow.selected.forEach(v => { total += v; });
    return total;
}

function _updateOverflowConfirmState() {
    const btn = document.getElementById('ii-confirm');
    if (btn) btn.disabled = _iiOverflowTotalSelected() < 1;
    const desc = document.getElementById('ii-desc');
    if (desc && _iiOverflow) {
        const n = _iiOverflowTotalSelected();
        desc.innerHTML = `새 아이템 <span class="iv-incoming">${(typeof itemLabel === 'function') ? itemLabel(_iiOverflow.incomingItem) : _iiOverflow.incomingItem}</span>` +
            `을(를) 얻으려면 버릴 아이템을 선택하세요.` +
            (n > 0 ? `<br><b>${n}개 선택됨</b>` : '');
    }
}

/** 클릭할 때마다 0→1→2→...→owned→0으로 선택 수량 순환. */
function _iiCycleSelect(name, owned) {
    if (!_iiOverflow) return;
    const cur = _iiOverflow.selected.get(name) || 0;
    const next = cur >= owned ? 0 : cur + 1;
    if (next === 0) _iiOverflow.selected.delete(name);
    else _iiOverflow.selected.set(name, next);
    refreshItemModal(state.player);
}

function openItemModal() {
    _iiMode = 'view';
    _iiOverflow = null;
    document.getElementById('ii-title').textContent = '📦 INVENTORY';
    document.getElementById('ii-desc').style.display = 'none';
    document.getElementById('btn-close-items').style.display = '';
    document.getElementById('ii-overflow-footer').style.display = 'none';
    refreshItemModal(state.player);
    document.getElementById('modal-item-inventory')?.classList.add('active');
}

function closeItemModal() {
    document.getElementById('modal-item-inventory')?.classList.remove('active');
}

/** overflow 모드로 인벤토리 팝업을 연다 — 예전 InventorySwap.js의 openInvSwap()
 *  을 대체. 모달이 닫힐 때(확인 또는 취소) resolve되는 Promise를 반환한다.
 *  기존 호출부(상점/이벤트처럼 반환값을 안 쓰는 곳)는 그냥 무시하면 되므로
 *  하위 호환 — 전투 보상 흐름만 await openInvSwap(...)로 순서를 맞춘다. */
function openInvSwap(incomingItem, candidates, ticketId) {
    _iiMode = 'overflow';
    _iiOverflow = { ticketId, incomingItem, candidates: candidates || [], selected: new Map() };

    document.getElementById('ii-title').textContent = '⚠ 가방 가득 — 교체 선택';
    const desc = document.getElementById('ii-desc');
    if (desc) desc.style.display = '';
    document.getElementById('btn-close-items').style.display = 'none';
    document.getElementById('ii-overflow-footer').style.display = 'flex';

    refreshItemModal(state.player);
    document.getElementById('modal-item-inventory')?.classList.add('active');

    return new Promise(resolve => { _iiResolvePending = resolve; });
}

function _closeInvSwap() {
    document.getElementById('modal-item-inventory')?.classList.remove('active');
    _iiMode = 'view';
    _iiOverflow = null;
    if (_iiResolvePending) {
        const resolve = _iiResolvePending;
        _iiResolvePending = null;
        resolve();
    }
}

let _iiSwapProcessing = false;   // 연속 클릭 방지

async function _confirmInvSwap() {
    if (_iiSwapProcessing || !_iiOverflow) return;
    if (_iiOverflowTotalSelected() < 1) return;
    _iiSwapProcessing = true;
    const btn = document.getElementById('ii-confirm');
    if (btn) btn.disabled = true;
    try {
        const drops = Object.fromEntries(_iiOverflow.selected);
        const r = await api('/inventory/swap', { ticket_id: _iiOverflow.ticketId, drops });
        if (!r.ok) { toast(r.error || '교체 실패', 'error'); return; }
        state.player = r.player;
        // ★ 상점 구매가 가득 찬 인벤토리 때문에 미뤄졌던 경우, 결제는 이
        //   스왑 확정 시점에 서버에서 이뤄진다(app/Inventory.py 참고) — 응답에
        //   gold가 실려오면 화면 골드도 같이 갱신해야 실제 차감이 반영된다.
        if (r.gold !== undefined) state.gold = r.gold;
        if (typeof refreshPlayer === 'function') refreshPlayer();
        toast(r.message || '교체 완료', 'ok');
        _closeInvSwap();
    } catch (e) {
        console.error('[_confirmInvSwap]', e);
        toast('네트워크 오류', 'error');
    } finally {
        _iiSwapProcessing = false;
        if (btn) btn.disabled = _iiOverflowTotalSelected() < 1;
    }
}

async function _cancelInvSwap() {
    if (_iiOverflow) {
        const label = (typeof itemLabel === 'function') ? itemLabel(_iiOverflow.incomingItem) : _iiOverflow.incomingItem;
        try { await api('/inventory/swap/cancel', { ticket_id: _iiOverflow.ticketId }); }
        catch (e) { console.error('[_cancelInvSwap]', e); }
        toast(`${label} 획득 포기`, 'info');
    }
    _closeInvSwap();
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-open-items')?.addEventListener('click', openItemModal);
    document.getElementById('btn-close-items')?.addEventListener('click', closeItemModal);
    document.getElementById('ii-confirm')?.addEventListener('click', _confirmInvSwap);
    document.getElementById('ii-cancel')?.addEventListener('click', _cancelInvSwap);
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
