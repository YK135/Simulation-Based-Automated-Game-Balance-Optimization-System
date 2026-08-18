/* map/MapRender.js — 노드/연결선/챕터맵 렌더링
   (chooseNode는 MapActions.js, _redrawMapLater/scrollToAvailableNode는 UI_Map.js 오케스트레이터) */

function renderMap(mapState) {
    const scroll = document.getElementById("map-scroll");
    if (!scroll) return;

    // ── 챕터 배경 이미지 적용 ──
    /*
      챕터 배경 이미지 자리
      Chapter 1: static/img/map/chapter_1_bg.png
      Chapter 2: static/img/map/chapter_2_bg.png
      권장 크기: 1280x720px, 16:9, 어두운 배경 권장
    */
    // 배경은 실제 노드맵 뷰포트인 #map-scroll에만 적용 (map-mode는 clipping만).
    // map-mode에 넣으면 header/overlay/footer까지 감싸 이미지가 아래로 새 보임.
    const mapEl = document.getElementById("map-mode");
    const bg = _mapBackgroundForState(mapState);
    if (mapEl) mapEl.style.backgroundImage = "";
    if (scroll) {
        scroll.style.backgroundImage = `url('${bg}')`;
        scroll.style.backgroundSize = "cover";
        scroll.style.backgroundPosition = "center";
        scroll.style.backgroundRepeat = "no-repeat";
    }

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

    // 아이콘: 이미지 우선, 실패/없으면 이모지 폴백
    const iconWrap = document.createElement("span");
    iconWrap.className = "map-node-icon";
    const fallback = document.createElement("span");
    fallback.className = "map-node-icon-fallback";
    fallback.textContent = meta.icon || "?";
    if (meta.img) {
        const img = document.createElement("img");
        img.className = "map-node-icon-img";
        img.src = meta.img;
        img.alt = "";
        img.draggable = false;
        img.addEventListener("error", () => {
            img.style.display = "none";
            fallback.style.display = "";
        });
        img.addEventListener("load", () => {
            fallback.style.display = "none";
        });
        iconWrap.appendChild(img);
    }
    iconWrap.appendChild(fallback);

    const labelEl = document.createElement("span");
    labelEl.className = "map-node-label";
    labelEl.textContent = meta.label;

    el.appendChild(iconWrap);
    el.appendChild(labelEl);

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
                    //이미 지나온 경로
                    line.setAttribute("stroke", "rgb(0, 0, 0)");
                    line.setAttribute("stroke-width", "4");
                    line.setAttribute("stroke-dasharray", "none");
                } else if (srcNode.available || srcNode.on_path) {
                    // 현재 선택 가능하거나 현재 경로에서 이어진 선
                    line.setAttribute("stroke", "rgb(255, 247, 98)");
                    line.setAttribute("stroke-width", "3");
                    line.setAttribute("stroke-dasharray", "6 5");
                } else {
                    // 잠긴/기본 연결 선
                    line.setAttribute("stroke", "rgb(255, 247, 98)");
                    line.setAttribute("stroke-width", "2");
                    line.setAttribute("stroke-dasharray", "4 6");
                }
                line.style.filter = "drop-shadow(0 0 3px rgba(0,0,0,0.9))";
                svg.appendChild(line);
            });
        });
        });
    }

function _mapBackgroundForState(mapState) {
    const chapter = mapState.chapter || 1;
    const layer = mapState.current_layer || 0;

    if (chapter === 1) {
        if (layer >= 11) return "/img/map/chapter_1_night.png";
        if (layer >= 6) return "/img/map/chapter_1_sunset.png";
        return "/img/map/chapter_1_sun.png";
    }

    return `/${mapState.bg_image || `img/map/chapter_${chapter}_bg.png`}`;
}