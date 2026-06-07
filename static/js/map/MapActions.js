/* map/MapActions.js — 노드 선택 / 결과 처리 / 노드 완료
   (renderMap은 MapRender.js, setMapMode/refreshMap은 UI_Map.js, 상점/휴식/이벤트 패널은 UI_Map.js) */

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