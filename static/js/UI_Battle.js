/* ═══════════════════════════════════════════════════════════
   ui-battle.js — 중앙 배틀 UI 갱신
   - refreshBattle: BattleSession._state() 응답 → UI 갱신
     - 좌측 게이지도 동기화 (HP/MP)
     - 적/플레이어 슬롯, HP/MP 미니바
     - 펜타곤 차트 (적 vs 플레이어 능력치)
     - 스킬 메뉴, 아이템 메뉴
     - 차례 인디케이터 + 액션 패널 표시
   - showPlayerTurn / showEnemyTurn: ATB 차례 시각화
   ═══════════════════════════════════════════════════════════ */

function refreshBattle(bs) {
    state.battleState = bs;
    state.inBattle = !bs.done && (bs.player_hp > 0);

    // ── 모드 전환 ──
    document.getElementById('explore-mode').style.display = state.inBattle ? 'none' : 'block';
    document.getElementById('battle-mode').style.display = state.inBattle ? 'block' : 'none';
    document.getElementById('actions-panel').style.display = state.inBattle ? 'block' : 'none';

    if (!state.inBattle) {
        ['btn-attack','btn-skill','btn-item','btn-escape'].forEach(id => {
            document.getElementById(id).disabled = true;
        });
        return;
    }

    // ── 보스전이면 escape 비활성 + 시각 표시 ──
    ['btn-attack','btn-skill','btn-item','btn-escape'].forEach(id => {
        document.getElementById(id).disabled = false;
    });
    if (state.battleState && state.battleState.is_boss) {
        const escBtn = document.getElementById('btn-escape');
        escBtn.disabled = true;
        escBtn.textContent = '✖ NO ESCAPE';
        escBtn.title = '보스전에서는 도망칠 수 없습니다';
        escBtn.classList.add('escape-blocked');
    } else {
        const escBtn = document.getElementById('btn-escape');
        escBtn.textContent = 'ESCAPE';
        escBtn.title = '';
        escBtn.classList.remove('escape-blocked');
    }

    // ── 핵심: 좌측 게이지도 전투 중 HP/MP 변동 반영 ──
    if (state.player) {
        state.player.hp = bs.player_hp;
        state.player.mp = bs.player_mp;
        if (bs.items) state.player.items = bs.items;
        document.getElementById('hp-cur').textContent = Math.round(bs.player_hp);
        document.getElementById('mp-cur').textContent = Math.round(bs.player_mp);
        document.getElementById('hp-fill').style.height = (bs.player_hp/bs.player_maxhp*100) + '%';
        document.getElementById('mp-fill').style.height = (bs.player_mp/bs.player_maxmp*100) + '%';
    }

    document.getElementById('turn-counter').textContent = `TURN ${bs.turn}`;
    document.getElementById('field-name').textContent = bs.is_boss ? 'BOSS ARENA' : 'FIELD';

    // ── 배틀 배경 단계별 클래스 토글 ──
    // 우선순위: is_boss > 게임 진행 turn (state.exploreTurn 기반)
    //   midboss   →  battle-bg-midboss   (turn ~25)
    //   finalboss →  battle-bg-finalboss (turn ~50)
    //   일반 + early →  battle-bg-normal-early
    //   일반 + late  →  battle-bg-normal-late (turn 25~)
    refreshBattleBackground(bs);

    // ── 플레이어 슬롯 ──
    const p = state.player;
    document.getElementById('player-combatant-art').textContent = JOB_ICONS[p.job] || '?';
    document.getElementById('player-combatant-name').textContent = p.name;
    document.getElementById('player-combatant-meta').textContent = `LV ${p.lv} ${p.job}`;
    document.getElementById('player-cb-hp').style.width = (bs.player_hp/bs.player_maxhp*100) + '%';
    document.getElementById('player-cb-hp-text').textContent = `${Math.round(bs.player_hp)}/${bs.player_maxhp}`;
    document.getElementById('player-cb-mp').style.width = (bs.player_mp/bs.player_maxmp*100) + '%';
    document.getElementById('player-cb-mp-text').textContent = `${Math.round(bs.player_mp)}/${bs.player_maxmp}`;

    // ── 적 슬롯 (다대일 지원) ──
    // bs.enemies는 항상 배열 (1대1이면 길이 1, 다대일이면 2~3)
    // 각 슬롯에 대응되는 ID 매핑:
    //   slot 0 → enemy-slot-1, enemy-art, enemy-name, enemy-meta, enemy-cb-hp(-text)
    //   slot 1 → enemy-slot-2, enemy-art-2, enemy-name-2, enemy-meta-2, enemy-cb-hp-2(-text-2)
    //   slot 2 → enemy-slot-3, ... -3
    const enemiesArr = bs.enemies || [];
    const enemyIdSuffix = (i) => i === 0 ? '' : `-${i + 1}`;
    const slotIdSuffix  = (i) => i === 0 ? '-1' : `-${i + 1}`;

    // 모든 슬롯 한 번씩 처리 (총 3개)
    for (let i = 0; i < 3; i++) {
        const en = enemiesArr[i];
        const slotEl = document.getElementById(`enemy-slot${slotIdSuffix(i)}`);
        if (!slotEl) continue;

        if (!en) {
            // 이 슬롯 사용 안 함 → 숨김
            slotEl.style.display = 'none';
            continue;
        }

        // 슬롯 표시
        slotEl.style.display = '';

        // 죽은 적은 흐리게 표시
        slotEl.style.opacity = en.alive ? '1' : '0.3';
        slotEl.style.filter  = en.alive ? '' : 'grayscale(100%)';

        // 아이콘
        const artEl = document.getElementById(`enemy-art${enemyIdSuffix(i)}`);
        if (artEl) artEl.textContent = ENEMY_ICONS[en.name] || '👹';

        // 이름/레벨
        const nameEl = document.getElementById(`enemy-name${enemyIdSuffix(i)}`);
        const metaEl = document.getElementById(`enemy-meta${enemyIdSuffix(i)}`);
        if (nameEl) nameEl.textContent = en.name + (en.alive ? '' : ' ✖');
        if (metaEl) metaEl.textContent = `LV ${en.lv} ${en.difficulty_label ? '['+en.difficulty_label+']' : ''}`;

        // HP 바
        const hpEl     = document.getElementById(`enemy-cb-hp${enemyIdSuffix(i)}`);
        const hpTextEl = document.getElementById(`enemy-cb-hp-text${enemyIdSuffix(i)}`);
        if (hpEl)     hpEl.style.width = (en.hp / en.maxhp * 100) + '%';
        if (hpTextEl) hpTextEl.textContent = `${Math.round(en.hp)}/${en.maxhp}`;

        // 타깃 표시 (현재 선택된 슬롯에만)
        const targetTag = i === 0
            ? document.getElementById('target-tag')
            : slotEl.querySelector('.target-tag');
        if (targetTag) {
            targetTag.style.display = (i === bs.target_idx && en.alive) ? 'block' : 'none';
        }

        // ── 슬롯 클릭으로 타깃 변경 ──
        // 죽은 적 / 단일전이면 클릭 비활성
        if (enemiesArr.length > 1 && en.alive) {
            slotEl.style.cursor = 'pointer';
            slotEl.onclick = () => selectTarget(i);
        } else {
            slotEl.style.cursor = '';
            slotEl.onclick = null;
        }
    }

    // ── 1대1 호환 — 기존 single enemy 필드 (target-tag 등) ──
    // 위 루프에서 이미 다 처리. 추가 로직 불필요.

    // ── 메시지 → 배틀 로그 ──
    if (bs.messages && bs.messages.length) {
        bs.messages.forEach(m => {
            let cls = '';
            if (/크리|CRIT/i.test(m)) cls = 'crit';
            else if (/회피|MISS/i.test(m)) cls = 'system';
            else if (/사용|스킬/i.test(m)) cls = 'skill';
            else if (/회복/i.test(m)) cls = 'heal';
            else if (/데미지|피해/i.test(m)) cls = 'dmg';
            logLine(m, cls);
        });
    }

    // ── 스킬 메뉴 ──
    if (bs.skills) {
        const sl = document.getElementById('skill-list');
        sl.innerHTML = '';
        bs.skills.forEach(sk => {
            const cell = document.createElement('div');
            cell.className = 'submenu-item';
            cell.innerHTML = `${sk.name}<span class="cost">MP${sk.mp}</span>`;
            const canUse = bs.player_mp >= sk.mp;
            if (!canUse) cell.style.opacity = 0.4;
            cell.onclick = canUse ? () => useSkill(sk.name) : null;
            sl.appendChild(cell);
        });
        if (!bs.skills.length) {
            sl.innerHTML = '<div style="color:var(--text-muted); padding:8px; grid-column:1/-1;">학습한 스킬 없음</div>';
        }
    }

    // ── 아이템 메뉴 (양쪽 형식 지원) ──
    // 백엔드 형식 두 가지:
    //  - 객체 배열: [{name:'HP_S_potion', count:2}, ...]  (전투 _state)
    //  - 문자열 배열: ['HP_S_potion', 'HP_S_potion', ...]  (player_dict)
    const il = document.getElementById('item-list');
    il.innerHTML = '';
    const battleItems = bs.items || [];
    let itemEntries = [];
    if (battleItems.length > 0) {
        if (typeof battleItems[0] === 'object' && battleItems[0].name !== undefined) {
            itemEntries = battleItems.map(it => [it.name, it.count]);
        } else {
            const counts = {};
            battleItems.forEach(it => counts[it] = (counts[it]||0)+1);
            itemEntries = Object.entries(counts);
        }
    }
    if (itemEntries.length === 0) {
        il.innerHTML = '<div style="color:var(--text-muted); padding:8px; grid-column:1/-1;">아이템 없음</div>';
    } else {
        itemEntries.forEach(([name, n]) => {
            const cell = document.createElement('div');
            cell.className = 'submenu-item';
            cell.innerHTML = `${name}<span class="cost">×${n}</span>`;
            cell.onclick = () => useItem(name);
            il.appendChild(cell);
        });
    }

    // ── ATB 시뮬 (시각적 효과) ──
    // 좌측 패널의 ATB 바는 제거됨. 안전하게 null 체크 후 처리.
    const atbFill = document.getElementById('atb-fill');
    const atbCur  = document.getElementById('atb-cur');
    if (atbFill) {
        atbFill.style.height = '100%';
        atbFill.classList.add('full');
    }
    if (atbCur) atbCur.textContent = '100';

    // ── 펜타곤 차트 ──
    // 다대일이면 살아있는 적들의 평균 능력치 사용 (전체 위협도 표시)
    const aliveEnemies = enemiesArr.filter(e => e.alive);
    if (aliveEnemies.length > 0) {
        const avg = (key) => aliveEnemies.reduce((s, e) => s + (e[key] || 0), 0) / aliveEnemies.length;
        const avgStg = avg('stg'), avgArm = avg('arm'),
              avgSpd = avg('spd'), avgLuc = avg('luc'), avgSp = avg('sp');

        // 다대일 보정: 적 수만큼 위협도 증가 (평균 × √n)
        const threatMul = Math.sqrt(aliveEnemies.length);
        const norm = v => Math.min(1, Math.max(0.1, v / 50));
        const enemyVec = [
            norm(avgStg * threatMul), norm(avgArm * threatMul),
            norm(avgSpd), 0.5, norm((avgLuc + avgSp) * threatMul)
        ];
        const playerVec = [norm(p.stg), norm(p.arm), norm(p.spd),
                           0.5, norm(p.luc + p.sp)];
        updatePentagon(playerVec, enemyVec);

        // 라벨: 다대일이면 N마리 표시
        const firstAlive = aliveEnemies[0];
        const baseLabel = firstAlive.difficulty_label
                          ? '['+firstAlive.difficulty_label.toUpperCase()+']'
                          : '[STABLE]';
        const multiTag = enemiesArr.length > 1 ? ` × ${aliveEnemies.length}` : '';
        document.getElementById('balance-label').textContent = baseLabel + multiTag;
    }

    // ── 행동 버튼 활성 + 차례 시각화 ──
    showPlayerTurn();
}

