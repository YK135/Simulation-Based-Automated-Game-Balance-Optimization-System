/* battle/BattleMenus.js — 스킬/아이템 메뉴 렌더 */

// 스킬 메뉴 렌더
function renderBattleSkillMenu(bs) {
    if (bs.skills) {
        const sl = document.getElementById('skill-list');
        sl.innerHTML = '';
        bs.skills.forEach(sk => {
            const cell = document.createElement('div');
            cell.className = 'submenu-item';
            // MP 0 + HP 지불(피의 격노)은 비용 표기를 HP로
            const costLabel = (sk.mp > 0 || !sk.hp_cost) ? `MP${sk.mp}` : `HP${sk.hp_cost}%`;
            cell.innerHTML = `${sk.name}<span class="cost">${costLabel}</span>`;
            // usable은 서버가 MP + 대상 조건(원소 폭발·피의 수확) + 전투당 횟수(패 고치기)까지 본 값
            const canUse = bs.player_mp >= sk.mp && sk.usable !== false;
            if (!canUse) {
                cell.style.opacity = 0.4;
                if (sk.reason) cell.title = sk.reason;
            }
            cell.onclick = canUse ? () => useSkill(sk.name) : null;
            sl.appendChild(cell);
        });
        if (!bs.skills.length) {
            sl.innerHTML = '<div style="color:var(--text-muted); padding:8px; grid-column:1/-1;">학습한 스킬 없음</div>';
        }
    }
}

// 아이템 메뉴 렌더 (포션/특수)
function renderBattleItemMenu(bs) {
const il = document.getElementById('item-list');
il.innerHTML = '';

// 전투 중 아이템 메뉴는 bs.items(실시간) 기준
// state.player.inventory는 전투 종료 전까지 업데이트 안 됨
const battleItems = bs.items || [];

if (battleItems.length === 0) {
    il.innerHTML = '<div style="color:var(--text-muted); padding:8px; grid-column:1/-1;">아이템 없음</div>';
} else {
    const counts = {};
    battleItems.forEach(it => {
        if (typeof it === 'object' && it !== null) {
            // {name, count} 형식
            counts[it.name] = (counts[it.name] || 0) + (it.count || 1);
        } else {
            // 평탄 문자열 형식
            counts[it] = (counts[it] || 0) + 1;
        }
    });
    Object.entries(counts).forEach(([name, n]) => {
        const cell = document.createElement('div');
        cell.className = 'submenu-item';
        cell.dataset.tooltipItem = name;
        if (typeof itemDesc === 'function' && itemDesc(name)) cell.title = itemDesc(name);
        // 아이콘(이미지 우선 + 이모지 폴백) + 이름 + 수량
        if (typeof renderIconWithFallback === 'function') {
            cell.appendChild(renderIconWithFallback(
                (typeof ITEM_ICONS !== 'undefined' ? ITEM_ICONS[name] : null) || { icon: '□' },
                'item-icon'));
        }
        const nameEl = document.createElement('span');
        nameEl.className = 'item-name';
        nameEl.textContent = name;
        const costEl = document.createElement('span');
        costEl.className = 'cost';
        costEl.textContent = `×${n}`;
        cell.appendChild(nameEl);
        cell.appendChild(costEl);
        cell.onclick = () => useItem(name);
        il.appendChild(cell);
    });
}
}