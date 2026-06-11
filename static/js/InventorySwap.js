/* ═══════════════════════════════════════════════════════════
   InventorySwap.js — 특수 인벤토리 교체 모달
   ═══════════════════════════════════════════════════════════ */

let ivIncomingItem = null;
let ivSelectedDrop = null;
let ivCandidates   = [];

function openInvSwap(incoming, candidates) {
    ivIncomingItem = incoming;
    ivSelectedDrop = null;
    ivCandidates   = candidates || [];

    const el = document.getElementById('iv-incoming');
    if (el) el.textContent = (typeof itemLabel === 'function') ? itemLabel(incoming) : incoming;
    renderInvCandidates();

    const modal = document.getElementById('modal-inv-swap');
    if (modal) modal.classList.add('active');
}

function renderInvCandidates() {
    const list = document.getElementById('iv-candidates');
    if (!list) return;
    list.innerHTML = '';

    ivCandidates.forEach(name => {
        const row = document.createElement('div');
        row.className = 'iv-candidate' + (ivSelectedDrop === name ? ' selected' : '');
        const dispName = (typeof itemLabel === 'function') ? itemLabel(name) : name;
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
    if (btn) btn.disabled = !ivSelectedDrop;
}

async function confirmInvSwap() {
    if (!ivSelectedDrop || !ivIncomingItem) return;
    try {
        const r = await api('/inventory/swap_special', {
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
}

document.addEventListener('DOMContentLoaded', () => {
    const confirmBtn = document.getElementById('iv-confirm');
    const cancelBtn  = document.getElementById('iv-cancel');
    if (confirmBtn) confirmBtn.onclick = confirmInvSwap;
    if (cancelBtn)  cancelBtn.onclick  = cancelInvSwap;
});