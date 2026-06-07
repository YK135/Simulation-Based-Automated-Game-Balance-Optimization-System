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
        return;
    }

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

    // ── 좌측 stat-grid를 실효 스탯(effective_*)으로 갱신 ──
    // 평상시(탐험 모드)에는 ui-player.js가 원본 스탯으로 렌더링.
    // 전투 중에는 여기서 effective_* 로 덮어써서 버프/디버프 영향 즉시 표시.
    refreshLeftStatsBattle(bs);

    // 좌측 버프/디버프 영역
    refreshPlayerStatusList(bs);

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
    // 이모지 폴백 동기화 (이미지 없으면 이게 보임)
    const playerArtIconEl = document.getElementById('player-combatant-art');
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

    // ★ 플레이어 ATB 바 갱신
    const playerAtb = bs.player_atb !== undefined ? bs.player_atb : 0;
    const playerAtbPct = Math.min(100, Math.max(0, playerAtb));
    const playerAtbEl = document.getElementById('player-cb-atb');
    const playerAtbTextEl = document.getElementById('player-cb-atb-text');
    if (playerAtbEl) {
        playerAtbEl.style.width = playerAtbPct + '%';
        // 100% 도달 시 펄스 글로우
        if (playerAtbPct >= 100) {
            playerAtbEl.classList.add('full');
        } else {
            playerAtbEl.classList.remove('full');
        }
    }
    if (playerAtbTextEl) {
        playerAtbTextEl.textContent = Math.round(playerAtb);
    }
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

        // 아이콘 (이모지)
        const artEl = document.getElementById(`enemy-art${enemyIdSuffix(i)}`);
        if (artEl) artEl.textContent = ENEMY_ICONS[en.name] || '👹';

        // ★ 배틀필드 적 이미지 갱신 (몬스터 종류별)
        const stateKey = en.alive ? 'idle' : 'dead';
        _updateBattleSprite('enemy_battle', i, en.name, stateKey);

        // 이름/레벨
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

        // ★ ATB 바 갱신
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
        
        // ── ★ 큐 기반 ATB: next_actor만 보고 결정 ──
        // ATB는 추가 행동권 게이지 (행동 자체는 큐 순서대로).
        // next_actor가 player면 ATB와 무관하게 행동 가능.
        const nextActor = bs.next_actor;
        if (nextActor === 'player') {
            showPlayerTurn();
        } else if (nextActor === 'enemy') {
            showEnemyTurn();
        } else if (nextActor === 'done') {
            // 종료 — battleAction에서 처리
        } else {
            // 미정 — 안전하게 비활성화
            showEnemyTurn();
        }
    }

    // ── 1대1 호환 — 기존 single enemy 필드 (target-tag 등) ──
    // 위 루프에서 이미 다 처리. 추가 로직 불필요.

    // ── 캐릭터 상태(이미지) 자동 갱신 ──
    // 메시지를 분석해 적절한 setCharState 호출.
    // 죽은 적은 dead로 영구, 살아있는데 데미지면 hurt → 0.4초 후 idle 복귀.
    if (bs.messages) {
        _triggerSpriteStates(bs);
    }

    // ── 메시지 → 배틀 로그 ──
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
    // 아이템 메뉴 — 포션/특수 분리 표시
// 백엔드 player.inventory가 있으면 새 구조, 없으면 옛 평탄 리스트
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

    // ── 좌측 패널 ATB 바 갱신 ──
    // bs.player_atb (0~100+) 값을 받아서 시각적으로 표시.
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

    // ── 행동 버튼 활성 + 차례 시각화 ──
    showPlayerTurn();
}