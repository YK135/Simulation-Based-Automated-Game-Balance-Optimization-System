// ═══════════════════════════════════════════════════════════
// RewardModal.js — 전투 보상 팝업
// ───────────────────────────────────────────────────────────
// 전투 승리 후 획득 골드/아이템을 팝업으로 표시한다.
// · 보상은 이미 백엔드에서 지급된 상태 — 이 팝업은 "표시 전용" (1차)
// · showRewardModal(result)는 Promise를 반환 — 확인 버튼 클릭까지 대기
//   (Actions.js에서 await 후 노드 완료 처리로 진행)
// · 유물 확장 예약: result.relics_gained가 생기면 #reward-relic-area에
//   "2개 중 1개 선택" UI를 붙일 수 있게 영역/구조를 비워둠.
// 사용: await showRewardModal(r);
// ═══════════════════════════════════════════════════════════

function showRewardModal(result) {
    return new Promise((resolve) => {
        const modal = document.getElementById('modal-reward');
        if (!modal) { resolve(); return; }

        const gold  = result.gold_gained  || 0;
        const items = result.items_gained || [];
        const relics = result.relics_gained || [];
        const hasLoot = gold > 0 || items.length > 0 || relics.length > 0;

        // ★ 예전엔 보상이 하나도 없으면(보스전은 items_gained 등 필드 자체가
        //   없었음 — app/Battle.py 참고, 이제는 항상 채워짐) 팝업을 생략하고
        //   바로 다음 화면으로 넘어갔다. 그러면 "승리 확인" 절차 없이 화면이
        //   훅 넘어가서 승리 상태를 볼 틈이 없었다 — 이제 보상이 없어도
        //   "전리품 없음"과 확인 버튼으로 항상 모달을 띄운다.
        const goldEl = document.getElementById('reward-gold');
        if (goldEl) goldEl.textContent = gold > 0 ? `💰 ${gold} G` : (hasLoot ? '' : '전리품 없음');

        // ── 아이템 목록 (일반/특수 구분 + 툴팁) ──
        const listEl = document.getElementById('reward-item-list');
        if (listEl) {
            listEl.innerHTML = '';
            items.forEach(id => {
                const row = document.createElement('div');
                const isPotion = String(id).endsWith('_potion');
                row.className = 'reward-item' + (isPotion ? '' : ' reward-special');
                row.dataset.tooltipItem = id;
                if (typeof itemDesc === 'function' && itemDesc(id)) row.title = itemDesc(id);

                if (typeof renderIconWithFallback === 'function') {
                    const meta = (typeof ITEM_ICONS !== 'undefined' ? ITEM_ICONS[id] : null) || { icon: '□' };
                    row.appendChild(renderIconWithFallback(meta, 'item-icon'));
                }
                const nameSp = document.createElement('span');
                nameSp.className = 'reward-item-name';
                nameSp.textContent = (typeof itemLabel === 'function') ? itemLabel(id) : id;
                row.appendChild(nameSp);
                if (!isPotion) {
                    const badge = document.createElement('span');
                    badge.className = 'reward-item-badge';
                    badge.textContent = '★';
                    row.appendChild(badge);
                }
                listEl.appendChild(row);
            });
            listEl.style.display = items.length ? '' : 'none';
        }

        // ── 유물 영역 (추후 확장 — 현재는 항상 숨김) ──
        const relicArea = document.getElementById('reward-relic-area');
        if (relicArea) relicArea.style.display = relics.length ? '' : 'none';

        // ── 확인 버튼 → 닫기 + resolve ──
        const okBtn = document.getElementById('reward-confirm-btn');
        const close = () => {
            modal.classList.remove('active');
            resolve();
        };
        if (okBtn) {
            // 이전 리스너 제거 (재사용 안전)
            okBtn.replaceWith(okBtn.cloneNode(true));
            document.getElementById('reward-confirm-btn')
                .addEventListener('click', close, { once: true });
        }

        modal.classList.add('active');
    });
}