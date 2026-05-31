// 3-C. 신규 파일 static/js/InventorySwap.js
// ═══════════════════════════════════════════════════════════
// InventorySwap.js — 특수 인벤토리 교체 모달
// ═══════════════════════════════════════════════════════════

let ivIncomingItem = null;
let ivSelectedDrop = null;
let ivCandidates = [];

/**
 * 모달 열기
 * @param {string} incoming - 새 아이템 이름
 * @param {string[]} candidates - 버릴 후보 (기존 특수 아이템 3개)
 */
function openInvSwap(incoming, candidates) {
    ivIncomingItem = incoming;
    ivSelectedDrop = null;
    ivCandidates = candidates || [];

    document.getElementById('iv-incoming').textContent = incoming;
    renderInvCandidates();

    const modal = document.getElementById('modal-inv-swap');
    if (modal) modal.classList.add('active');
}

/** 후보 리스트 렌더 */
function renderInvCandidates() {
    const list = document.getElementById('iv-candidates');
    if (!list) return;
    list.innerHTML = '';

    ivCandidates.forEach(name => {
        const row = document.createElement('div');
        row.className = 'iv-candidate' + (ivSelectedDrop === name ? ' selected' : '');
        row.innerHTML = `
            <span class="iv-cand-name">${name}</span>
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

/** 교체 확정 */
async function confirmInvSwap() {
    if (!ivSelectedDrop || !ivIncomingItem) return;

    try {
        const r = await api('/inventory/swap_special', {
            drop: ivSelectedDrop,
            new:  ivIncomingItem,
        });
        if (!r.ok) {
            toast(r.error || '교체 실패', 'error');
            return;
        }

        state.player = r.player;
        if (typeof refreshPlayer === 'function') refreshPlayer();
        if (typeof refreshExploreInfo === 'function') refreshExploreInfo();

        toast(r.message || `교체 완료`, 'ok');
        closeInvSwap();
    } catch (e) {
        console.error('[confirmInvSwap]', e);
        toast('네트워크 오류', 'error');
    }
}

/** 취소 (새 아이템 포기) */
function cancelInvSwap() {
    toast(`${ivIncomingItem} 획득 포기`, 'info');
    closeInvSwap();
}

function closeInvSwap() {
    const modal = document.getElementById('modal-inv-swap');
    if (modal) modal.classList.remove('active');
    ivIncomingItem = null;
    ivSelectedDrop = null;
}

// 이벤트 바인딩
document.addEventListener('DOMContentLoaded', () => {
    const confirmBtn = document.getElementById('iv-confirm');
    const cancelBtn = document.getElementById('iv-cancel');
    if (confirmBtn) confirmBtn.onclick = confirmInvSwap;
    if (cancelBtn) cancelBtn.onclick = cancelInvSwap;
});
`;

// 3-D. 탐험 응답 처리 (UI_Explore.js 또는 어디든 explore 응답 받는 곳)
const EXPLORE_RESPONSE_HOOK = `
// /api/explore 응답 처리 — event === 'item_full' 시 모달
if (r.event === 'item_full') {
    if (typeof openInvSwap === 'function') {
        openInvSwap(r.incoming, r.candidates);
    }
    // 메시지는 별도 표시
} else if (r.event === 'item_rejected') {
    toast(r.message, 'warning');
}