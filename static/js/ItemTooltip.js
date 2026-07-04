// ═══════════════════════════════════════════════════════════
// ItemTooltip.js — 공용 아이템 커스텀 툴팁
// ───────────────────────────────────────────────────────────
// [data-tooltip-item="아이템ID"] 속성을 가진 요소에 hover하면
// 마우스 옆에 이름+설명 말풍선을 띄운다.
//
// · 이벤트 위임(document 레벨) — 한 번만 바인딩하면
//   동적으로 렌더링되는 UI(패널/상점/전투메뉴/보상팝업/교체모달)에
//   자동 적용된다. 렌더 후 bind를 다시 호출할 필요 없음.
// · 표시명 itemLabel(id), 설명 itemDesc(id) (State.js)
// · 뷰포트 경계를 벗어나지 않게 위치 보정.
// 사용: 페이지 로드 시 bindItemTooltip() 1회 (아래에서 자동 실행)
// ═══════════════════════════════════════════════════════════

(function () {
    let tipEl = null;

    function _ensureTip() {
        tipEl = document.getElementById('item-tooltip');
        if (!tipEl) {
            tipEl = document.createElement('div');
            tipEl.id = 'item-tooltip';
            tipEl.className = 'item-tooltip';
            document.body.appendChild(tipEl);
        }
        return tipEl;
    }

    function _show(itemId, x, y) {
        const tip = _ensureTip();
        const name = (typeof itemLabel === 'function') ? itemLabel(itemId) : itemId;
        const desc = (typeof itemDesc === 'function') ? itemDesc(itemId) : '';
        tip.innerHTML =
            `<div class="item-tooltip-name">${name}</div>` +
            (desc ? `<div class="item-tooltip-desc">${desc}</div>` : '');
        tip.classList.add('active');
        _move(x, y);
    }

    function _move(x, y) {
        if (!tipEl || !tipEl.classList.contains('active')) return;
        const pad = 14;
        const rect = tipEl.getBoundingClientRect();
        let left = x + pad;
        let top  = y + pad;
        // 뷰포트 경계 보정 (오른쪽/아래로 넘치면 반대편에)
        if (left + rect.width > window.innerWidth - 4) {
            left = x - rect.width - pad;
        }
        if (top + rect.height > window.innerHeight - 4) {
            top = y - rect.height - pad;
        }
        tipEl.style.left = Math.max(4, left) + 'px';
        tipEl.style.top  = Math.max(4, top) + 'px';
    }

    function _hide() {
        if (tipEl) tipEl.classList.remove('active');
    }

    // 공개 함수 — root는 호환용 인자 (위임 방식이라 실제로는 document 1회면 충분)
    window.bindItemTooltip = function (root) {
        _ensureTip();
        // 중복 바인딩 방지
        if (document._itemTooltipBound) return;
        document._itemTooltipBound = true;

        document.addEventListener('mouseover', (e) => {
            const el = e.target.closest && e.target.closest('[data-tooltip-item]');
            if (el) _show(el.dataset.tooltipItem, e.clientX, e.clientY);
        });
        document.addEventListener('mousemove', (e) => {
            const el = e.target.closest && e.target.closest('[data-tooltip-item]');
            if (el) _move(e.clientX, e.clientY);
            else _hide();
        });
        document.addEventListener('mouseout', (e) => {
            const el = e.target.closest && e.target.closest('[data-tooltip-item]');
            if (el) _hide();
        });
        // 클릭/스크롤 시에도 정리 (모달 전환 대비)
        document.addEventListener('click', _hide, true);
        document.addEventListener('scroll', _hide, true);
    };

    // 자동 초기화
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => window.bindItemTooltip());
    } else {
        window.bindItemTooltip();
    }
})();