// ATB 시각화: 플레이어 차례 (행동 가능 상태)
function showPlayerTurn() {
    ['btn-attack','btn-skill','btn-item','btn-escape'].forEach(id => {
        document.getElementById(id).disabled = false;
    });
    if (state.battleState && state.battleState.is_boss) {
        document.getElementById('btn-escape').disabled = true;
    }
    const ind = document.getElementById('turn-indicator');
    ind.className = 'turn-indicator player-turn';
    ind.textContent = '▶ YOUR TURN';
    document.getElementById('action-bar').classList.add('your-turn');
    document.querySelector('.combatant.player')?.classList.add('acting');
    document.querySelector('.combatant.enemy')?.classList.remove('acting');
}

// ATB 시각화: 적 차례 (행동 불가)
function showEnemyTurn() {
    ['btn-attack','btn-skill','btn-item','btn-escape'].forEach(id => {
        document.getElementById(id).disabled = true;
    });
    const ind = document.getElementById('turn-indicator');
    ind.className = 'turn-indicator enemy-turn';
    ind.textContent = '◀ ENEMY TURN';
    document.getElementById('action-bar').classList.remove('your-turn');
    document.querySelector('.combatant.player')?.classList.remove('acting');
    document.querySelector('.combatant.enemy')?.classList.add('acting');
    const atbFill = document.getElementById('atb-fill');
    const atbCur  = document.getElementById('atb-cur');
    if (atbFill) {
        atbFill.style.height = '20%';
        atbFill.classList.remove('full');
    }
    if (atbCur) atbCur.textContent = '20';
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