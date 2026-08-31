/* map/MapEvents.js — 이벤트 노드 패널 */

function _showEventResult(r) {
    if (r.event === "item_full" || r.reason === "special_full") {
        if (typeof openInvSwap === "function") {
            openInvSwap(r.incoming || r.item, r.candidates || []);
        } else {
            toast("특수 아이템 칸이 가득 찼습니다.", "warn");
        }
        return;
    }
    const overlay = document.getElementById("map-content-overlay");
    if (!overlay) return;
    const icon = r.item ? "📦" : "✨";
    overlay.style.display = "flex";
    overlay.innerHTML = `
        <div class="event-result-panel">
            <div class="event-icon">${icon}</div>
            <div class="event-message">${r.message || "이벤트 발생!"}</div>
            ${r.item ? `<div class="event-item-gained">${r.item} 획득!</div>` : ""}
            <button class="btn event-continue-btn" id="event-continue-btn">계속하기</button>
        </div>
    `;
    overlay.querySelector("#event-continue-btn")
        ?.addEventListener("click", closeEventPanel);
    if (typeof logAdventure === "function") {
        logAdventure(r.message || "무언가를 발견했다.", r.item ? "loot" : "system");
    }
    if (r.player) {
        state.player = r.player;
        if (typeof refreshPlayer === "function") refreshPlayer();
    }
}

async function closeEventPanel() {
    _hideOverlay();
    await _reloadMapState();
}