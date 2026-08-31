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

    // ★ 사망 상태로 새로고침한 경우 — 맵 대신 바로 게임 오버 화면
    if (r.player && r.player.hp <= 0) {
        state.inBattle = false;
        if (typeof showGameOver === 'function') showGameOver();
        return true;
    }

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
            logAdventure(`${name}(${job})의 모험이 시작되었다.`, 'system');
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

// ── 예약 행동: 적 차례에 입력한 액션을 보관했다가 플레이어 차례에 자동 실행 ──
let _pendingBattleAction = null;

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

        // ★ 적 차례에 입력한 행동 → 백엔드가 무시(action_ignored) → 예약으로 보관
        //    (타깃 인덱스가 action 문자열에 포함돼 그대로 유지됨. 예: "skill:파이어볼:1")
        if (r.action_ignored && action !== 'auto') {
            _pendingBattleAction = action;
            logLine('⏳ 행동 예약됨 — 내 차례에 자동 실행', 'system');
        }

        const messages = r.messages || [];
        if (!Array.isArray(state.battleMessages)) state.battleMessages = [];
        state.battleMessages.push(...messages);
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
            _pendingBattleAction = null;   // 전투 종료 — 예약 초기화
            const _foeNames = (state.battleState?.enemies || []).map(e => e.name).join(', ') || '적';
            if (r.winner === 'player') {
                logLine('★ VICTORY!', 'crit');
                logAdventure(`${_foeNames}을(를) 물리쳤다.`, 'win');
                term('battle won', 'ok');
                toast('승리!');
                if (typeof showHappyState === 'function') showHappyState('player_panel', 2000);
                // ★ 전투에서 이긴 적(전멸시켰으므로 전원 처치)만 도감 해금 대상
                if (typeof recordBestiaryKill === 'function') {
                    const deadNames = (state.battleState?.enemies || []).map(e => e.name);
                    recordBestiaryKill(deadNames, state.battleMessages || []);
                }
            } else if (r.winner === 'enemy') {
                logLine('✖ DEFEAT', 'crit');
                logAdventure(`${_foeNames}에게 쓰러졌다...`, 'lose');
                term('battle lost', 'warn');
                toast('패배...', 'error');
            } else {
                logLine('▶ 도망쳤다.', 'system');
                logAdventure(`${_foeNames}에게서 도망쳤다.`, 'system');
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

            // ★ 승리 시 보상 팝업 (확인 클릭까지 대기) → 노드맵 완료 처리
            if (r.winner === 'player') {
                const _gold = r.gold_gained || 0;
                const _items = r.items_gained || [];
                if (_gold > 0 || _items.length > 0) {
                    const _itemPart = _items.length
                        ? _items.map(id => (typeof itemLabel === 'function' ? itemLabel(id) : id)).join(', ')
                        : '';
                    const _parts = [];
                    if (_gold > 0) _parts.push(`${_gold} G`);
                    if (_itemPart) _parts.push(_itemPart);
                    logAdventure(`전리품 획득: ${_parts.join(' / ')}`, 'loot');
                }
                if (typeof showRewardModal === 'function') await showRewardModal(r);
            }
            if (r.winner === 'player' && typeof handleMapNodeDone === 'function') {
                await handleMapNodeDone(r);
            } else if (r.winner === 'enemy') {
                // ★ 사망 시 맵으로 돌아가지 않음 — NEW GAME으로만 재시작 가능
                if (typeof showGameOver === 'function') showGameOver();
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
            // ★ 예약 행동이 있으면 액션창을 열지 않고 자동 실행
            if (_pendingBattleAction) {
                const pending = _pendingBattleAction;
                _pendingBattleAction = null;
                state.battleProcessing = false;
                logLine('▶ 예약 행동 실행!', 'skill');
                await new Promise(resolve => setTimeout(resolve, 300));
                await battleAction(pending);
                return;
            }
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
    // 사망 상태 차단 (백엔드도 막지만 프론트에서 1차 차단)
    if (state.player && state.player.hp <= 0) {
        toast('사망 상태에서는 아이템을 사용할 수 없습니다.', 'error');
        return;
    }
    const r = await api('/use_item', { item: itemName });
    if (!r.ok) { toast(r.error || '사용 실패', 'error'); return; }
    if (r.player) {
        state.player = r.player;
        refreshPlayer();
    }
    logLine(r.message || `${itemName} 사용`, 'heal');
    toast(r.message || `${itemName} 사용`, 'ok');
}

// performRest는 Modals.js에 정의됨 (icon 표시 + checkPendingPoints 포함)
// 이 파일에서는 중복 정의 제거