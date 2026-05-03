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

    // ── 플레이어 슬롯 ──
    const p = state.player;
    document.getElementById('player-combatant-art').textContent = JOB_ICONS[p.job] || '?';
    document.getElementById('player-combatant-name').textContent = p.name;
    document.getElementById('player-combatant-meta').textContent = `LV ${p.lv} ${p.job}`;
    document.getElementById('player-cb-hp').style.width = (bs.player_hp/bs.player_maxhp*100) + '%';
    document.getElementById('player-cb-hp-text').textContent = `${Math.round(bs.player_hp)}/${bs.player_maxhp}`;
    document.getElementById('player-cb-mp').style.width = (bs.player_mp/bs.player_maxmp*100) + '%';
    document.getElementById('player-cb-mp-text').textContent = `${Math.round(bs.player_mp)}/${bs.player_maxmp}`;

    // ── 적 슬롯 ──
    const ei = bs.enemy_info || {};
    document.getElementById('enemy-art').textContent = ENEMY_ICONS[ei.name || bs.enemy_name] || '👹';
    document.getElementById('enemy-name').textContent = ei.name || bs.enemy_name;
    document.getElementById('enemy-meta').textContent = `LV ${ei.lv || '?'} ${ei.difficulty_label ? '['+ei.difficulty_label+']' : ''}`;
    document.getElementById('enemy-cb-hp').style.width = (bs.enemy_hp/bs.enemy_maxhp*100) + '%';
    document.getElementById('enemy-cb-hp-text').textContent = `${Math.round(bs.enemy_hp)}/${bs.enemy_maxhp}`;
    document.getElementById('target-tag').style.display = 'block';

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
    document.getElementById('atb-fill').style.height = '100%';
    document.getElementById('atb-cur').textContent = '100';
    document.getElementById('atb-fill').classList.add('full');

    // ── 펜타곤 차트 ──
    if (ei.stg && ei.arm) {
        const norm = v => Math.min(1, Math.max(0.1, v / 50));
        const enemyVec = [norm(ei.stg), norm(ei.arm), norm(ei.spd),
                          0.5, norm((ei.luc||0) + (ei.sp||0))];
        const playerVec = [norm(p.stg), norm(p.arm), norm(p.spd),
                           0.5, norm(p.luc + p.sp)];
        updatePentagon(playerVec, enemyVec);
        document.getElementById('balance-label').textContent =
            ei.difficulty_label ? '['+ei.difficulty_label.toUpperCase()+']' : '[STABLE]';
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
    document.getElementById('atb-fill').style.height = '20%';
    document.getElementById('atb-cur').textContent = '20';
    document.getElementById('atb-fill').classList.remove('full');
}