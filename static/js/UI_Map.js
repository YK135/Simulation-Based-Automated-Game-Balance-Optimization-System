/* ═══════════════════════════════════════════════════════════
   UI_Map.js — 노드맵 UI
   ───────────────────────────────────────────────────────────
   전역 함수:
     initMap(chapter)        — 챕터 맵 생성 + 표시
     refreshMap(mapState)    — 맵 상태 갱신 (노드 available 반영)
     setMapMode()            — 맵 화면으로 전환
     handleNodeResult(r)     — choose API 응답 처리
     handleMapNodeDone()     — 노드 완료 후 맵 갱신

   노드 아이콘:
     battle ⚔  elite 💀  rest 🏕  shop 🛒  event ❓  boss 💠
   ═══════════════════════════════════════════════════════════ */

// ─── 노드 타입 메타 ───────────────────────────────────────
const NODE_META = {
    battle: { icon: "⚔",  label: "BATTLE",  color: "#ff5050" },
    elite:  { icon: "💀", label: "ELITE",   color: "#ff9632" },
    rest:   { icon: "🏕", label: "REST",    color: "#50dc78" },
    shop:   { icon: "🛒", label: "SHOP",    color: "#ffd23c" },
    event:  { icon: "❓", label: "EVENT",   color: "#a064ff" },
    boss:   { icon: "💠", label: "BOSS",    color: "#ff2828" },
};

// ─── 현재 맵 상태 캐시 ────────────────────────────────────
let _mapState = null;
let _pendingNodeId = null;   // 휴식/상점 완료 대기 중인 node_id

// ═══════════════════════════════════════════════════════════
// 진입점
// ═══════════════════════════════════════════════════════════

/** 챕터 맵 생성 요청 */
async function initMap(chapter = 1) {
    try {
        const r = await api("/map/generate", { chapter });
        if (!r.ok) { toast(r.error || "맵 생성 실패", "error"); return; }
        _mapState = r.map;
        setMapMode();
        renderMap(_mapState);
        logLine(`📍 챕터 ${chapter} 시작! 노드를 선택하세요.`, "system");
        toast(`챕터 ${chapter} 시작!`, "ok");
    } catch (e) {
        console.error("[initMap]", e);
        toast("맵 생성 실패", "error");
    }
}

/** 맵 상태만 갱신 (노드 완료 후 etc.) */
function refreshMap(mapState) {
    _mapState = mapState;
    renderMap(_mapState);
}

// ═══════════════════════════════════════════════════════════
// 모드 전환
// ═══════════════════════════════════════════════════════════

/** 맵 화면으로 전환 */
function setMapMode() {
    const exploreEl = document.getElementById("explore-mode");
    const battleEl  = document.getElementById("battle-mode");
    const actionsEl = document.getElementById("actions-panel");
    const mapEl     = document.getElementById("map-mode");

    if (exploreEl) exploreEl.style.display = "none";
    if (battleEl)  battleEl.style.display  = "none";
    if (actionsEl) actionsEl.style.display = "none";
    if (mapEl)     mapEl.style.display     = "flex";
}

/** 맵 화면 숨기기 (전투 진입 시 etc.) */
function hideMapMode() {
    const mapEl = document.getElementById("map-mode");
    if (mapEl) mapEl.style.display = "none";
}

// ═══════════════════════════════════════════════════════════
// 맵 렌더링
// ═══════════════════════════════════════════════════════════

/** 전체 맵 렌더링 */
function renderMap(mapState) {
    const container = document.getElementById("map-scroll");
    if (!container) return;

    // 층별로 노드 그룹화
    const byLayer = {};
    mapState.nodes.forEach(n => {
        if (!byLayer[n.layer]) byLayer[n.layer] = [];
        byLayer[n.layer].push(n);
    });

    const availableSet = new Set(mapState.available || []);
    const totalLayers  = mapState.boss_layer;

    container.innerHTML = "";

    // column-reverse라 높은 layer가 위에 렌더됨
    for (let layer = 0; layer <= totalLayers; layer++) {
        const nodes = byLayer[layer] || [];
        const row   = document.createElement("div");
        row.className = "map-layer-row";
        row.dataset.layer = layer === totalLayers ? "BOSS" : `L${layer + 1}`;

        nodes.forEach(nodeData => {
            const el = _buildNodeEl(nodeData, availableSet);
            row.appendChild(el);
        });

        container.appendChild(row);
    }

    // 헤더 갱신
    const chBadge = document.getElementById("map-chapter-badge");
    const layerInfo = document.getElementById("map-layer-info");
    if (chBadge)  chBadge.textContent  = `CHAPTER ${mapState.chapter}`;
    if (layerInfo) {
        const visited = mapState.nodes.filter(n => n.visited).length;
        layerInfo.textContent = `${visited} / ${mapState.nodes.length} 노드`;
    }
}

