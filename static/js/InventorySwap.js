/* ═══════════════════════════════════════════════════════════
   InventorySwap.js — 인벤토리 교체 모달 (포션 + 특수 공용)
   ═══════════════════════════════════════════════════════════ */

let ivIncomingItem  = null;
let ivSelectedDrop  = null;
let ivCandidates    = [];
let ivResolvePending = null;   // openInvSwap()이 반환한 Promise의 resolve —
                                // 전투 보상 흐름이 "이 모달이 닫힐 때까지" 기다릴 때 사용
let _ivSwapProcessing = false; // 연속 클릭 방지

/** 모달을 열고, 닫힐 때(확인 또는 취소) resolve되는 Promise를 반환한다.
 *  상점/이벤트처럼 반환값을 안 쓰는 기존 호출부는 그냥 무시하면 되므로
 *  하위 호환 — 전투 보상 흐름만 `await openInvSwap(...)`로 순서를 맞춘다. */
function openInvSwap(incoming, candidates) {
    ivIncomingItem = incoming;
    ivSelectedDrop = null;
    ivCandidates   = candidates || [];

    const el = document.getElementById('iv-incoming');
    if (el) {
        el.textContent = (typeof itemLabel === 'function') ? itemLabel(incoming) : incoming;
        el.dataset.tooltipItem = incoming;   // 획득 아이템에도 hover 설명
    }
    renderInvCandidates();

    const modal = document.getElementById('modal-inv-swap');
    if (modal) modal.classList.add('active');

    return new Promise(resolve => { ivResolvePending = resolve; });
}

function renderInvCandidates() {
    const list = document.getElementById('iv-candidates');
    if (!list) return;
    list.innerHTML = '';

    ivCandidates.forEach(name => {
        const row = document.createElement('div');
        row.className = 'iv-candidate' + (ivSelectedDrop === name ? ' selected' : '');
        const dispName = (typeof itemLabel === 'function') ? itemLabel(name) : name;
        row.dataset.tooltipItem = name;
        if (typeof itemDesc === 'function' && itemDesc(name)) row.title = itemDesc(name);
        row.innerHTML = `
            <span class="iv-cand-name">${dispName}</span>
            <span class="iv-cand-mark">✕ 버림</span>
        `;
        row.onclick = () => {
            ivSelectedDrop = name;
            renderInvCandidates();
            updateConfirmButton();
        };
        list.appendChild(row);
    });
}

function updateConfirmButton() {
    const btn = document.getElementById('iv-confirm');
    if (btn) btn.disabled = !ivSelectedDrop || _ivSwapProcessing;
}

async function confirmInvSwap() {
    if (_ivSwapProcessing) return;   // ★ 연속 클릭 방지 — 응답 오기 전 재클릭 차단
    if (!ivSelectedDrop || !ivIncomingItem) return;
    _ivSwapProcessing = true;
    updateConfirmButton();
    try {
        const r = await api('/inventory/swap', {
            drop: ivSelectedDrop,
            new:  ivIncomingItem,
        });
        if (!r.ok) { toast(r.error || '교체 실패', 'error'); return; }
        state.player = r.player;
        if (typeof refreshPlayer === 'function') refreshPlayer();
        toast(r.message || '교체 완료', 'ok');
        closeInvSwap();
    } catch (e) {
        console.error('[confirmInvSwap]', e);
        toast('네트워크 오류', 'error');
    } finally {
        _ivSwapProcessing = false;
        updateConfirmButton();
    }
}

function cancelInvSwap() {
    toast(`${(typeof itemLabel === 'function') ? itemLabel(ivIncomingItem) : ivIncomingItem} 획득 포기`, 'info');
    closeInvSwap();
}

function closeInvSwap() {
    const modal = document.getElementById('modal-inv-swap');
    if (modal) modal.classList.remove('active');
    ivIncomingItem = null;
    ivSelectedDrop = null;
    if (ivResolvePending) {
        const resolve = ivResolvePending;
        ivResolvePending = null;
        resolve();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const confirmBtn = document.getElementById('iv-confirm');
    const cancelBtn  = document.getElementById('iv-cancel');
    if (confirmBtn) confirmBtn.onclick = confirmInvSwap;
    if (cancelBtn)  cancelBtn.onclick  = cancelInvSwap;
});
