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

// ─────────────────────────────────────────────
// 노드 타입 메타
// ─────────────────────────────────────────────
/*
  노드 아이콘 이미지 자리
  권장 크기: PNG/WebP 투명 배경, 64x64px 또는 96x96px
  UI 표시 크기: 40~56px

  예시 경로:
    battle: static/img/map/node_battle.png
    elite:  static/img/map/node_elite.png
    event:  static/img/map/node_event.png
    rest:   static/img/map/node_rest.png
    shop:   static/img/map/node_shop.png
    boss:   static/img/map/node_boss.png

  이미지 사용 시 _buildNodeEl()의 el.innerHTML을
  <img src="img/map/node_${type}.png" ...> 형식으로 교체하세요.
*/
const NODE_META = {
    battle: { icon: "⚔",  label: "BATTLE",  color: "#ff5050" },
    elite:  { icon: "💀", label: "ELITE",   color: "#ff9632" },
    rest:   { icon: "🏕", label: "REST",    color: "#50dc78" },
    shop:   { icon: "🛒", label: "SHOP",    color: "#ffd23c" },
    event:  { icon: "❓", label: "EVENT",   color: "#a064ff" },
    boss:   { icon: "💠", label: "BOSS",    color: "#ff2828" },
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
    ["explore-mode", "battle-mode", "actions-panel"].forEach(id => {
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

// ═══════════════════════════════════════════════════════════
// 맵 렌더링
// ═══════════════════════════════════════════════════════════

function renderMap(mapState) {
    const scroll = document.getElementById("map-scroll");
    if (!scroll) return;

    // ── 챕터 배경 이미지 적용 ──
    /*
      챕터 배경 이미지 자리
      Chapter 1: static/img/map/chapter_1_bg.png
      Chapter 2: static/img/map/chapter_2_bg.png
      권장 크기: 1280x720px, 16:9, 어두운 배경 권장
      적용 방법: 아래 주석 해제 후 이미지 파일 배치
    */
    // const mapEl = document.getElementById("map-mode");
    // if (mapEl) mapEl.style.backgroundImage = `url('${mapState.bg_image}')`;

    // ── 노드 데이터 정리 ──
    const nodes       = mapState.nodes || [];
    const availSet    = new Set(mapState.available || []);
    const totalLayers = mapState.total_layers || 15;
    const bossLayer   = mapState.boss_layer   || 15;
    const playerBranch = mapState.player_branch;  // "left" | "right" | null

    // layer → branch → nodes 그룹화
    const byLayer = {};
    nodes.forEach(n => {
        if (!byLayer[n.layer]) byLayer[n.layer] = { left: [], right: [], boss: [], start: [] };
        byLayer[n.layer][n.branch] = byLayer[n.layer][n.branch] || [];
        byLayer[n.layer][n.branch].push(n);
    });

    scroll.innerHTML = "";

    // ── 맵 헤더 갱신 ──
    const badge = document.getElementById("map-chapter-badge");
    const info  = document.getElementById("map-layer-info");
    if (badge) badge.textContent = `CHAPTER ${mapState.chapter}`;
    if (info) {
        const visited = nodes.filter(n => n.visited).length;
        info.textContent = `${visited} / ${nodes.length} 노드`;
    }

    // ── 갈래 라벨 (map-branch-status에 렌더, scroll 밖 고정) ──
    const branchStatus = document.getElementById("map-branch-status");
    if (branchStatus) {
        branchStatus.innerHTML = `
            <span class="map-branch-label ${playerBranch === 'left' ? 'active' : ''}">◀ LEFT</span>
            <span class="map-branch-divider">|</span>
            <span class="map-branch-label ${playerBranch === 'right' ? 'active' : ''}">RIGHT ▶</span>
        `;
    }

    // ── 계층 순서 렌더링 (보스가 위 = 먼저 추가, 시작이 아래 = 나중 추가)
    for (let layer = totalLayers; layer >= 0; layer--) {
        const layerData = byLayer[layer] || {};
        const row = document.createElement("div");
        row.className = "map-layer-row";
        row.dataset.layer = layer === bossLayer ? "BOSS" : layer === 0 ? "START" : `L${layer}`;

        if (layer === 0) {
            // 시작 노드 — 중앙 정렬
            const startWrap = document.createElement("div");
            startWrap.className = "map-start-row";
            const startNodes = layerData["start"] || [];
            startNodes.forEach(nd => startWrap.appendChild(_buildNodeEl(nd, availSet)));
            row.appendChild(startWrap);
        } else if (layer === bossLayer) {
            // 보스 계층 — grid 전체 너비 중앙 정렬
            const bossWrap = document.createElement("div");
            bossWrap.className = "map-boss-row";
            const bossNodes = layerData["boss"] || [];
            bossNodes.forEach(nd => bossWrap.appendChild(_buildNodeEl(nd, availSet)));
            row.appendChild(bossWrap);
        } else {
            // 일반 계층 — 좌/우 2열
            const leftCol  = document.createElement("div");
            const divider  = document.createElement("div");
            const rightCol = document.createElement("div");
            leftCol.className  = "map-branch-col left-col";
            divider.className  = "map-col-divider";
            rightCol.className = "map-branch-col right-col";

            // 좌측 branch
            const leftNodes = layerData["left"] || [];
            leftNodes.forEach(nd => leftCol.appendChild(_buildNodeEl(nd, availSet)));
            if (leftNodes.length === 0) {
                leftCol.innerHTML = '<div class="map-empty-col"></div>';
            }

            // 우측 branch
            const rightNodes = layerData["right"] || [];
            rightNodes.forEach(nd => rightCol.appendChild(_buildNodeEl(nd, availSet)));
            if (rightNodes.length === 0) {
                rightCol.innerHTML = '<div class="map-empty-col"></div>';
            }

            row.appendChild(leftCol);
            row.appendChild(divider);
            row.appendChild(rightCol);
        }

        scroll.appendChild(row);
    }

    // ── SVG 연결선 (available 노드 → next_ids) ──
    // 스크롤 이동 후 연결선 계산 (순서 보장)
    _redrawMapLater(scroll, nodes, availSet);
}

/** 단일 노드 DOM 요소 생성 */
function _buildNodeEl(nodeData, availSet) {
    const meta      = NODE_META[nodeData.node_type] || { icon: "?", label: nodeData.node_type };
    const available = availSet.has(nodeData.node_id);
    const visited   = nodeData.visited;
    const onPath    = nodeData.on_path;

    const el = document.createElement("div");
    el.className    = "map-node";
    el.dataset.type = nodeData.node_type;
    el.dataset.id   = nodeData.node_id;
    el.dataset.layer = nodeData.layer;
    el.dataset.branch = nodeData.branch;
    el.title        = meta.label;

    if (visited)        el.classList.add("visited");
    else if (available) el.classList.add("available");
    else                el.classList.add("locked");

    if (onPath) el.classList.add("on-path");

    el.innerHTML = `
        <span class="map-node-icon">${meta.icon}</span>
        <span class="map-node-label">${meta.label}</span>
    `;

    // x_pos 좌표 기반 배치 (x_offset은 fallback)
    const xPos = nodeData.x_pos !== undefined ? nodeData.x_pos : (nodeData.x_offset || 0);
    el.style.setProperty("--node-x", `${xPos}px`);

    if (available) {
        el.addEventListener("click", () => {
            // 즉시 비활성화 (중복 클릭 방지)
            el.classList.remove("available");
            el.classList.add("locked");
            el.style.pointerEvents = "none";
            chooseNode(nodeData.node_id, nodeData.node_type);
        });
    }

    return el;
}

/** SVG 연결선 그리기 */
function _drawConnections(container, nodes, availSet) {
    // 이전 SVG 제거
    container.querySelectorAll(".map-connections-svg").forEach(el => el.remove());

    const nodeMap = {};
    nodes.forEach(n => nodeMap[n.node_id] = n);

    // available 노드에서 next_ids로 선 그리기
    // DOM에서 위치를 읽어야 하므로 requestAnimationFrame 사용
    requestAnimationFrame(() => {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.classList.add("map-connections-svg");
        const scrollH = container.scrollHeight || container.offsetHeight;
        const scrollW = container.scrollWidth  || container.offsetWidth;
        svg.style.cssText = `
            position:absolute; top:0; left:0;
            width:${scrollW}px; height:${scrollH}px;
            pointer-events:none; z-index:0;
            overflow:visible;
        `;
        svg.setAttribute("viewBox", `0 0 ${scrollW} ${scrollH}`);
        container.style.position = "relative";
        container.appendChild(svg);

        const containerRect = container.getBoundingClientRect();

        nodes.forEach(srcNode => {
            // 모든 연결선 표시 (필터 없음)
            srcNode.next_ids.forEach(nextId => {
                const dstNode = nodeMap[nextId];
                if (!dstNode) return;

                const srcEl = container.querySelector(`[data-id="${srcNode.node_id}"]`);
                const dstEl = container.querySelector(`[data-id="${dstNode.node_id}"]`);
                if (!srcEl || !dstEl) return;

                const sRect = srcEl.getBoundingClientRect();
                const dRect = dstEl.getBoundingClientRect();
                const scrollTop  = container.scrollTop  || 0;
                const scrollLeft = container.scrollLeft || 0;
                const sx = sRect.left + sRect.width / 2  - containerRect.left + scrollLeft;
                const sy = sRect.top  + sRect.height / 2 - containerRect.top  + scrollTop;
                const dx = dRect.left + dRect.width / 2  - containerRect.left + scrollLeft;
                const dy = dRect.top  + dRect.height / 2 - containerRect.top  + scrollTop;
                // 노드 원 테두리에서 시작/끝 (중심 관통 방지)
                const NODE_RADIUS = 24, LINE_GAP = 3, TRIM = NODE_RADIUS + LINE_GAP;
                const vx = dx - sx, vy = dy - sy;
                const len = Math.sqrt(vx*vx + vy*vy) || 1;
                const x1 = sx + (vx/len)*TRIM, y1 = sy + (vy/len)*TRIM;
                const x2 = dx - (vx/len)*TRIM, y2 = dy - (vy/len)*TRIM;

                const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
                line.setAttribute("x1", x1); line.setAttribute("y1", y1);
                line.setAttribute("x2", x2); line.setAttribute("y2", y2);

                // 3단계 선 스타일
                if (srcNode.on_path && dstNode.on_path) {
                    line.setAttribute("stroke", "rgba(0,255,208,0.8)");
                    line.setAttribute("stroke-width", "2.5");
                    line.setAttribute("stroke-dasharray", "none");
                } else if (srcNode.available || srcNode.on_path) {
                    line.setAttribute("stroke", "rgba(0,255,208,0.45)");
                    line.setAttribute("stroke-width", "2");
                    line.setAttribute("stroke-dasharray", "5 3");
                } else {
                    line.setAttribute("stroke", "rgba(120,140,160,0.22)");
                    line.setAttribute("stroke-width", "1");
                    line.setAttribute("stroke-dasharray", "3 4");
                }
                svg.appendChild(line);
            });
        });
        });
    }

// ═══════════════════════════════════════════════════════════
// 노드 선택
// ═══════════════════════════════════════════════════════════

async function chooseNode(nodeId, nodeType) {
    if (!nodeId) return;

    // 중복 클릭 방지
    document.querySelectorAll(".map-node.available").forEach(el => {
        el.classList.replace("available", "locked");
        el.style.pointerEvents = "none";
    });

    try {
        const r = await api("/map/choose", { node_id: nodeId });
        if (!r.ok) {
            toast(r.error || "노드 선택 실패", "error");
            await _reloadMapState();
            return;
        }
        _pendingNodeId = nodeId;
        // 백엔드 최신 맵 상태로 즉시 재렌더
        if (r.map) refreshMap(r.map);
        else await _reloadMapState();
        handleNodeResult(r);
    } catch (e) {
        console.error("[chooseNode]", e);
        toast("네트워크 오류", "error");
        await _reloadMapState();
    }
}

function handleNodeResult(r) {
    const event = r.event;

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
            if (r.node_done && r.map) refreshMap(r.map);
            break;

        case "item_full":
            _showEventResult(r);
            break;

        case "item_rejected":
            toast(r.message || "아이템 획득 실패", "warn");
            if (r.node_done && r.map) refreshMap(r.map);
            break;

        default:
            toast("알 수 없는 이벤트", "error");
    }
}

async function handleMapNodeDone(battleResult) {
    if (battleResult?.map) {
        refreshMap(battleResult.map);
        setMapMode();
        if (battleResult.map_done) _showChapterClear(battleResult);
        return;
    }
    await _reloadMapState();
    setMapMode();
}

// ═══════════════════════════════════════════════════════════
// 노드 타입별 패널
// ═══════════════════════════════════════════════════════════

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

function _showShopPanel(r) {
    const overlay = document.getElementById("map-content-overlay");
    if (!overlay) return;
    const gold  = r.gold || 0;
    const items = r.shop_items || [];
    overlay.style.display = "flex";
    overlay.innerHTML = `
        <div class="shop-panel">
            <div class="shop-header">
                <span class="panel-title">🛒 SHOP</span>
                <span class="shop-gold">💰 ${gold} G</span>
            </div>
            <div class="shop-items-grid">
                ${items.map(item => `
                    <div class="shop-item ${gold < item.price ? "cant-afford" : ""}"
                         onclick="${gold >= item.price ? `buyShopItem('${item.id}',${item.price})` : ""}">
                        <span class="shop-item-name">${item.name}</span>
                        <span class="shop-item-effect">${item.effect}</span>
                        <span class="shop-item-price">${item.price} G</span>
                    </div>
                `).join("")}
            </div>
            <button class="btn shop-leave-btn" onclick="leaveShop()">나가기</button>
        </div>
    `;
}

async function buyShopItem(itemId, price) {
    try {
        const r = await api("/shop/buy", { item_id: itemId, price });
        if (!r.ok && r.reason === "special_full") {
            if (typeof openInvSwap === "function") openInvSwap(itemId, r.candidates || []);
            else toast("특수 아이템 칸이 가득 찼습니다.", "warn");
            return;
        }
        if (!r.ok) {
            const msg = r.error || "구매 실패";
            toast(msg, "error");
            logLine(`🛒 ${msg}`, "warn");
            // 포션 가득 찬 경우 상점 버튼 시각적 표시
            if (r.reason === "potion_full") {
                document.querySelectorAll(`.shop-item[data-id="${itemId}"]`).forEach(el => {
                    el.classList.add("cant-afford");
                    el.title = "포션 슬롯 가득 참";
                });
            }
            return;
        }
        if (r.player) {
            state.player = r.player;
            if (typeof refreshPlayer === "function") refreshPlayer();
        }
        logLine(`🛒 ${r.message || itemId + " 구매!"}`, "skill");
        toast(r.message || `${itemId} 구매!`, "ok");

        // 상점 UI 재렌더 (골드/재고 반영)
        if (r.shop_items) {
            _showShopPanel({ gold: r.gold, shop_items: r.shop_items });
        } else if (r.gold !== undefined) {
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
    }
}

async function leaveShop() {
    await _completeNode(_pendingNodeId);
    _hideOverlay();
}

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
            ${r.item ? `<div style="color:var(--accent-cyan);font-size:13px;font-weight:700;">${r.item} 획득!</div>` : ""}
            <button class="btn event-continue-btn" onclick="closeEventPanel()">계속하기</button>
        </div>
    `;
    if (r.player) {
        state.player = r.player;
        if (typeof refreshPlayer === "function") refreshPlayer();
    }
}

async function closeEventPanel() {
    _hideOverlay();
    await _reloadMapState();
}

// ═══════════════════════════════════════════════════════════
// 챕터 클리어
// ═══════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════
// 내부 헬퍼
// ═══════════════════════════════════════════════════════════

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

async function _reloadMapState() {
    try {
        const r = await api("/map/state", null, "GET");
        if (r.ok && r.map) refreshMap(r.map);
    } catch (e) {
        console.error("[_reloadMapState]", e);
    }
}

function _hideOverlay() {
    const el = document.getElementById("map-content-overlay");
    if (el) { el.style.display = "none"; el.innerHTML = ""; }
}