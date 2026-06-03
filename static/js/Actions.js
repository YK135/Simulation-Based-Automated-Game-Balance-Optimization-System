/* ═══════════════════════════════════════════════════════════
   actions.js — 백엔드 API 호출 액션
   - loadStatus: 세션/전투 복구
   - newGame: 새 게임 시작
   - battleAction: 전투 행동 (attack, skill, item, escape)
   - useSkill / useItem / useItemInField: 사용 헬퍼
   ※ explore() 함수 제거 — 노드맵으로 대체
   ═══════════════════════════════════════════════════════════ */

async function loadStatus() {
    const r = await api('/status');
    if (!r.ok) return false;

    state.player = r.player;
    state.exploreTurn = r.turn || 0;
    if (r.gold !== undefined) state.gold = r.gold;
    refreshPlayer();

    if (r.in_battle) {
        let bs = r.battle;
        if (!bs) {
            const fetched = await api('/battle/state');
            if (fetched && fetched.turn !== undefined) bs = fetched;
        }
        if (bs) {
            refreshBattle(bs);
            term('battle session restored', 'ok');
            return true;
        }
        term('battle restore failed, fallback to map', 'warn');
    }

    state.inBattle = false;

    // 맵이 있으면 맵 모드, 없으면 맵 생성
    if (typeof setMapMode === 'function') {
        const ms = await api('/map/state', null, 'GET');
        if (ms.ok && ms.map) {
            if (typeof refreshMap === 'function') refreshMap(ms.map);
            setMapMode();
        }
        // 맵이 없으면 newGame 모달에서 처리됨
    }
    return true;
}

async function newGame(name, job) {
    if (state.creatingGame) {
        console.warn('[newGame] already in progress, ignoring duplicate call');
        return;
    }
    state.creatingGame = true;
    try {
        const r = await api('/new_game', { name, job });
        if (r.ok) {
            state.player = r.player;
            if (r.gold !== undefined) state.gold = r.gold;
            refreshPlayer();
            document.getElementById('modal-newgame')?.classList.remove('active');
            clearLog();
            logLine(`▶ ${name} (${job}) 모험 시작!`, 'skill');
            term(`session created: ${name}/${job}`, 'ok');
            toast(`Welcome, ${name}!`);
            // ★ 노드맵 챕터 1 생성
            if (typeof initMap === 'function') {
                await initMap(1);
            }
        } else {
            toast('생성 실패: ' + (r.error || 'unknown'), 'error');
        }
    } finally {
        state.creatingGame = false;
    }
}

async function battleAction(action) {
    if (state.battleProcessing) {
        term('battle action in progress, ignored', 'warn');
        return;
    }
    state.battleProcessing = true;

    document.getElementById('skill-menu')?.classList.remove('active');
    document.getElementById('item-menu')?.classList.remove('active');
    showEnemyTurn();

    try {
        const r = await api('/battle/action', { action });
        if (!r.ok) {
            toast(r.error || 'action 실패', 'error');
            showPlayerTurn();
            return;
        }

        const messages = r.messages || [];
        const bsForRefresh = { ...r, messages: [] };
        refreshBattle(bsForRefresh);
        showEnemyTurn();

        if (typeof playBattleSequence === 'function') {
            await playBattleSequence(action, { ...r, messages });
        } else {
            messages.forEach(m => logLine(m));
        }

        await new Promise(resolve => setTimeout(resolve, 400));

        // ── 종료 처리 ──
        if (r.done) {
            if (r.winner === 'player') {
                logLine('★ VICTORY!', 'crit');
                term('battle won', 'ok');
                toast('승리!');
                if (typeof showHappyState === 'function') showHappyState('player_panel', 2000);
            } else if (r.winner === 'enemy') {
                logLine('✖ DEFEAT', 'crit');
                term('battle lost', 'warn');
                toast('패배...', 'error');
            } else {
                logLine('▶ 도망쳤다.', 'system');
                term('escaped');
            }

            // UI 초기화
            const turnEl  = document.getElementById('turn-indicator');
            const actBar  = document.getElementById('action-bar');
            const actPanel = document.getElementById('actions-panel');
            if (turnEl)   turnEl.className = 'turn-indicator';
            if (actBar)   { actBar.classList.remove('your-turn', 'processing'); }
            if (actPanel) actPanel.classList.remove('processing');

            // 플레이어 상태 갱신
            if (r.player) {
                state.player = r.player;
                refreshPlayer();
            }

            if (typeof checkPendingPoints === 'function') checkPendingPoints();

            // ★ 승리 시만 노드맵 완료 처리, 패배/도망은 loadStatus
            if (r.winner === 'player' && typeof handleMapNodeDone === 'function') {
                await handleMapNodeDone(r);
            } else {
                await loadStatus();
            }
            return;
        }

        // next_actor 처리
        const nextActor = r.next_actor || 'player';
        if (nextActor === 'enemy') {
            state.battleProcessing = false;
            await new Promise(resolve => setTimeout(resolve, 500));
            await battleAction('auto');
            return;
        } else {
            showPlayerTurn();
        }

    } catch (e) {
        console.error('[battleAction]', e);
        toast('네트워크 오류', 'error');
    } finally {
        state.battleProcessing = false;
    }
}

// ── 헬퍼 ──────────────────────────────────────────────────

function _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function _withTarget(action) {
    if (!state.battleState) return action;
    const enemies = state.battleState.enemies || [];
    if (enemies.length <= 1) return action;
    const idx = state.battleState.target_idx ?? 0;
    return `${action}:${idx}`;
}

async function useSkill(skillName) {
    await battleAction(_withTarget(`skill:${skillName}`));
}

async function useItem(itemName) {
    // 아이템은 타깃 인덱스 불필요 — BattleSession이 직접 처리
    await battleAction(`item:${itemName}`);
}

async function useItemInField(itemName) {
    const r = await api('/use_item', { item: itemName });
    if (!r.ok) { toast(r.error || '사용 실패', 'error'); return; }
    if (r.player) {
        state.player = r.player;
        refreshPlayer();
        if (typeof refreshExploreInfo === 'function') refreshExploreInfo();
    }
    logLine(r.message || `${itemName} 사용`, 'heal');
    toast(r.message || `${itemName} 사용`, 'ok');
}

// performRest는 Modals.js에 정의됨 (icon 표시 + checkPendingPoints 포함)
// 이 파일에서는 중복 정의 제거