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
    refreshPlayer();   // 골드는 api()가 이미 반영함(Api.js)

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
        const ms = await api('/map/state');
        if (ms.ok && ms.map) {
            if (typeof refreshMap === 'function') refreshMap(ms.map);
            setMapMode();
        }
        // 맵이 없으면 newGame 모달에서 처리됨
    }

    // ★ 고르지 않은 보상 선택은 여기서 바로 띄우지 않고 예약만 한다 —
    //   부팅 경로(Main.js)에서는 이 함수가 끝난 뒤에야 시작 모달(modal-entry)이
    //   닫히기 때문에, 여기서 열면 시작 화면 뒤에 깔려 클릭할 수 없다(실측).
    //   시작 모달이 이미 없는 경우(전투 중 세션 복구 등)에는 곧바로 이어서 띄운다.
    state.pendingRelicOffer = r.relic_offer || null;
    if (!document.querySelector('#modal-entry.active, #modal-email.active, #modal-newgame.active')) {
        await resumePendingChoices();
    }
    return true;
}

/** 고르지 않고 남아 있는 보상 선택을 다시 띄운다 (유물 → 스킬, 전투 종료 때와 같은 순서).
 *  · 유물: 전투 종료 응답의 relic_offer로만 열렸어서, 고르기 전에 새로고침하면
 *    서버에는 티켓이 남아 있는데 화면에서 사라져 영영 못 골랐다(다음 제시가 덮어씀).
 *    이제 /api/status가 대기 티켓을 같이 내려주고, 여기서 다시 연다.
 *  · 스킬 2택 1: 데이터(state.player.pending_skill_choices)는 원래도 남아 있었지만
 *    여는 곳이 레벨업 흐름(StatAllocate.js)뿐이라 다음 레벨업까지 미뤄졌다.
 *  한 번 띄운 제안은 state에서 지우므로 여러 번 불러도 안전하다. */
