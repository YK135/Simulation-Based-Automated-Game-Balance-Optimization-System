/* ═══════════════════════════════════════════════════════════
   battle/BattleTurn.js — 턴 표시 / 타겟 선택 / 배경 전환
   ═══════════════════════════════════════════════════════════ */

function showPlayerTurn() {
    // 버튼 활성화
    ['btn-attack','btn-skill','btn-item','btn-escape'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = false;
    });
    // 보스전이면 escape 비활성 유지
    if (state.battleState && state.battleState.is_boss) {
        const escBtn = document.getElementById('btn-escape');
        if (escBtn) escBtn.disabled = true;
    }

    // ★ processing 클래스 제거 — 시각적 복귀
    const actionBar = document.getElementById('action-bar');
    if (actionBar) {
        actionBar.classList.add('your-turn');
        actionBar.classList.remove('processing');
    }
    const actionsPanel = document.getElementById('actions-panel');
    if (actionsPanel) {
        actionsPanel.classList.remove('processing');
    }

    // 차례 인디케이터
    const ind = document.getElementById('turn-indicator');
    if (ind) {
        ind.className = 'turn-indicator player-turn';
        ind.textContent = '▶ YOUR TURN';
    }

    // 배틀필드 acting 효과
    document.querySelector('.combatant.player')?.classList.add('acting');
    document.querySelector('.combatant.enemy')?.classList.remove('acting');
}

// ATB 시각화: 적 차례 (행동 불가)

function showEnemyTurn() {
    // 버튼 비활성화 (동작 차단)
    ['btn-attack','btn-skill','btn-item','btn-escape'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = true;
    });

    // 스킬/아이템 메뉴 닫기
    document.getElementById('skill-menu')?.classList.remove('active');
    document.getElementById('item-menu')?.classList.remove('active');

    // ★ 액션 패널 전체에 processing 클래스 — 시각적 비활성화
    const actionBar = document.getElementById('action-bar');
    if (actionBar) {
        actionBar.classList.remove('your-turn');
        actionBar.classList.add('processing');
    }
    const actionsPanel = document.getElementById('actions-panel');
    if (actionsPanel) {
        actionsPanel.classList.add('processing');
    }

    // 차례 인디케이터
    const ind = document.getElementById('turn-indicator');
    if (ind) {
        ind.className = 'turn-indicator enemy-turn';
        ind.textContent = '◀ ENEMY TURN';
    }

    // 배틀필드 acting 효과
    document.querySelector('.combatant.player')?.classList.remove('acting');
    document.querySelector('.combatant.enemy')?.classList.add('acting');
}

// 다대일 — 슬롯 클릭으로 타깃 변경
//   서버에 별도 호출 없이 state만 변경. 다음 attack/skill에서 인덱스 함께 전송.
//   (서버는 attack:N 형식으로 받음)

function selectTarget(slotIdx) {
    if (!state.battleState) return;
    if (state.battleState.enemies && state.battleState.enemies.length <= 1) return;
    state.battleState.target_idx = slotIdx;
    // UI만 갱신 (서버 호출 없음)
    refreshBattleTargetTags(slotIdx);
    toast(`타깃: 슬롯 ${slotIdx + 1}`);
}

// 타깃 태그만 갱신 (전체 refreshBattle 호출 없이 가벼운 변경)

function refreshBattleTargetTags(targetIdx) {
    for (let i = 0; i < 3; i++) {
        const slotEl = document.getElementById(`enemy-slot-${i + 1}`);
        if (!slotEl) continue;
        const tag = i === 0
            ? document.getElementById('target-tag')
            : slotEl.querySelector('.target-tag');
        if (!tag) continue;
        const en = state.battleState.enemies && state.battleState.enemies[i];
        tag.style.display = (i === targetIdx && en && en.alive) ? 'block' : 'none';
    }
}

