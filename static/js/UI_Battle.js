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

/** 원소 부착 → 이름 색상 class 부여 */

/* ───────────────────────────────────────────────────────────
   ※ 다음 함수들은 battle/ 폴더로 분리됨 (index.html에서 먼저 로드):
     BattleStatusUI.js — applyElementNameClass, statusEmojiList,
                         renderNameWithStatus, refreshLeftStatsBattle,
                         refreshPlayerStatusList
     BattleTurn.js     — showPlayerTurn, showEnemyTurn, selectTarget,
                         refreshBattleTargetTags, refreshBattleBackground
     BattleEffects.js  — _triggerSpriteStates, _scheduleSetState,
                         _updateBattleSprite
   이 파일은 refreshBattle 오케스트레이터만 담당.
   ─────────────────────────────────────────────────────────── */

function refreshBattle(bs) {
    state.battleState = bs;
    state.inBattle = !bs.done && (bs.player_hp > 0);

    // 모드 표시 + 버튼 상태 (전투 아님이면 false 반환 → 조기 종료)
    if (!updateBattleModeVisibility(bs)) return;

    syncPlayerBattleState(bs);
    refreshLeftStatsBattle(bs);
    refreshPlayerStatusList(bs);
    refreshBattleBackground(bs);

    renderBattleStage(bs);

    // 캐릭터 스프라이트 상태
    if (bs.messages) {
        _triggerSpriteStates(bs);
    }

    // 배틀 로그
    if (bs.messages && bs.messages.length) {
        bs.messages.forEach(m => {
            let cls = '';
            if (/크리티컬|CRIT/i.test(m)) cls = 'crit';
            else if (/회피|MISS/i.test(m)) cls = 'system';
            else if (/사용|스킬/i.test(m)) cls = 'skill';
            else if (/회복/i.test(m)) cls = 'heal';
            else if (/데미지|피해/i.test(m)) cls = 'dmg';
            logLine(m, cls);
        });
    }

    renderBattleSkillMenu(bs);
    renderBattleItemMenu(bs);
    renderBattleSidePanel(bs);

    // 행동 버튼 활성 + 차례 시각화
    showPlayerTurn();
}


// ═══════════════════════════════════════════════════════════
// refreshBattle 내부 블록 → 함수 추출 (동작 동일, 호출 순서 보존)
// HTML/CSS/id/class 변경 없음. JS 내부 함수화만.
// ═══════════════════════════════════════════════════════════

// 전투 모드 표시 토글 + 행동 버튼/도망 버튼 상태
function updateBattleModeVisibility(bs) {
    const mapModeEl = document.getElementById('map-mode');
    const invPanel = document.getElementById('player-inventory-panel');
    if (invPanel) invPanel.style.display = state.inBattle ? 'none' : '';
    if (mapModeEl) mapModeEl.style.display = 'none';
    const exploreModeEl = document.getElementById('explore-mode');
    if (exploreModeEl) exploreModeEl.style.display = 'none';
    const battleModeEl = document.getElementById('battle-mode');
    if (battleModeEl) battleModeEl.style.display = state.inBattle ? 'block' : 'none';
    const actionsPanelEl = document.getElementById('actions-panel');
    if (actionsPanelEl) actionsPanelEl.style.display = state.inBattle ? 'block' : 'none';
 
    if (!state.inBattle) {
        ['btn-attack','btn-skill','btn-item','btn-escape'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.disabled = true;
        });
        return false;
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
    return true;
}

// 좌측 패널 HP/MP/turn 동기화
function syncPlayerBattleState(bs) {
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
}

// 플레이어 슬롯 + 적 슬롯(1~3) + HP/MP/ATB 바 + 타겟 + 턴 시각화
// (원본 단일 for 루프 구조 보존 — 슬롯/바/타겟이 한 패스에서 처리됨)
// ── 플레이어 전투 슬롯 (이름/이미지/HP/MP/ATB) ──
function renderPlayerCombatant(bs) {
    const p = state.player;
    document.getElementById('player-combatant-art').textContent = JOB_ICONS[p.job] || '?';
    renderNameWithStatus(document.getElementById('player-combatant-name'), {
        name: p.name,
        element_aura: bs.player_element_aura || p.element_aura || '',
        status_effects: bs.player_status_effects || [],
        buffs: bs.player_buffs || [],
        debuffs: bs.player_debuffs || []
    });
    document.getElementById('player-combatant-meta').textContent = `LV ${p.lv} ${p.job}`;
    document.getElementById('player-cb-hp').style.width = (bs.player_hp/bs.player_maxhp*100) + '%';
    document.getElementById('player-cb-hp-text').textContent = `${Math.round(bs.player_hp)}/${bs.player_maxhp}`;
    document.getElementById('player-cb-mp').style.width = (bs.player_mp/bs.player_maxmp*100) + '%';
    document.getElementById('player-cb-mp-text').textContent = `${Math.round(bs.player_mp)}/${bs.player_maxmp}`;

    // 플레이어 ATB 바
    const playerAtb = bs.player_atb !== undefined ? bs.player_atb : 0;
    const playerAtbPct = Math.min(100, Math.max(0, playerAtb));
    const playerAtbEl = document.getElementById('player-cb-atb');
    const playerAtbTextEl = document.getElementById('player-cb-atb-text');
    if (playerAtbEl) {
        playerAtbEl.style.width = playerAtbPct + '%';
        if (playerAtbPct >= 100) {
            playerAtbEl.classList.add('full');
        } else {
            playerAtbEl.classList.remove('full');
        }
    }
    if (playerAtbTextEl) {
        playerAtbTextEl.textContent = Math.round(playerAtb);
    }
}

