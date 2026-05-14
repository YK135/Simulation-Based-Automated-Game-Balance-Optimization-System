/* ═══════════════════════════════════════════════════════════
   actions.js — 백엔드 API 호출 액션
   - loadStatus: 세션/전투 복구
   - newGame: 새 게임 시작
   - explore: 탐험
   - battleAction: 전투 행동 (attack, skill, item, escape)
   - useSkill / useItem / useItemInField: 사용 헬퍼
   ═══════════════════════════════════════════════════════════ */

async function loadStatus() {
    const r = await api('/status');
    if (!r.ok) return false;

    state.player = r.player;
    state.exploreTurn = r.turn || 0;
    refreshPlayer();

    // 서버 세션이 전투 중이면 전투 상태 복구.
    // 1차: /api/status 응답에 battle 페이로드 포함 (백엔드가 합쳐서 줌)
    // 2차 폴백: in_battle만 true면 /api/battle/state 별도 호출
    if (r.in_battle) {
        let bs = r.battle;
        if (!bs) {
            const fetched = await api('/battle/state');
            if (fetched && fetched.turn !== undefined && fetched.player_hp !== undefined) {
                bs = fetched;
            }
        }
        if (bs) {
            refreshBattle(bs);
            term('battle session restored', 'ok');
            return true;
        }
        term('battle restore failed, fallback to peace', 'warn');
    }

    state.inBattle = false;
    setExploreMode();
    return true;
}

async function newGame(name, job) {
    const r = await api('/newgame', { name, job });
    if (!r.ok) { toast(r.error || '게임 시작 실패', 'error'); return; }
    state.player = r.player;
    state.inBattle = false;
    refreshPlayer();

    // ★ 모든 스프라이트 idle로 초기화 (새 게임이면 idle 상태로)
    if (typeof resetAllSprites === 'function') {
        // 배틀필드는 아직 표시 안 되니까 player_panel만
        setCharState('player_panel', 'idle');
    } else {
        toast('생성 실패: ' + (r.error||'unknown'), 'error');
    }
}

async function explore() {
    // ── 연타 방지 락 ──
    // 백엔드 응답이 도착하기 전에 두 번째 explore 클릭이 들어오면 무시.
    // 응답 처리 중 race condition으로 인해 이벤트가 스킵되는 버그 방지.
    if (state.exploring) {
        term('exploration in progress, ignored', 'warn');
        return;
    }
    state.exploring = true;

    // 탐험 버튼 즉시 비활성화 (시각적 피드백)
    const btn = document.getElementById('btn-explore');
    if (btn) {
        btn.disabled = true;
        btn.style.opacity = '0.5';
        btn.style.cursor = 'wait';
    }

    try {
        term('exploring field...');
        const r = await api('/explore', {});
        if (!r.ok) {
            toast(r.error || '탐험 실패', 'error');
            return;
        }

        if (r.event === 'battle' || r.event === 'midboss' || r.event === 'finalboss' || r.event === 'battle_multi') {
            state.inBattle = true;
            if (r.event === 'midboss') {
                logLine('▼ 중간 보스가 나타났다!', 'crit');
                term('encounter: MIDBOSS', 'warn');
            } else if (r.event === 'finalboss') {
                logLine('▼ 최종 보스가 나타났다!', 'crit');
                term('encounter: FINALBOSS', 'warn');
            } else if (r.event === 'battle_multi') {
                const names = (r.enemies || []).map(e => e.name).join(', ');
                logLine(`⚠ ${r.enemy_count}마리의 적이 나타났다! [${names}]`, 'crit');
                term(`encounter: ${r.enemy_count} enemies`, 'warn');
            } else {
                const enemyName = r.battle_state?.enemy_info?.name || r.battle_state?.enemy_name || '???';
                logLine(`▼ ${enemyName}이(가) 나타났다!`, 'system');
                term(`encounter: ${enemyName}`);
            }
            refreshBattle(r.battle_state);
            animateBalanceTuning();
        } else if (r.event === 'item') {
            logLine(`✚ 아이템 획득: ${r.item}`, 'heal');
            term('item gained');
            if (r.player) { state.player = r.player; refreshPlayer(); }
            toast(`+ ${r.item}`);
            // ★ 좌측 패널 happy 표정 1.5초
            showHappyState('player_panel', 1500);
        } else if (r.event === 'rest') {
            logLine('🌙 휴식 장소를 발견했다.', 'heal');
            term('rest event');
            showRestModal();
            // ★ 휴식 발견도 좋은 이벤트 — happy
            showHappyState('player_panel', 1500);
        } else if (r.event === 'gameover') {
            logLine('✖ GAME OVER', 'crit');
            term('game over', 'warn');
            toast('게임 오버. 다시 시작하세요.', 'warn');
        } else {
            logLine(r.message || '아무 일도 일어나지 않았다.', 'system');
            if (r.player) { state.player = r.player; refreshPlayer(); }
        }

        // 진행 턴 동기화
        if (!state.inBattle) {
            const st = await api('/status');
            if (st.ok) {
                state.exploreTurn = st.turn || 0;
                refreshExploreTurn();
            }
        }
    } finally {
        // 락 해제 — 응답이 성공/실패 어느 쪽이든 반드시 해제 (try/finally)
        state.exploring = false;
        if (btn) {
            btn.disabled = false;
            btn.style.opacity = '';
            btn.style.cursor = '';
        }
    }
}

