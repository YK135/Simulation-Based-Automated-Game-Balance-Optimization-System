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
    const mapModeEl = document.getElementById('map-mode');
    if (mapModeEl) mapModeEl.style.display = 'none';
    document.getElementById('explore-mode').style.display = 'none';
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
    document.getElementById('player-combatant-name').textContent = p.name;
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
        if (nameEl) nameEl.textContent = en.name + (en.alive ? '' : ' ✖');
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
        const name = typeof it === 'object' ? it.name : it;
        counts[name] = (counts[name] || 0) + 1;
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

// ATB 시각화: 플레이어 차례 (행동 가능 상태)
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
function refreshLeftStatsBattle(bs) {
    const grid = document.getElementById('stat-grid');
    if (!grid || !state.player) return;
    const p = state.player;

    // (label, original, effective) 순서
    const rows = [
        ["STG",   p.stg,   bs.player_effective_stg ],
        ["SP",    p.sp,    p.sp                    ],  // SP는 effective 없음
        ["ARM",   p.arm,   bs.player_effective_arm ],
        ["SPARM", p.sparm, bs.player_effective_sparm],
        ["SPD",   p.spd,   bs.player_effective_spd ],
        ["LUC",   p.luc,   p.luc                   ],
    ];
    grid.innerHTML = rows.map(([label, orig, eff]) => {
        const useEff = (typeof eff === 'number') ? eff : orig;
        const changed = Math.abs(useEff - orig) > 0.5;
        return `<div class="stat-row${changed ? ' changed' : ''}">
                  <span>${label}</span>
                  <span class="v">${Math.round(useEff * 10) / 10}</span>
                </div>`;
    }).join('');
}

// ── 좌측 버프/디버프 칩 렌더 ──
//   bs.player_buffs / bs.player_debuffs (각각 [{stat, amount, turns, name}, ...])
function refreshPlayerStatusList(bs) {
    const buffsEl   = document.getElementById('player-buffs');
    const debuffsEl = document.getElementById('player-debuffs');
    if (!buffsEl || !debuffsEl) return;

    const STAT_KOR = {
        stg:'공격', arm:'방어', sparm:'마방', spd:'속도',
        mp_efficiency:'마나효율'
    };

    const renderChip = (s, kind) => {
        const stat = STAT_KOR[s.stat] || s.stat;
        const amt  = Math.round((s.amount || 0) * 100);
        const sign = kind === 'buff' ? '+' : '−';
        return `<span class="status-chip ${kind}" title="${s.name || ''}">
                  ${stat} ${sign}${amt}%<span class="turns">${s.turns}T</span>
                </span>`;
    };

    const buffs   = bs.player_buffs   || [];
    const debuffs = bs.player_debuffs || [];
    buffsEl.innerHTML   = buffs.map(b => renderChip(b, 'buff')).join('');
    debuffsEl.innerHTML = debuffs.map(d => renderChip(d, 'debuff')).join('');
}