// ── 적 슬롯 (다대일 지원): 슬롯 show/hide, 이름/이미지/HP/ATB 바, 타겟 태그, 슬롯 클릭 ──
// 슬롯↔ID 매핑: slot 0 → enemy-slot-1/enemy-name/enemy-cb-hp(접미사 없음)
//              slot 1 → -2,  slot 2 → -3
function renderEnemySlots(bs) {
    const enemiesArr = bs.enemies || [];
    const enemyIdSuffix = (i) => i === 0 ? '' : `-${i + 1}`;
    const slotIdSuffix  = (i) => i === 0 ? '-1' : `-${i + 1}`;

    for (let i = 0; i < 3; i++) {
        const en = enemiesArr[i];
        const slotEl = document.getElementById(`enemy-slot${slotIdSuffix(i)}`);
        if (!slotEl) continue;

        if (!en) {
            slotEl.style.display = 'none';
            continue;
        }

        slotEl.style.display = '';
        slotEl.style.opacity = en.alive ? '1' : '0.3';
        slotEl.style.filter  = en.alive ? '' : 'grayscale(100%)';

        const artEl = document.getElementById(`enemy-art${enemyIdSuffix(i)}`);
        if (artEl) artEl.textContent = ENEMY_ICONS[en.name] || '👹';

        const stateKey = en.alive ? 'idle' : 'dead';
        _updateBattleSprite('enemy_battle', i, en.name, stateKey);

        const nameEl = document.getElementById(`enemy-name${enemyIdSuffix(i)}`);
        const metaEl = document.getElementById(`enemy-meta${enemyIdSuffix(i)}`);
        if (nameEl) {
            renderNameWithStatus(nameEl, {
                ...en,
                name: en.name + (en.alive ? '' : ' ✖'),
                element_aura: en.element_aura || '',
                status_effects: en.status_effects || [],
                buffs: en.buffs || [],
                debuffs: en.debuffs || []
            });
        }
        if (metaEl) metaEl.textContent = `LV ${en.lv ?? '--'} ${en.difficulty_label ? '[' + en.difficulty_label + ']' : ''}`;

        // HP 바
        const hpEl     = document.getElementById(`enemy-cb-hp${enemyIdSuffix(i)}`);
        const hpTextEl = document.getElementById(`enemy-cb-hp-text${enemyIdSuffix(i)}`);
        if (hpEl)     hpEl.style.width = (en.hp / en.maxhp * 100) + '%';
        if (hpTextEl) hpTextEl.textContent = `${Math.round(en.hp)}/${en.maxhp}`;

        // ATB 바
        const enemyAtb = en.atb !== undefined ? en.atb : 0;
        const enemyAtbPct = Math.min(100, Math.max(0, enemyAtb));
        const atbEl     = document.getElementById(`enemy-cb-atb${enemyIdSuffix(i)}`);
        const atbTextEl = document.getElementById(`enemy-cb-atb-text${enemyIdSuffix(i)}`);
        if (atbEl) {
            atbEl.style.width = enemyAtbPct + '%';
            if (enemyAtbPct >= 100 && en.alive) {
                atbEl.classList.add('full');
            } else {
                atbEl.classList.remove('full');
            }
        }
        if (atbTextEl) {
            atbTextEl.textContent = en.alive ? Math.round(enemyAtb) : '--';
        }

        // 타깃 태그
        const targetTag = i === 0
            ? document.getElementById('target-tag')
            : slotEl.querySelector('.target-tag');
        if (targetTag) {
            targetTag.style.display = (i === bs.target_idx && en.alive) ? 'block' : 'none';
        }

        // 슬롯 클릭으로 타깃 변경 (다대일 + 살아있는 적만)
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

// ── 전투 무대 렌더 오케스트레이터 ──
function renderBattleStage(bs) {
    renderPlayerCombatant(bs);
    renderEnemySlots(bs);
    renderBattleTurnState(bs);
    return state.player;
}


// 스킬 메뉴 렌더
function renderBattleSkillMenu(bs) {
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
        cell.innerHTML = `${name}<span class="cost">×${n}</span>`;
        cell.onclick = () => useItem(name);
        il.appendChild(cell);
    });
}
}

// 좌측 ATB 바 + 펜타곤 차트
function renderBattleSidePanel(bs) {
    const p = state.player;
    const enemiesArr = bs.enemies || [];
    const atbFill = document.getElementById('atb-fill');
    const atbCur  = document.getElementById('atb-cur');
    const leftAtbVal = bs.player_atb !== undefined ? bs.player_atb : 0;
    const leftAtbPct = Math.min(100, Math.max(0, leftAtbVal));
    if (atbFill) {
        atbFill.style.height = leftAtbPct + '%';
        if (leftAtbPct >= 100) {
            atbFill.classList.add('full');
        } else {
            atbFill.classList.remove('full');
        }
    }
    if (atbCur) atbCur.textContent = Math.round(leftAtbVal);
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
}