// 배틀 단계별 배경 클래스 토글
//   battle-bg-midboss     →  bs.is_boss && state.exploreTurn ~25 (중간 보스)
//   battle-bg-finalboss   →  bs.is_boss && state.exploreTurn ~50 (최종 보스)
//   battle-bg-normal-early →  일반전 + turn < 25
//   battle-bg-normal-late  →  일반전 + turn >= 25

function refreshBattleBackground(bs) {
    const stage = document.querySelector('.battle-stage');
    if (!stage) return;
    stage.classList.remove('battle-bg-normal-early',
                            'battle-bg-midboss',
                            'battle-bg-normal-late',
                            'battle-bg-finalboss');
    const turn = state.exploreTurn || 0;
    if (bs.is_boss) {
        // 보스전: turn 위치로 중간 vs 최종 판단
        // 중간 보스는 turn==25 시점에 발생, 최종 보스는 turn>=50
        if (turn >= 50) stage.classList.add('battle-bg-finalboss');
        else            stage.classList.add('battle-bg-midboss');
    } else {
        if (turn >= 25) stage.classList.add('battle-bg-normal-late');
        else            stage.classList.add('battle-bg-normal-early');
    }
}

// ── 전투 중 좌측 stat-grid를 실효 스탯으로 다시 렌더 ──
//   bs.player_effective_stg 등이 있으면 사용, 없으면 원본으로 폴백.
//   원본과 다르면 .changed 클래스 (노란색 강조).

// ═══════════════════════════════════════════════════════════
// UI_Battle.js에서 이동: 타겟 태그 / 슬롯 클릭 바인딩 / 턴 시각화
//   ※ 기존 refreshBattleTargetTags(targetIdx, 숫자)와 다른 함수:
//     renderBattleTargetTags(bs, 상태객체) — 이름/시그니처 모두 구분됨
// ═══════════════════════════════════════════════════════════

// ── 타깃 태그: 현재 target_idx 슬롯에만 TARGET 표시 ──
function renderBattleTargetTags(bs) {
    const enemiesArr = bs.enemies || [];
    const slotIdSuffix = (i) => i === 0 ? '-1' : `-${i + 1}`;
    for (let i = 0; i < 3; i++) {
        const en = enemiesArr[i];
        const slotEl = document.getElementById(`enemy-slot${slotIdSuffix(i)}`);
        if (!slotEl || !en) continue;
        const targetTag = i === 0
            ? document.getElementById('target-tag')
            : slotEl.querySelector('.target-tag');
        if (targetTag) {
            targetTag.style.display = (i === bs.target_idx && en.alive) ? 'block' : 'none';
        }
    }
}

// ── 적 슬롯 클릭 바인딩 (다대일 + 살아있는 적만 타깃 변경 가능) ──
function bindEnemyTargetClicks(bs) {
    const enemiesArr = bs.enemies || [];
    const slotIdSuffix = (i) => i === 0 ? '-1' : `-${i + 1}`;
    for (let i = 0; i < 3; i++) {
        const en = enemiesArr[i];
        const slotEl = document.getElementById(`enemy-slot${slotIdSuffix(i)}`);
        if (!slotEl || !en) continue;
        if (enemiesArr.length > 1 && en.alive) {
            slotEl.style.cursor = 'pointer';
            slotEl.onclick = () => selectTarget(i);
        } else {
            slotEl.style.cursor = '';
            slotEl.onclick = null;
        }
    }
}

// ── 턴 시각화: next_actor 기반 행동권 표시 ──
function renderBattleTurnState(bs) {
    const nextActor = bs.next_actor;
    if (nextActor === 'player') {
        showPlayerTurn();
    } else if (nextActor === 'enemy') {
        showEnemyTurn();
    } else if (nextActor === 'done') {
        // 종료 — battleAction에서 처리
    } else {
        showEnemyTurn();
    }
}

// updateBattleTurnVisual: renderBattleTurnState 별칭 (호환)
function updateBattleTurnVisual(bs) {
    renderBattleTurnState(bs);
}