/* map/MapChapter.js — 챕터 클리어/전환 */

function _showChapterClear(result) {
    const isGameClear = result.game_clear;
    const nextCh      = result.next_chapter;
    const overlay = document.createElement("div");
    overlay.id = "chapter-clear-overlay";
    overlay.className = "chapter-clear-overlay";
    overlay.innerHTML = `
        <div class="chapter-clear-title">
            ${isGameClear ? "🎉 GAME CLEAR!" : `CHAPTER ${_mapState?.chapter || ""} CLEAR!`}
        </div>
        <div class="chapter-clear-sub">
            ${isGameClear ? "모든 챕터를 클리어했습니다!" : `챕터 ${nextCh}로 진행합니다.`}
        </div>
        <button class="btn chapter-clear-btn"
            onclick="${isGameClear ? "restartGame()" : `startNextChapter(${nextCh})`}">
            ${isGameClear ? "처음으로" : `챕터 ${nextCh} 시작 ▶`}
        </button>
    `;
    document.body.appendChild(overlay);
}

async function startNextChapter(chapter) {
    document.getElementById("chapter-clear-overlay")?.remove();
    try {
        const r = await api("/map/next_chapter", {});
        if (!r.ok) { toast(r.error || "챕터 전환 실패", "error"); return; }
        _mapState = r.map;
        setMapMode();
        renderMap(_mapState);
        logLine(`📍 챕터 ${chapter} 시작!`, "system");
        toast(`챕터 ${chapter} 시작!`, "ok");
    } catch (e) {
        console.error("[startNextChapter]", e);
    }
}