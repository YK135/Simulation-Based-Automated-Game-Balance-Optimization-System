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
    // 턴 시각화는 renderBattleStage 내부 updateBattleTurnVisual에서 처리.
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


// ── 전투 무대 렌더 오케스트레이터 ──
function renderBattleStage(bs) {
    renderPlayerCombatant(bs);
    renderEnemySlots(bs);
    renderBattleTargetTags(bs);
    bindEnemyTargetClicks(bs);
    updateBattleTurnVisual(bs);
    return state.player;
}