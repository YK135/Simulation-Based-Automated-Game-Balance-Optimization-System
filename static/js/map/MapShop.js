/* map/MapShop.js — 상점 패널/구매 */

function _showShopPanel(r) {
    const overlay = document.getElementById("map-content-overlay");
    if (!overlay) return;
    const gold  = r.gold || 0;
    const items = r.shop_items || [];
    overlay.style.display = "flex";
    // 일반(포션) / 특수 섹션 분리 — type 필드 기준 (없으면 id로 판별)
    const isSpecial = (it) => (it.type === "special") ||
        (it.type !== "potion" && !String(it.id).endsWith("_potion"));
    const normals  = items.filter(it => !isSpecial(it));
    const specials = items.filter(isSpecial);

    const cardHtml = (item) => `
        <div class="shop-item ${gold < item.price ? "cant-afford" : ""}"
             data-item-id="${item.id}"
             data-tooltip-item="${item.id}"
             data-price="${item.price}"
             title="${(typeof ITEM_DESCRIPTIONS !== "undefined" && ITEM_DESCRIPTIONS[item.id]) || item.effect || ""}">
            <span class="shop-item-icon" data-icon-for="${item.id}"></span>
            <span class="shop-item-name">${item.name}</span>
            <span class="shop-item-effect">${item.effect}</span>
            <span class="shop-item-price">${item.price} G</span>
        </div>`;

    const sectionHtml = (label, list) => list.length ? `
        <div class="shop-section-label">${label}</div>
        <div class="shop-items-grid">${list.map(cardHtml).join("")}</div>` : "";

    overlay.innerHTML = `
        <div class="shop-panel">
            <div class="shop-header">
                <span class="panel-title">🛒 SHOP</span>
                <span class="shop-gold">💰 ${gold} G</span>
            </div>
            <div class="shop-scroll-area">
                ${sectionHtml("일반 아이템", normals)}
                ${sectionHtml("특수 아이템", specials)}
            </div>
            <button class="btn shop-leave-btn" id="shop-leave-btn">나가기</button>
        </div>
    `;

    // 아이콘 주입 (이미지 우선 + 이모지 폴백) — name 텍스트/구매 id 영향 없음
    overlay.querySelectorAll(".shop-item-icon[data-icon-for]").forEach(span => {
        const id = span.dataset.iconFor;
        const meta = (typeof ITEM_ICONS !== "undefined" ? ITEM_ICONS[id] : null) || { icon: "□" };
        if (typeof renderIconWithFallback === "function") {
            span.replaceWith(renderIconWithFallback(meta, "shop-item-icon"));
        } else {
            span.textContent = meta.icon;
        }
    });

    // 이벤트 바인딩 (인라인 onclick 대체)
    overlay.querySelectorAll(".shop-item[data-item-id]").forEach(el => {
        el.addEventListener("click", () => {
            if (el.classList.contains("cant-afford")) return;
            buyShopItem(el.dataset.itemId, Number(el.dataset.price));
        });
    });
    overlay.querySelector("#shop-leave-btn")
        ?.addEventListener("click", leaveShop);
}

// ★ 연속 클릭 방지 — 가드가 없어서 같은 아이템(또는 다른 아이템)을
//   응답 오기 전에 여러 번 누르면 중복 구매가 발사될 수 있었음. 진행 중엔
//   상점 아이템 카드 전체를 클릭 불가로 막는다(개별 disabled 속성이 없는
//   div라 pointer-events로 처리).
let _shopBuyProcessing = false;

async function buyShopItem(itemId, price) {
    if (_shopBuyProcessing) return;
    _shopBuyProcessing = true;
    const items = document.querySelectorAll(".shop-item");
    items.forEach(el => el.style.pointerEvents = "none");
    try {
        const r = await api("/shop/buy", { item_id: itemId, price });
        // ★ 포션도 특수템과 동일하게 "버릴 아이템 선택" UI를 받도록 통일
        //   (예전엔 포션 가득 참은 그냥 재구매 불가 표시만 하고 끝났음).
        if (!r.ok && (r.reason === "special_full" || r.reason === "potion_full")) {
            if (typeof openInvSwap === "function") await openInvSwap(itemId, r.candidates || []);
            else toast("가방이 가득 찼습니다.", "warn");
            return;
        }
        if (!r.ok) {
            const msg = r.error || "구매 실패";
            toast(msg, "error");
            logLine(`🛒 ${msg}`, "warn");
            return;
        }
        if (r.player) state.player = r.player;
        if (r.gold !== undefined) state.gold = r.gold;
        if (typeof refreshPlayer === "function") refreshPlayer();
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
    } finally {
        _shopBuyProcessing = false;
        // _showShopPanel()로 이미 다시 그려졌을 수 있으므로 최신 노드 목록을 다시 조회
        document.querySelectorAll(".shop-item").forEach(el => el.style.pointerEvents = "");
    }
}

async function leaveShop() {
    await _completeNode(_pendingNodeId);
    _hideOverlay();
}