async function battleAction(action) {
    // ── 연타 방지 락 ──
    if (state.battleProcessing) {
        term('battle action in progress, ignored', 'warn');
        return;
    }
    state.battleProcessing = true;

    document.getElementById('skill-menu').classList.remove('active');
    document.getElementById('item-menu').classList.remove('active');

    // 즉시 적 턴 시각화 (버튼 disabled + ENEMY TURN 표시)
    showEnemyTurn();

    try {
        const r = await api('/battle/action', { action });
        if (!r.ok) {
            toast(r.error || 'action 실패', 'error');
            return;
        }

        // ── ENEMY TURN 연출 (500ms) ──
        // refreshBattle()이 자동으로 showPlayerTurn()을 호출하기 때문에
        // refreshBattle 전에 sleep을 해서 ENEMY TURN 표시를 실제로 보이게 함.
        // 전투 종료 시(r.done)는 어차피 인디케이터 끄므로 딜레이 불필요.
        if (!r.done) {
            await _sleep(500);
        }

        // 상태 갱신 (HP/MP/타깃 등 + showPlayerTurn 자동 호출)
        refreshBattle(r);

        if (r.done) {
            if (r.winner === 'player') {
                logLine('★ VICTORY!', 'crit');
                term('battle won', 'ok');
                toast('승리!');
                // ★ 승리 시 happy 표정 (좌측 패널)
                showHappyState('player_panel', 2000);

                // 레벨업 메시지 있으면 더 길게 happy
                const hasLevelUp = (r.messages || []).some(m => m.includes('LEVEL UP'));
                if (hasLevelUp) {
                    showHappyState('player_panel', 3000);
                }
            } else if (r.winner === 'enemy') {
                logLine('✖ DEFEAT', 'crit');
                term('battle lost', 'warn');
                toast('패배...', 'error');
            } else {
                logLine('▶ 도망쳤다.', 'system');
                term('escaped');
            }
            document.getElementById('turn-indicator').className = 'turn-indicator';
            document.getElementById('action-bar').classList.remove('your-turn');
            await loadStatus();
        }
        // r.done이 false인 경우: refreshBattle이 이미 showPlayerTurn 호출했으므로
        // 별도 처리 불필요. (이전 버전에서 중복 호출하던 부분 제거)
    } finally {
        // 락 해제
        state.battleProcessing = false;
    }
}

// ── 헬퍼: 비동기 sleep ──
function _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// 다대일 전투 시 타깃 인덱스를 액션에 첨부.
// 단일전이면 그대로 보냄.
function _withTarget(action) {
    if (!state.battleState) return action;
    const enemies = state.battleState.enemies || [];
    if (enemies.length <= 1) return action;
    const idx = state.battleState.target_idx ?? 0;
    return `${action}:${idx}`;
}

async function useSkill(skillName) { await battleAction(_withTarget(`skill:${skillName}`)); }
async function useItem(itemName)  { await battleAction(`item:${itemName}`); }  // 아이템은 타깃 무관

// 탐험 중 아이템 사용 (전투 외 — /api/use_item 호출)
async function useItemInField(itemName) {
    if (state.inBattle) {
        toast('전투 중에는 전투 메뉴에서 사용하세요', 'warn');
        return;
    }
    const r = await api('/use_item', { item: itemName });
    if (!r.ok) {
        toast(r.error || '아이템 사용 실패', 'error');
        return;
    }
    if (r.player) { state.player = r.player; refreshPlayer(); }
    if (r.message) {
        logLine('✚ ' + r.message, 'heal');
        term(`item used: ${itemName}`, 'ok');
        toast(r.message);
    }
}