async function resumePendingChoices() {
    const offer = state.pendingRelicOffer;
    state.pendingRelicOffer = null;
    if (offer && typeof openRelicChoice === 'function') await openRelicChoice(offer);
    if (typeof checkPendingSkillChoices === 'function') await checkPendingSkillChoices();
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
    // ★ 여기서 바로 showEnemyTurn()을 부르면 실제 행동할 적 인덱스를 아직
    //   몰라서 슬롯1로 기본값 처리되는데, 다대일 전투에서 2·3번 슬롯이 행동할
    //   차례면 응답이 오기 전까지 슬롯1이 "행동 중" 상태로 잘못 반짝임 —
    //   서버 응답으로 acting_enemy_idx를 알고 난 뒤(아래)에만 호출.

    try {
        const r = await api('/battle/action', { action });
        if (!r.ok) {
            toast(r.error || 'action 실패', 'error');
            // ★ 서버가 "전투 중이 아닙니다"를 주는 경우는 워커 재시작 등으로
            //   진행 중이던 전투(gs["battle"])가 사라져 세션이 복구된 상태 —
            //   클라이언트는 여전히 전투 화면인 채로 계속 같은 400을 재시도하며
            //   멈춰있게 되므로, 실제 서버 상태로 다시 동기화한다.
            if (r.error && r.error.includes('전투 중이 아닙니다')) {
                state.inBattle = false;
                await loadStatus();
            } else {
                showPlayerTurn();
            }
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
        // ★ deferDeathAnim: true — 이 시점에 HP/ATB/버튼 등은 최신 상태로
        //   반영하되, 방금 죽은 캐릭터의 스프라이트만큼은 아직 'dead'로
        //   바꾸지 않는다. 즉시 바꿔버리면 아래 playBattleSequence가 재생하는
        //   공격→피격→사망 연출이 시작되기도 전에 이미 죽은 포즈로 굳어서,
        //   그 연출 전체가 화면에 아무 효과 없이 허비됐다(CharSprite.js의
        //   "이미 dead면 재적용 스킵" 가드 때문에 시퀀서의 setDeadState
        //   호출도 무시됨).
        refreshBattle(bsForRefresh, { deferDeathAnim: true });
        showEnemyTurn(r.acting_enemy_idx);

        if (typeof playBattleSequence === 'function') {
            await playBattleSequence(action, { ...r, messages });
        } else {
            // 시퀀서가 없으면 위에서 미룬 사망 스프라이트를 아무도 안 걸어주므로
            // 여기서 최종 상태로 한 번 더 그려 보정한다.
            messages.forEach(m => logLine(m));
            refreshBattle(r);
        }

        // ★ 승리로 전투가 끝나는 순간엔 여유를 더 준다 — playBattleSequence가
        //   몬스터별 실제 사망 애니메이션 길이(frames/fps 기반)는 이미 기다린
        //   뒤이므로, 여기 추가되는 대기는 "이겼다"는 걸 느낄 여운용. 예전엔
        //   승패 관계없이 항상 400ms뿐이라 승리 직후 화면이 훅 꺼지는
        //   느낌이었음(사망 애니메이션이 끝나기도 전에 보상창으로 넘어가는
        //   경우도 있었음).
        const _postSeqWait = (r.done && r.winner === 'player') ? 2500 : 400;
        await new Promise(resolve => setTimeout(resolve, _postSeqWait));

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

            // ★ 순서 고정: 보상 확인 → 오버플로 처리 → 레벨업 스탯 분배 →
            //   노드 완료/맵 복귀. 예전엔 checkPendingPoints()가 여기서
            //   await 없이 바로 호출돼서(레벨업 모달이 즉시 뜸) 보상 모달과
            //   동시에 열리거나 순서가 꼬일 수 있었다 — 이제 둘 다 모달이
            //   닫힐 때 resolve되는 Promise라 순서대로 하나씩만 뜬다.

            // ★ 승리 시 보상 팝업 (확인 클릭까지 대기, 보상이 0개여도 항상 뜸)
            if (r.winner === 'player') {
                const _gold = r.gold_gained || 0;
                const _items = r.items_gained || [];
                // ★ RewardModal.js가 relics_gained도 같이 보므로(유물 UI 영역
                //   예약돼 있음), 여기서도 같이 챙겨야 팝업엔 뜨는데 모험 기록엔
                //   빠지는 불일치가 안 생김.
                const _relics = r.relics_gained || [];
                if (_gold > 0 || _items.length > 0 || _relics.length > 0) {
                    const _itemPart = _items.length
                        ? _items.map(id => (typeof itemLabel === 'function' ? itemLabel(id) : id)).join(', ')
                        : '';
                    const _parts = [];
                    if (_gold > 0) _parts.push(`${_gold} G`);
                    if (_itemPart) _parts.push(_itemPart);
                    if (_relics.length) _parts.push(`유물 ${_relics.length}개`);
                    logAdventure(`전리품 획득: ${_parts.join(' / ')}`, 'loot');
                }
                if (typeof showRewardModal === 'function') await showRewardModal(r);

                // ★ 보상 요약 확인 → (칸 넘친 아이템이 있으면) 교체 선택창 →
                //   레벨업 → 노드맵, 순서로 진행. openInvSwap()은 모달이 닫힐 때
                //   resolve되는 Promise를 반환하므로 순서대로 하나씩 처리.
                const _overflow = r.inventory_overflow || [];
                if (_overflow.length && typeof openInvSwap === 'function') {
                    for (const ov of _overflow) {
                        await openInvSwap(ov.item, ov.candidates || [], ov.ticket_id);
                    }
                }

                // ★ 유물 3종 택 1 (엘리트·보스 승리) — 보상·교체 다음, 레벨업 스탯 분배 앞
                if (r.relic_offer && typeof openRelicChoice === 'function') await openRelicChoice(r.relic_offer);

                if (typeof checkPendingPoints === 'function') await checkPendingPoints();
            }
            if (r.winner === 'player' && typeof handleMapNodeDone === 'function') {
                await handleMapNodeDone(r);
            } else if (r.winner === 'enemy') {
                // ★ 사망 시 맵으로 돌아가지 않음 — NEW GAME으로만 재시작 가능
                // r.feedback: 서버가 BehaviorAnalyzer/FeedbackEngine으로 생성한
                // 복기 리포트(headline/good_plays/bad_plays/suggestions/score) — 있으면 표시.
                if (typeof showGameOver === 'function') showGameOver(r.feedback);
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