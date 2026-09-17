/* battle/BattleRender.js — 플레이어/적 슬롯 렌더 (이름/이미지/레벨/HP/MP/ATB 바) */

// 플레이어 슬롯 + 적 슬롯(1~3) + HP/MP/ATB 바 + 타겟 + 턴 시각화
// (원본 단일 for 루프 구조 보존 — 슬롯/바/타겟이 한 패스에서 처리됨)
// ── 플레이어 전투 슬롯 (이름/이미지/HP/MP/ATB) ──
// 실드바 공통 갱신 — 실드 0이면 row 숨김, 게이지 기준은 shield/maxhp
// 실드가 있다가 0이 되면 'shield-break' 파괴 모션을 잠깐 재생 후 숨긴다.
function updateShieldBar(rowId, fillId, textId, shield, maxhp) {
    const row = document.getElementById(rowId);
    const fill = document.getElementById(fillId);
    const text = document.getElementById(textId);
    if (!row) return;

    const value = Math.max(0, Number(shield || 0));
    const pct = maxhp > 0 ? Math.min(100, value / maxhp * 100) : 0;
    const prev = Number(row.dataset.prevShield || 0);
    row.dataset.prevShield = value;

    // 실드 파괴: 이전 > 0 → 현재 0 — 깨지는 모션 후 숨김
    if (prev > 0 && value <= 0) {
        row.classList.add('shield-break');
        if (fill) fill.style.width = '0%';
        if (text) text.textContent = '0';
        setTimeout(() => {
            row.classList.remove('shield-break');
            row.style.display = 'none';
        }, 450);   // CSS 애니메이션 길이와 일치
        return;
    }

    row.style.display = value > 0 ? '' : 'none';
    if (fill) fill.style.width = pct + '%';
    if (text) text.textContent = Math.round(value);
}

function renderPlayerCombatant(bs, opts) {
    opts = opts || {};
    const p = state.player;
    document.getElementById('player-combatant-art').textContent = JOB_ICONS[p.job] || '?';

    // ★ setCharState 경유(=CharSprite.js) — enemy 슬롯과 동일한 패턴.
    //   기존엔 player_battle의 idle을 트는 호출(resetAllSprites)이 어디서도 실행되지
    //   않아 스프라이트시트가 등록돼 있어도 항상 이모지 폴백만 보이는 버그가 있었음.
    const playerStateKey = bs.player_hp > 0 ? 'idle' : 'dead';
    // ★ opts.deferDeathAnim(Actions.js가 playBattleSequence 실행 전 호출하는
    //   refreshBattle에서만 true)이면서 "방금 막 죽은" 경우엔 여기서 즉시
    //   dead로 바꾸지 않는다 — 그대로 두면 CharSprite.js의 "이미 dead면
    //   재적용 스킵" 가드 때문에, 뒤이어 실행되는 playBattleSequence의
    //   피격/사망 애니메이션이 전부 무시되고 서버 응답이 오자마자 죽은
    //   포즈로 굳어버렸다(공격 모션조차 보여주기 전에). 이미 죽어 있던
    //   슬롯(이번 행동과 무관하게 예전부터 dead)은 isCharDead가 true라
    //   그대로 재적용 — 세션 복구 등 시퀀서 없이 바로 그려야 하는 경우와
    //   동일하게 정상 동작한다.
    if (playerStateKey === 'dead' && opts.deferDeathAnim && !isCharDead('player_battle')) {
        // 사망 애니메이션은 playBattleSequence의 setDeadState('player_battle')가 담당
    } else {
        setCharState('player_battle', playerStateKey, { persist: playerStateKey === 'dead' });
    }
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
    updateShieldBar('player-shield-row', 'player-cb-shield', 'player-cb-shield-text',
                    bs.player_shield, bs.player_maxhp);
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
function renderEnemySlots(bs, opts) {
    opts = opts || {};
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

        // ★ setCharState 경유(=CharSprite.js) — 스프라이트시트(원소/애니메이션) 메타를
        //   이해 못 하는 옛 _updateBattleSprite로 매 렌더 덮어쓰면, 시트 로딩 사이의
        //   찰나에 이모지 폴백이 깜빡이는 버그가 있었음(모든 시트 몬스터 공통).
        //   idle/dead는 자동 idle 복귀 타이머를 안 타므로 매 렌더 호출해도 안전.
        const stateKey = en.alive ? 'idle' : 'dead';
        // ★ renderPlayerCombatant와 동일한 이유로 "방금 죽은" 슬롯은 여기서
        //   즉시 dead 처리하지 않고 playBattleSequence의 사망 연출에 맡긴다.
        if (stateKey === 'dead' && opts.deferDeathAnim && !isCharDead(`enemy_battle:${i}`)) {
            // no-op — 아래 playBattleSequence의 setDeadState가 담당
        } else {
            setCharState(`enemy_battle:${i}`, stateKey, { persist: stateKey === 'dead' });
        }

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

        // 패턴 배지 — 죽은 적은 예고가 의미 없으므로 비운다
        renderPatternBadges(document.getElementById(`enemy-pattern${enemyIdSuffix(i)}`),
                            en.alive ? en.pattern : []);

        // HP 바
        const hpEl     = document.getElementById(`enemy-cb-hp${enemyIdSuffix(i)}`);
        const hpTextEl = document.getElementById(`enemy-cb-hp-text${enemyIdSuffix(i)}`);
        if (hpEl)     hpEl.style.width = (en.hp / en.maxhp * 100) + '%';
        updateShieldBar(`enemy-shield-row${enemyIdSuffix(i)}`,
                        `enemy-cb-shield${enemyIdSuffix(i)}`,
                        `enemy-cb-shield-text${enemyIdSuffix(i)}`,
                        en.shield, en.maxhp);
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
    }
}