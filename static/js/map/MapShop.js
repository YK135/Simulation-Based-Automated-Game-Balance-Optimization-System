/* map/MapShop.js — 상점 패널/구매 */

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
                         data-item-id="${item.id}"
                         data-price="${item.price}">
                        <span class="shop-item-name">${item.name}</span>
                        <span class="shop-item-effect">${item.effect}</span>
                        <span class="shop-item-price">${item.price} G</span>
                    </div>
                `).join("")}
            </div>
            <button class="btn shop-leave-btn" id="shop-leave-btn">나가기</button>
        </div>
    `;

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
                document.querySelectorAll(`.shop-item[data-item-id="${itemId}"]`).forEach(el => {
                    el.classList.add("cant-afford");
                    el.title = "포션 슬롯 가득 참";
                });
            }
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
    }
}

async function leaveShop() {
    await _completeNode(_pendingNodeId);
    _hideOverlay();
}