// ═══════════════════════════════════════════════════════════
// 메시지 → 캐릭터 상태(이미지) 매핑
// ─────────────────────────────────────────────────────────
// 서버 응답의 messages를 보고 적절한 setCharState 호출.
// 한 응답에 플레이어 행동 + 적 행동이 섞여있으므로 시간차 적용:
//   - 플레이어 행동: 즉시 (0ms)
//   - 데미지 효과(hurt): 200ms 후 (공격 모션 보여준 뒤 적이 흠칫)
//   - 적 행동: 600ms 후 (플레이어 행동 다 끝나고)
// ═══════════════════════════════════════════════════════════
function _triggerSpriteStates(bs) {
    if (!bs || !bs.enemies) return;
    const messages = bs.messages || [];

    // 적 이름 목록 (슬롯 인덱스 매핑용)
    const enemyNameToSlot = {};
    bs.enemies.forEach((en, i) => {
        if (en && en.name) enemyNameToSlot[en.name] = i;
    });

    // 플레이어 이름
    const playerName = state.player ? state.player.name : '';

    // 메시지 분석
    let playerActed = false;
    let playerSkillUsed = false;
    let enemyActed = false;
    const damagedEnemies = new Set();   // 데미지 입은 적 슬롯 인덱스 집합
    const deadEnemies = new Set();      // 사망한 적 슬롯 인덱스
    let playerHurt = false;
    let playerDead = false;

    for (const m of messages) {
        // 플레이어 사망
        if (m.includes('쓰러졌다')) {
            playerDead = true;
            continue;
        }

        // 적 사망 ("XXX을(를) 처치했다" / "모든 적을 처치했다")
        if (m.includes('처치했다')) {
            // 어떤 적이 죽었는지 명확하지 않으면 (모든 적 처치 시) hp<=0인 모든 적
            bs.enemies.forEach((en, i) => {
                if (en && !en.alive) deadEnemies.add(i);
            });
            continue;
        }

        // 적 행동: "XXX → " 패턴 (XXX는 적 이름)
        let foundEnemyAction = false;
        for (const [name, slotIdx] of Object.entries(enemyNameToSlot)) {
            if (m.includes(name + ' →') || m.includes(name + ' → ')) {
                enemyActed = true;
                // 적이 공격하면 플레이어가 hurt (단, 회피/실드 흡수 메시지는 제외)
                if (!m.includes('회피') && /\\d+ 데미지/.test(m)) {
                    playerHurt = true;
                }
                // 적 슬롯 자체는 attack 상태로
                _scheduleSetState(`enemy_battle:${slotIdx}`, 'attack', 600);
                foundEnemyAction = true;
                break;
            }
        }
        if (foundEnemyAction) continue;

        // 플레이어 스킬 사용: "XXX 사용 →" 또는 "사용!"
        if (/[가-힣\\w]+ 사용/.test(m) && !m.includes('아이템')) {
            playerSkillUsed = true;
            playerActed = true;
            continue;
        }

        // 적 데미지: "└ XXX에게 ... 데미지" (AoE 후속 적) 또는 "XXX HP: NNN"
        for (const [name, slotIdx] of Object.entries(enemyNameToSlot)) {
            if (m.includes(name + '에게') && /\\d+ 데미지/.test(m)) {
                damagedEnemies.add(slotIdx);
            }
            if (m.includes(name + ' HP:') && /HP: 0/.test(m)) {
                deadEnemies.add(slotIdx);
            }
        }

        // 일반 플레이어 공격 메시지 ("→ NN 데미지")
        if (/^→ \\d+ 데미지/.test(m) || /^\\s*→ \\d+/.test(m)) {
            playerActed = true;
            // 현재 타깃이 데미지 받음
            if (bs.target_idx !== undefined) {
                damagedEnemies.add(bs.target_idx);
            }
        }
    }

    // ── 상태 적용 ──

    // 1) 플레이어 행동 (0ms)
    if (playerActed && !playerDead) {
        if (playerSkillUsed) {
            setCharState('player_battle', 'skill');
        } else {
            setCharState('player_battle', 'attack');
        }
    }

    // 2) 적 데미지 효과 (200ms 후 — 플레이어 공격 모션 보여준 뒤)
    setTimeout(() => {
        damagedEnemies.forEach(slotIdx => {
            if (!deadEnemies.has(slotIdx)) {
                setCharState(`enemy_battle:${slotIdx}`, 'hurt');
            }
        });
    }, 200);

    // 3) 적 사망 (300ms 후 — hurt 보여준 뒤)
    setTimeout(() => {
        deadEnemies.forEach(slotIdx => {
            setDeadState(`enemy_battle:${slotIdx}`);
        });
    }, 300);

    // 4) 플레이어 피격 (700ms 후 — 적 공격 모션 보여준 뒤)
    if (playerHurt) {
        setTimeout(() => {
            if (!playerDead) {
                setCharState('player_battle', 'hurt');
                setCharState('player_panel', 'hurt', { duration: 600 });
            }
        }, 700);
    }

    // 5) 플레이어 사망 (900ms 후)
    if (playerDead) {
        setTimeout(() => {
            setDeadState('player_battle');
        }, 900);
    }
}

// 헬퍼: 일정 시간 후 setCharState 호출
function _scheduleSetState(target, state, delay) {
    setTimeout(() => setCharState(target, state), delay);
}
// ═══════════════════════════════════════════════════════════
// 배틀필드 캐릭터 이미지 갱신 헬퍼
// ───────────────────────────────────────────────────────────
// section: 'player_battle' | 'enemy_battle'
// slotIdx: enemy_battle일 때 0/1/2, player_battle일 때 null
// name:    직업명 or 몬스터명
// state:   'idle' | 'attack' | 'skill' | 'hurt' | 'dead'
//
// 동작:
//   1. CHAR_IMAGES에서 경로 조회
//   2. 해당 슬롯의 <img> 가 있으면 src 갱신
//   3. <img>가 없으면 div(이모지) 그대로 사용 (이미 위에서 textContent 설정함)
//   4. 이미지 로드 실패하면 자동으로 img 숨기고 div 표시
// ═══════════════════════════════════════════════════════════
function _updateBattleSprite(section, slotIdx, name, stateName) {
    // 이미지 경로 조회
    const imgPath = (typeof getCharImage === 'function')
        ? getCharImage(section, name, stateName)
        : null;

    // 대상 <img> / <div> 요소 찾기
    let imgEl, iconEl;
    if (section === 'player_battle') {
        imgEl  = document.getElementById('player-combatant-art-img');
        iconEl = document.getElementById('player-combatant-art');
    } else if (section === 'enemy_battle') {
        if (slotIdx === 0) {
            imgEl  = document.getElementById('enemy-art-img');
            iconEl = document.getElementById('enemy-art');
        } else if (slotIdx === 1) {
            imgEl  = document.getElementById('enemy-art-2-img');
            iconEl = document.getElementById('enemy-art-2');
        } else if (slotIdx === 2) {
            imgEl  = document.getElementById('enemy-art-3-img');
            iconEl = document.getElementById('enemy-art-3');
        }
    }

    // <img> 태그가 HTML에 없으면 → 이모지(div)만 표시하고 종료
    if (!imgEl) {
        if (iconEl) iconEl.style.display = '';
        return;
    }

    if (imgPath) {
        imgEl.src = imgPath;
        imgEl.style.display = '';
        imgEl.onerror = function() {
            this.style.display = 'none';
            if (iconEl) iconEl.style.display = '';
        };
        imgEl.onload = function() {
            if (iconEl) iconEl.style.display = 'none';
        };
    } else {
        imgEl.style.display = 'none';
        if (iconEl) iconEl.style.display = '';
    }
}