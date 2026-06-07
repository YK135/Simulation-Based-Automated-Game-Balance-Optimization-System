/* map/MapRest.js — 휴식/수련 패널 */

function _showRestPanel(r) {
    const overlay = document.getElementById("map-content-overlay");
    if (!overlay) return;
    overlay.style.display = "flex";
    overlay.innerHTML = `
        <div class="rest-panel">
            <div class="rest-title">🏕 REST SITE</div>
            <p class="event-message">${r.message || "휴식 지점에 도착했다."}</p>
            <div class="rest-options">
                ${(r.options || []).map(opt => `
                    <button class="rest-option-btn" onclick="chooseRestOption('${opt.key}')">
                        ${opt.label}
                    </button>
                `).join("")}
            </div>
        </div>
    `;
}

async function chooseRestOption(choice) {
    try {
        const r = await api("/rest", { choice });
        if (!r.ok) { toast(r.error || "실패", "error"); return; }
        if (r.player) {
            state.player = r.player;
            if (typeof refreshPlayer === "function") refreshPlayer();
        }
        logLine(r.message || "휴식 완료", "heal");
        toast(r.message, "ok");
        if (typeof checkPendingPoints === "function") checkPendingPoints();
        await _completeNode(_pendingNodeId);
        _hideOverlay();
    } catch (e) {
        console.error("[chooseRestOption]", e);
    }
}