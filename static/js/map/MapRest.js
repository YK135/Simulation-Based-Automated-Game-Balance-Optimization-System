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
                    <button class="rest-option-btn" data-choice="${opt.key}">
                        ${opt.label}
                    </button>
                `).join("")}
            </div>
        </div>
    `;

    // 이벤트 바인딩 (인라인 onclick 대체)
    overlay.querySelectorAll(".rest-option-btn[data-choice]").forEach(btn => {
        btn.addEventListener("click", () => chooseRestOption(btn.dataset.choice));
    });
}

// ★ 연속 클릭 방지 — 예전엔 가드가 전혀 없어서 "수련"을 빠르게 여러 번
//   누르면 응답이 오기 전에 요청이 중복 발사돼 경험치가 여러 번 지급됐음
//   (실측: 클릭 1번에 5초 새 경험치 로그 7개). battleAction()의
//   state.battleProcessing 패턴을 그대로 적용.
let _restProcessing = false;

async function chooseRestOption(choice) {
    if (_restProcessing) return;
    _restProcessing = true;
    const buttons = document.querySelectorAll(".rest-option-btn");
    buttons.forEach(b => b.disabled = true);
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
    } finally {
        _restProcessing = false;
        buttons.forEach(b => b.disabled = false);   // 성공 시엔 오버레이가 이미 사라짐 — 무해
    }
}