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

    // 스탯 카드는 제거됨 (좌측 패널 능력치로 통합)

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
    refreshExploreBackground();   // 단계별 배경 클래스 토글
}

// 탐험 진행 턴에 따라 배경 클래스 자동 전환
//   0~22:  early-normal       (밝은 풀밭 등)
//   23~24: pre-midboss        (긴장감, 어두워짐)
//   25~47: late-normal        (후반 어두운 톤)
//   48~49: pre-finalboss      (붉은 톤, 임박)
function refreshExploreBackground() {
    const exp = document.getElementById('explore-mode');
    if (!exp) return;
    const turn = state.exploreTurn || 0;
    // 모든 배경 클래스 제거 후 현재 단계만 추가
    exp.classList.remove('explore-bg-early-normal',
                         'explore-bg-pre-midboss',
                         'explore-bg-late-normal',
                         'explore-bg-pre-finalboss');
    if (turn >= 48 && turn < 50) exp.classList.add('explore-bg-pre-finalboss');
    else if (turn >= 25)         exp.classList.add('explore-bg-late-normal');
    else if (turn >= 23)         exp.classList.add('explore-bg-pre-midboss');
    else                          exp.classList.add('explore-bg-early-normal');
}