/** 단일 노드 DOM 요소 생성 */
function _buildNodeEl(nodeData, availableSet) {
    const meta      = NODE_META[nodeData.node_type] || { icon: "?", label: nodeData.node_type };
    const available = availableSet.has(nodeData.node_id);
    const visited   = nodeData.visited;

    const el = document.createElement("div");
    el.className   = "map-node";
    el.dataset.type = nodeData.node_type;
    el.dataset.id   = nodeData.node_id;
    el.title        = meta.label;

    if (visited)        el.classList.add("visited");
    else if (available) el.classList.add("available");
    else                el.classList.add("locked");

    el.innerHTML = `
        <span class="map-node-icon">${meta.icon}</span>
        <span class="map-node-label">${meta.label}</span>
    `;

    if (available) {
        el.addEventListener("click", () => chooseNode(nodeData.node_id, nodeData.node_type));
    }

    return el;
}

// ═══════════════════════════════════════════════════════════
// 노드 선택
// ═══════════════════════════════════════════════════════════

/** 노드 선택 API 호출 */
async function chooseNode(nodeId, nodeType) {
    if (!nodeId) return;

    // 버튼 즉시 비활성화 (중복 클릭 방지)
    document.querySelectorAll(".map-node.available").forEach(el => {
        el.classList.remove("available");
        el.classList.add("locked");
        el.style.pointerEvents = "none";
    });

    try {
        const r = await api("/map/choose", { node_id: nodeId });
        if (!r.ok) {
            toast(r.error || "노드 선택 실패", "error");
            // 실패 시 맵 재갱신
            await _reloadMapState();
            return;
        }
        _pendingNodeId = nodeId;
        handleNodeResult(r);
    } catch (e) {
        console.error("[chooseNode]", e);
        toast("네트워크 오류", "error");
        await _reloadMapState();
    }
}

/** /api/map/choose 응답 처리 */
function handleNodeResult(r) {
    const event = r.event;

    // 맵 상태 업데이트 (응답에 포함된 경우)
    if (r.map) refreshMap(r.map);

    switch (event) {
        case "battle":
        case "elite":
        case "boss":
            logLine(`⚔ ${r.enemy?.name || "적"}이(가) 나타났다!`, "crit");
            hideMapMode();
            if (r.battle_state && typeof refreshBattle === "function") {
                refreshBattle(r.battle_state);
            }
            break;

        case "rest":
            _showRestPanel(r);
            break;

        case "shop":
            _showShopPanel(r);
            break;

        case "event":
            _showEventResult(r);
            // node_done: true면 즉시 완료
            if (r.node_done && r.map) refreshMap(r.map);
            break;

        default:
            toast("알 수 없는 이벤트", "error");
    }
}

/** 전투/이벤트 종료 후 맵으로 복귀 */
async function handleMapNodeDone(battleResult) {
    // 전투 종료 시 battle.py가 map.mark_visited 자동 호출
    // → result.map이 있으면 그걸 쓰고, 없으면 /api/map/state 재조회
    if (battleResult?.map) {
        refreshMap(battleResult.map);
        setMapMode();
        if (battleResult.map_done) {
            _showChapterClear(battleResult);
        }
        return;
    }
    await _reloadMapState();
    setMapMode();
}

// ═══════════════════════════════════════════════════════════
// 노드 타입별 UI 패널
// ═══════════════════════════════════════════════════════════

