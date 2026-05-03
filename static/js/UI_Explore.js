/* ═══════════════════════════════════════════════════════════
   ui-explore.js — 탐험 모드 UI
   - refreshExploreInfo: 인벤토리/스탯/스킬 카드 3개 갱신
   - refreshExploreTurn: 진행 턴 progress 바 갱신
   - setExploreMode: 평시 모드로 UI 전환
   ═══════════════════════════════════════════════════════════ */

// 탐험 모드 카드 갱신
function refreshExploreInfo() {
    if (!state.player) return;
    const p = state.player;

    // 인벤토리 (player.items) — 탐험 중 클릭으로 사용 가능
    // 백엔드 형식:
    //  - player_dict: 단순 문자열 배열 ['HP_S_potion', 'HP_S_potion', ...]
    //  - 전투 state.items: [{name, count}, ...]
    const invEl = document.getElementById('explore-inventory');
    if (invEl) {
        const items = p.items || [];
        let entries = [];
        if (items.length > 0) {
            if (typeof items[0] === 'object' && items[0].name !== undefined) {
                entries = items.map(it => [it.name, it.count]);
            } else {
                const counts = {};
                items.forEach(it => counts[it] = (counts[it]||0)+1);
                entries = Object.entries(counts);
            }
        }
        if (entries.length === 0) {
            invEl.innerHTML = '<div class="explore-empty">아이템이 없습니다</div>';
        } else {
            invEl.innerHTML = '';
            entries.forEach(([name, n]) => {
                const row = document.createElement('div');
                row.className = 'inv-item clickable';
                row.title = '클릭해서 사용';
                row.innerHTML = `<span>${name}</span><span class="qty">×${n}</span>`;
                row.onclick = () => useItemInField(name);
                invEl.appendChild(row);
            });
        }
    }

    // 스탯 (간단 요약)
    const statEl = document.getElementById('explore-stats');
    if (statEl) {
        statEl.innerHTML = `
            <div class="explore-stat-row"><span>STG</span><span class="v">${p.stg}</span></div>
            <div class="explore-stat-row"><span>SP</span><span class="v">${p.sp}</span></div>
            <div class="explore-stat-row"><span>ARM</span><span class="v">${p.arm}</span></div>
            <div class="explore-stat-row"><span>SPARM</span><span class="v">${p.sparm}</span></div>
            <div class="explore-stat-row"><span>SPD</span><span class="v">${p.spd}</span></div>
            <div class="explore-stat-row"><span>LUC</span><span class="v">${p.luc}</span></div>
        `;
    }

    // 스킬
    const skEl = document.getElementById('explore-skills');
    if (skEl) {
        const skills = p.skills || [];
        if (skills.length === 0) {
            skEl.innerHTML = '<div class="explore-empty">학습한 스킬 없음</div>';
        } else {
            skEl.innerHTML = skills.map(sk =>
                `<span class="sk-chip">${sk}</span>`
            ).join('');
        }
    }
}

// 탐험 진행 턴 표시 갱신 (state.exploreTurn 기반)
//   백엔드 흐름:
//     turn=25 → 중간 보스 발생
//     turn>=50 → 최종 보스 발생
//   따라서 진행률은 turn / 50 으로 계산
function refreshExploreTurn() {
    const turn = state.exploreTurn || 0;
    const tv = document.getElementById('explore-turn-value');
    const fill = document.getElementById('explore-turn-fill');
    const hint = document.getElementById('explore-turn-hint');
    if (!tv || !fill) return;

    tv.textContent = turn;
    const pct = Math.min(100, (turn / 50) * 100);
    fill.style.width = pct + '%';

    if (hint) {
        if (turn >= 50) {
            hint.textContent = '⚠ 최종 보스 출현!';
            hint.style.color = 'var(--accent-warn)';
        } else if (turn >= 25) {
            hint.textContent = `최종 보스까지 ${50 - turn}턴`;
            hint.style.color = '';
        } else {
            const toMid = 25 - turn;
            hint.textContent = `중간 보스까지 ${toMid}턴 / 최종 보스까지 ${50 - turn}턴`;
            hint.style.color = '';
        }
    }
}

// 평시 모드로 UI 전환 — 탐험 보이기 + 배틀/액션 패널 숨김
function setExploreMode() {
    document.getElementById('explore-mode').style.display = 'block';
    document.getElementById('battle-mode').style.display = 'none';
    document.getElementById('actions-panel').style.display = 'none';
    refreshExploreTurn();
}