/* ═══════════════════════════════════════════════════════════
   UI_Map.js — 슬레이 더 스파이어 스타일 노드맵 UI
   ───────────────────────────────────────────────────────────
   구조:
     - 좌/우 2열 레이아웃 (left branch | right branch)
     - 계층 1~14 일반 노드, 계층 15 보스 노드
     - 선택된 branch 이후 반대편 비활성화
     - 방문 경로 하이라이트 (on_path)
     - 노드 간 SVG 연결선

   전역 함수:
     initMap(chapter)         — 챕터 맵 생성 + 표시
     refreshMap(mapState)     — 맵 상태 갱신
     setMapMode()             — 맵 화면으로 전환
     hideMapMode()            — 맵 화면 숨기기
     handleNodeResult(r)      — choose API 응답 처리
     handleMapNodeDone(r)     — 노드 완료 후 맵 복귀
   ═══════════════════════════════════════════════════════════ */
const NODE_META = {
    start:  { icon: "🧭", label: "START",  color: "#8aa0b0", img: "/img/icons/nodes/start.png" },
    battle: { icon: "⚔",  label: "BATTLE", color: "#ff5050", img: "/img/icons/nodes/battle.png" },
    elite:  { icon: "💀", label: "ELITE",  color: "#ff9632", img: "/img/icons/nodes/elite.png" },
    rest:   { icon: "🏕", label: "REST",   color: "#50dc78", img: "/img/icons/nodes/rest.png" },
    shop:   { icon: "🛒", label: "SHOP",   color: "#ffd23c", img: "/img/icons/nodes/shop.png" },
    event:  { icon: "❓", label: "EVENT",  color: "#a064ff", img: "/img/icons/nodes/event.png" },
    boss:   { icon: "💠", label: "BOSS",   color: "#ff2828", img: "img/icons/nodes/boss.png" },
};

// ─────────────────────────────────────────────
// 상태
// ─────────────────────────────────────────────
let _mapState      = null;
let _pendingNodeId = null;

// ═══════════════════════════════════════════════════════════
// 진입점
// ═══════════════════════════════════════════════════════════

async function initMap(chapter = 1) {
    try {
        const r = await api("/map/generate", { chapter });
        if (!r.ok) { toast(r.error || "맵 생성 실패", "error"); return; }
        _mapState = r.map;
        setMapMode();
        renderMap(_mapState);
        logLine(`📍 챕터 ${chapter} 시작! 경로를 선택하세요.`, "system");
        toast(`챕터 ${chapter} 시작!`, "ok");
    } catch (e) {
        console.error("[initMap]", e);
        toast("맵 생성 실패", "error");
    }
}

function refreshMap(mapState) {
    _mapState = mapState;
    renderMap(_mapState);
    // 스크롤 + 연결선은 renderMap 내부 _redrawMapLater에서 처리
}

function _redrawMapLater(scroll, nodes, availSet) {
    setTimeout(() => {
        scrollToAvailableNode();
        requestAnimationFrame(() => {
            _drawConnections(scroll, nodes, availSet);
        });
    }, 80);
    // 폰트/이미지 로딩 후 한 번 더 재계산
    setTimeout(() => {
        _drawConnections(scroll, nodes, availSet);
    }, 280);
}

function scrollToAvailableNode() {
    const el = document.querySelector(".map-node.available");
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
}

// ═══════════════════════════════════════════════════════════
// 모드 전환
// ═══════════════════════════════════════════════════════════

function setMapMode() {
    ["battle-mode", "actions-panel"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = "none";
    });
    const mapEl = document.getElementById("map-mode");
    if (mapEl) mapEl.style.display = "flex";
}

function hideMapMode() {
    const mapEl = document.getElementById("map-mode");
    if (mapEl) mapEl.style.display = "none";
}

function _hideOverlay() {
    const el = document.getElementById("map-content-overlay");
    if (el) { el.style.display = "none"; el.innerHTML = ""; }
}