/** 휴식 패널 표시 */
function _showRestPanel(r) {
    const mapEl = document.getElementById("map-content-overlay");
    if (!mapEl) return;

    mapEl.style.display = "flex";
    mapEl.innerHTML = `
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

/** 휴식 선택 (heal / train) */
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

        // 레벨업 스탯 분배 모달
        if (typeof checkPendingPoints === "function") checkPendingPoints();

        // 노드 완료 처리
        await _completeNode(_pendingNodeId);
        _hideContentOverlay();
    } catch (e) {
        console.error("[chooseRestOption]", e);
        toast("오류 발생", "error");
    }
}

/** 상점 패널 표시 */
function _showShopPanel(r) {
    const mapEl = document.getElementById("map-content-overlay");
    if (!mapEl) return;

    const gold = r.gold || 0;
    const items = r.shop_items || [];

    mapEl.style.display = "flex";
    mapEl.innerHTML = `
        <div class="shop-panel">
            <div class="shop-header">
                <span class="panel-title">🛒 SHOP</span>
                <span class="shop-gold">💰 ${gold} G</span>
            </div>
            <div class="shop-items-grid">
                ${items.map(item => `
                    <div class="shop-item ${gold < item.price ? "cant-afford" : ""}"
                         onclick="${gold >= item.price ? `buyShopItem('${item.id}', ${item.price})` : ""}">
                        <span class="shop-item-name">${item.name}</span>
                        <span class="shop-item-effect">${item.effect}</span>
                        <span class="shop-item-price">${item.price} G</span>
                    </div>
                `).join("")}
            </div>
            <button class="btn shop-leave-btn" onclick="leaveShop()">
                나가기
            </button>
        </div>
    `;
}

/** 상점 구매 */
async function buyShopItem(itemId, price) {
    try {
        const r = await api("/shop/buy", { item_id: itemId, price });

        // 특수 아이템 가득 → swap 모달
        if (!r.ok && r.reason === "special_full") {
            if (typeof openInvSwap === "function") {
                openInvSwap(itemId, r.candidates || []);
            } else {
                toast("특수 아이템 칸이 가득 찼습니다.", "warn");
            }
            return;
        }
        if (!r.ok) { toast(r.error || "구매 실패", "error"); return; }

        if (r.player) {
            state.player = r.player;
            if (typeof refreshPlayer === "function") refreshPlayer();
        }

        logLine(`🛒 ${r.message || itemId + " 구매!"}`, "skill");
        toast(r.message || `${itemId} 구매!`, "ok");

        if (r.gold !== undefined) {
            const goldEl = document.querySelector(".shop-gold");
            if (goldEl) goldEl.textContent = `💰 ${r.gold} G`;
            document.querySelectorAll(".shop-item").forEach(el => {
                const priceEl = el.querySelector(".shop-item-price");
                if (!priceEl) return;
                const p = parseInt(priceEl.textContent);
                if (r.gold < p) el.classList.add("cant-afford");
                else el.classList.remove("cant-afford");
            });
        }
    } catch (e) {
        console.error("[buyShopItem]", e);
        toast("오류 발생", "error");
    }
}

/** 상점 나가기 */
async function leaveShop() {
    await _completeNode(_pendingNodeId);
    _hideContentOverlay();
}

/** 이벤트 결과 표시 */
function _showEventResult(r) {
    const mapEl = document.getElementById("map-content-overlay");
    if (!mapEl) return;

    const icon = r.item ? "📦" : "✨";
    mapEl.style.display = "flex";
    mapEl.innerHTML = `
        <div class="event-result-panel">
            <div class="event-icon">${icon}</div>
            <div class="event-message">${r.message || "이벤트 발생!"}</div>
            ${r.item ? `<div style="color:var(--accent-cyan);font-size:13px;font-weight:700;">${r.item} 획득!</div>` : ""}
            <button class="btn event-continue-btn" onclick="closeEventPanel()">계속하기</button>
        </div>
    `;

    // 플레이어 상태 갱신
    if (r.player) {
        state.player = r.player;
        if (typeof refreshPlayer === "function") refreshPlayer();
    }
}

/** 이벤트 패널 닫기 */
async function closeEventPanel() {
    _hideContentOverlay();
    // node_done이 true면 이미 백엔드에서 완료됨 → map state 재조회
    await _reloadMapState();
}

// ═══════════════════════════════════════════════════════════
// 챕터 클리어
// ═══════════════════════════════════════════════════════════

function _showChapterClear(result) {
    const isGameClear = result.game_clear;
    const nextChapter = result.next_chapter;

    const overlay = document.createElement("div");
    overlay.className = "chapter-clear-overlay";
    overlay.id = "chapter-clear-overlay";

    overlay.innerHTML = `
        <div class="chapter-clear-title">
            ${isGameClear ? "🎉 GAME CLEAR!" : `CHAPTER ${_mapState?.chapter || ""} CLEAR!`}
        </div>
        <div class="chapter-clear-sub">
            ${isGameClear
                ? "모든 챕터를 클리어했습니다!"
                : `챕터 ${nextChapter}로 진행합니다.`}
        </div>
        <button class="btn chapter-clear-btn" onclick="${isGameClear ? "restartGame()" : `startNextChapter(${nextChapter})`}">
            ${isGameClear ? "처음으로" : `챕터 ${nextChapter} 시작 ▶`}
        </button>
    `;

    document.body.appendChild(overlay);
}

/** 다음 챕터 시작 */
async function startNextChapter(chapter) {
    // 클리어 오버레이 제거
    const overlay = document.getElementById("chapter-clear-overlay");
    if (overlay) overlay.remove();

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
        toast("오류 발생", "error");
    }
}

// ═══════════════════════════════════════════════════════════
// 내부 헬퍼
// ═══════════════════════════════════════════════════════════

/** 노드 완료 API 호출 */
async function _completeNode(nodeId) {
    if (!nodeId) return;
    try {
        const r = await api("/map/node/complete", { node_id: nodeId });
        if (!r.ok) { toast(r.error || "노드 완료 실패", "error"); return; }
        _pendingNodeId = null;

        if (r.map) refreshMap(r.map);
        if (r.player) {
            state.player = r.player;
            if (typeof refreshPlayer === "function") refreshPlayer();
        }

        if (r.map_done) _showChapterClear(r);
    } catch (e) {
        console.error("[_completeNode]", e);
    }
}

/** 맵 상태 재조회 */
async function _reloadMapState() {
    try {
        const r = await api("/map/state", null, "GET");
        if (r.ok && r.map) refreshMap(r.map);
    } catch (e) {
        console.error("[_reloadMapState]", e);
    }
}

/** 콘텐츠 오버레이 숨기기 */
function _hideContentOverlay() {
    const el = document.getElementById("map-content-overlay");
    if (el) { el.style.display = "none"; el.innerHTML = ""; }
}