// ─────────────────────────────────────────────
// 타이밍 상수 (밀리초)
// ★ 애니메이션 에셋(스프라이트시트)이 있는 상태(attack/skill/hurt/dead)는
//   _animDuration()이 실제 프레임수/fps로 계산한 값을 우선 쓰고, 여기 상수는
//   시트가 없는 캐릭터(정지 이미지/이모지)에 대한 폴백으로만 쓰인다.
//   ITEM_USE/ESCAPE_TRY/NEXT_ENEMY_GAP/NEXT_TURN_GAP처럼 캐릭터 모션과
//   무관한(순수 페이싱용) 값은 그대로 고정 상수.
// ─────────────────────────────────────────────
const SEQ_TIMING = {
    PASSIVE_MSG:        400,  // 패시브 메시지 표시 후 대기
    PLAYER_ACTION:      500,  // 플레이어 공격/스킬 모션
    DAMAGE_APPLY:       400,  // 데미지 적용 + 적 hurt
    ENEMY_DEAD:         600,  // 적 사망 연출
    NEXT_ENEMY_GAP:     300,  // 다음 적 전환 대기 (다대일)
    ENEMY_ACTION:       500,  // 적 공격/스킬 모션
    PLAYER_HURT:        500,  // 플레이어 피격 (face_B 표시 포함)
    NEXT_TURN_GAP:      300,  // 다음 턴 준비 대기
    SKILL_MOTION_BONUS: 200,  // 스킬은 공격보다 +200ms 더 김
    ITEM_USE:           400,  // 아이템 사용
    ESCAPE_TRY:         600,  // 도망 시도
};


// 비동기 sleep 헬퍼
function _seqSleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// 실제 스프라이트시트 재생 시간(ms) — 프레임 수/fps 기반으로 계산.
// 시트가 아니면(정지 이미지/이모지 폴백) fallbackMs를 그대로 씀.
// 이렇게 하면 다음 단계로 넘어가기 전에 "지금 캐릭터가 보여주는 모션"이
// 실제로 다 재생될 시간을 확보할 수 있음 — 애니메이션 에셋이 없는 캐릭터는
// 기존 고정 대기시간(SEQ_TIMING.*)이 폴백으로 그대로 적용되어 회귀 없음.
// section: 'player_battle' | 'enemy_battle', stateName: 'attack'|'skill'|'hurt'|'dead'
function _animDuration(section, name, stateName, fallbackMs) {
    const sheet = _sheetDuration(section, name, stateName);
    return sheet === null ? fallbackMs : sheet + 150;         // +150ms 여유 버퍼
}

// 시트 자체가 재생되는 순수 시간 (여유 버퍼 제외). 시트가 아니면 null.
//   ★ 임팩트 지점(데미지 숫자/플래시)은 반드시 이 값 기준으로 잡아야 한다.
//     버퍼가 포함된 _animDuration에 비율을 곱하면 타격 프레임보다 늦게 터진다 —
//     8프레임 시트에서 0.55 × (시트+150) 은 6번째 프레임(이미 회수 동작)이고,
//     0.55 × 시트 는 5번째 프레임(실제 타격 프레임)이다.
function _sheetDuration(section, name, stateName) {
    const meta = (typeof getCharImage === 'function') ? getCharImage(section, name, stateName) : null;
    if (meta && typeof meta === 'object' && meta.type === 'sheet' && meta.frames > 1) {
        return Math.ceil((meta.frames / (meta.fps || 8)) * 1000);
    }
    return null;
}

// 모션 전체 시간(actionTime) 중 "타격이 실제로 닿는" 지점.
//   시트가 있으면 시트 길이의 IMPACT_RATIO, 없으면(정지/이모지) 폴백 시간의 비율.
//   반환 값은 항상 actionTime 이하 — 남는 시간은 호출부가 hurt 단계에 흡수시킨다.
function _impactWait(section, name, stateName, actionTime, ratio) {
    const sheet = _sheetDuration(section, name, stateName);
    const base = sheet === null ? actionTime : sheet;
    return Math.min(actionTime, Math.round(base * ratio));
}

function _deathAnimDuration(section, name) {
    return _animDuration(section, name, 'dead', SEQ_TIMING.ENEMY_DEAD);
}


// 메시지 분류
// ─────────────────────────────────────────────
// 입력: 서버가 보낸 messages 배열
// 출력: 단계별 그룹으로 분류된 객체
//
// 구분 패턴:
//   passive  : "[전사 패시브]", "[탱커 패시브]" 등 [...]로 시작
//   player   : "→ N 데미지", "...사용 →", "(전체 공격!) →"
//   damage   : "{몬스터명} HP:", "└ 데미지", "회복"
//   enemy_dead: "...을(를) 처치했다", "모든 적을 처치"
//   enemy    : "{몬스터명} →" 또는 "{몬스터명}이(가)" + 데미지
//   player_hurt: "{플레이어명} HP:"
//   victory_defeat: "VICTORY", "DEFEAT", "쓰러졌다", "도망"
// ─────────────────────────────────────────────
function _classifyMessages(messages, bs) {
    const playerName = (window.state && window.state.player) ? window.state.player.name : '';
    const enemyNames = (bs.enemies || []).map(e => e.name);

    const groups = {
        passive:    [],   // 패시브 메시지
        player:     [],   // 플레이어 공격/스킬 메시지
        damage:     [],   // 데미지 결과 (적 HP)
        enemy_dead: [],   // 적 사망
        enemy:      [],   // 적 행동
        player_hurt:[],   // 플레이어 피격
        ending:     [],   // 전투 종료 메시지
        misc:       [],   // 분류 안 된 나머지
    };

    let phase = 'pre_player';  // 진행 단계 추적 (메시지가 시간 순이므로)

    for (const m of messages) {
        // 패시브 메시지 (대괄호로 시작)
        if (m.startsWith('[') && m.includes('패시브')) {
            groups.passive.push(m);
            continue;
        }

        // 전투 종료 메시지
        if (m.includes('처치했다') && (m.includes('모든') || enemyNames.some(n => m.includes(n)))) {
            groups.enemy_dead.push(m);
            phase = 'after_player_damage';
            continue;
        }
        if (m.includes('쓰러졌다')) {
            groups.ending.push(m);
            continue;
        }

        // 적 행동 메시지: "{몬스터명} →" 또는 "{몬스터명}이(가)"
        let isEnemyAction = false;
        for (const name of enemyNames) {
            if (m.startsWith(name + ' →') ||
                m.includes(name + '이(가) 기회를') ||
                m.includes(name + '이(가) 먼저')) {
                groups.enemy.push(m);
                phase = 'enemy_turn';
                isEnemyAction = true;
                break;
            }
        }
        if (isEnemyAction) continue;

        // 회피 메시지 (적 공격을 플레이어가 회피)
        if (m.includes('회피했다') || m.includes('회피!')) {
            if (phase === 'enemy_turn') {
                groups.enemy.push(m);
            } else {
                groups.player.push(m);
            }
            continue;
        }

        // 플레이어 HP 변동 (적 행동의 결과)
        if (playerName && m.includes(playerName + ' HP:')) {
            groups.player_hurt.push(m);
            continue;
        }

        // 적 HP 변동 (플레이어 행동의 결과)
        let isEnemyHP = false;
        for (const name of enemyNames) {
            if (m.includes(name + ' HP:')) {
                if (phase === 'enemy_turn') {
                    // 적이 적을 회복시킨 경우 (사제힐 등) — enemy 그룹에
                    groups.enemy.push(m);
                } else {
                    groups.damage.push(m);
                }
                isEnemyHP = true;
                break;
            }
        }
        if (isEnemyHP) continue;

        // 피해 결과 줄 — "└ XXX에게 N 데미지"(AoE 후속),
        //   "N타: XXX에게 N 피해!"(연속공격/연속찌르기), "XXX에게 추가 N 피해!"(원소 반응)
        //   ★ 예전엔 '데미지'만 봐서 '피해' 표기를 쓰는 타격별 경로의 메시지가
        //     전부 misc로 떨어졌다 — groups.damage가 비면 시퀀서의 "데미지 적용 +
        //     hurt" 단계 자체가 건너뛰어져서, 전사 연속공격은 데미지 숫자 팝업·
        //     피격 모션·히트 플래시가 하나도 안 나왔다(무성 버그).
        if (m.trim().startsWith('└')
            || (m.includes('에게') && (m.includes('데미지') || m.includes('피해')))
            || /^총 .*(피해|데미지)/.test(m.trim())) {     // 연속 타격 합계 줄
            groups.damage.push(m);
            continue;
        }

        // 플레이어 행동 (공격/스킬)
        // "→ N 데미지", "...사용 →", "(전체 공격!)" 등
        if (m.includes('→') && (m.includes('데미지') || m.includes('사용'))) {
            // phase 전환
            if (phase === 'pre_player') phase = 'player_turn';
            groups.player.push(m);
            continue;
        }

        // 사용 (실드, 강화, 힐 등 비공격)
        if (m.includes('사용') || m.includes('생성') || m.includes('강화')) {
            groups.player.push(m);
            continue;
        }

        // 분류 안 됨 — 안전망
        groups.misc.push(m);
    }

    return groups;
}


// 메시지 종류별 색상 (logLine cls)
function _msgCls(msg) {
    if (msg.includes('치명타') || msg.includes('CRIT')) return 'crit';
    if (msg.includes('회피') || msg.includes('MISS')) return 'system';
    if (msg.includes('회복') || msg.includes('HP +')) return 'heal';
    if (msg.includes('사용') || msg.includes('스킬') || msg.includes('패시브')) return 'skill';
    if (msg.includes('데미지') || msg.includes('피해')) return 'dmg';   // 타격별 경로는 '피해' 표기
    if (msg.includes('처치') || msg.includes('VICTORY')) return 'crit';
    return '';
}


// ═══════════════════════════════════════════════════════════
// 메인: 배틀 시퀀스 재생
// ───────────────────────────────────────────────────────────
// action:  플레이어가 선택한 행동 (attack, skill:..., item:..., escape)
// bs:      서버 응답 (battle state + messages)
// ───────────────────────────────────────────────────────────
// 흐름:
//   1. 메시지 분류
//   2. 패시브 (있으면)
//   3. 플레이어 행동 + 모션
//   4. 데미지 + 적 hurt
//   5. 적 사망 + dead
//   6. 적 행동 + 모션
//   7. 플레이어 피격 + face_B
//   8. 종료 메시지
// ═══════════════════════════════════════════════════════════
async function playBattleSequence(action, bs) {
    const messages = bs.messages || [];
    if (messages.length === 0) return;

    const groups = _classifyMessages(messages, bs);

    // 액션 종류 파악 (모션 시간 결정)
    const isSkill  = action && action.startsWith('skill:');
    const isItem   = action && action.startsWith('item:');
    const isEscape = action === 'escape';

    // ── 1. 패시브 메시지 (행동 전) ──
    if (groups.passive.length > 0) {
        for (const m of groups.passive) {
            logLine(m, _msgCls(m));
        }
        await _seqSleep(SEQ_TIMING.PASSIVE_MSG);
    }

    // 공격 모션 중 "타격이 꽂히는" 지점 비율 — 모션이 다 끝난 뒤에 피격을
    // 처리하면 버튼을 누르고 모션 전체가 흐른 다음에야 숫자가 떠서 반응이
    // 느리게 느껴진다. 실제 게임처럼 모션 중간에 임팩트를 넣고, 남은 모션
    // 시간은 피격 단계가 이어서 소화한다(전체 페이싱 총합은 거의 동일).
    //   ★ 비율은 _impactWait()가 "시트 길이"에 곱한다(여유 버퍼 제외).
    //     8프레임 공격 시트에서 0.55 → 5번째 프레임 = 실제 타격 프레임.
    //     마법사 mage_B(8f): 1~3 준비동작 / 4 시전 정점 / 5 발출 / 6~8 회수
    //     박쥐   bat_B(8f) : 1~4 상승·날개접기 / 5~6 급강하(타격) / 7~8 복귀
    const IMPACT_RATIO = 0.55;
    let motionRemainder = 0;

    // ── 2. 플레이어 행동 + 모션 ──
    //   ★ AoE(슬래시·난사)의 선언 문구 "슬래시1 (전체 공격!) → …에게 N 데미지"는 분류기가
    //     피해 줄로 보내 groups.player가 비므로, 메시지만 보면 이 단계가 통째로 건너뛰어진다
    //     (모션도 시전 이펙트도 없음). 행동했는지는 구조화 필드 bs.action_fx로 판정한다.
    const playerActed = !!(bs.action_fx && bs.action_fx.actor === 'player');
    if (groups.player.length > 0 || isItem || isEscape || playerActed) {
        const job = (window.state && window.state.player) ? window.state.player.job : '';

        // 모션 트리거 (이미지 변화) — 대기 시간도 실제 시트 재생 길이로 계산
        let actionTime;
        if (isSkill) {
            actionTime = _animDuration('player_battle', job, 'skill',
                SEQ_TIMING.PLAYER_ACTION + SEQ_TIMING.SKILL_MOTION_BONUS);
            if (typeof setCharState === 'function') {
                setCharState('player_battle', 'skill', { duration: actionTime });
            }
        } else if (isItem) {
            actionTime = SEQ_TIMING.ITEM_USE;   // 아이템은 별도 모션 없음 — 메시지만
        } else if (isEscape) {
            actionTime = SEQ_TIMING.ESCAPE_TRY;  // 도망도 별도 모션 없음
        } else {
            actionTime = _animDuration('player_battle', job, 'attack', SEQ_TIMING.PLAYER_ACTION);
            if (typeof setCharState === 'function') {
                setCharState('player_battle', 'attack', { duration: actionTime });
            }
        }

        // 메시지 출력
        for (const m of groups.player) {
            logLine(m, _msgCls(m));
        }

        // 임팩트 지점까지만 대기 — 나머지 모션 시간은 피격 단계로 넘긴다.
        //   아이템/도주는 캐릭터 모션이 없으니 그대로 전체 대기.
        if (isItem || isEscape) {
            // 시전 이펙트 1회 (RULE 1) — 아이템은 모션이 없으니 사용 시점을 임팩트로 본다
            const fxEnd = (typeof playSkillFx === 'function' && bs.action_fx && bs.action_fx.actor === 'player')
                ? playSkillFx(bs.action_fx, { impactAt: Math.round(actionTime * 0.5) }) : 0;
            await _seqSleep(Math.max(actionTime, fxEnd));
        } else {
            const impactWait = _impactWait('player_battle', job,
                isSkill ? 'skill' : 'attack', actionTime, IMPACT_RATIO);
            // 시전 이펙트 1회 (RULE 1) — bs.action_fx는 시전당 1개. impact_frame이 임팩트에 오도록
            // SkillFx가 시작 시점을 앞당기고, 이펙트 꼬리는 피격 단계 대기에 합산한다.
            const fxEnd = (typeof playSkillFx === 'function' && bs.action_fx && bs.action_fx.actor === 'player')
                ? playSkillFx(bs.action_fx, { impactAt: impactWait }) : 0;
            motionRemainder = Math.max(actionTime - impactWait, fxEnd - impactWait);
            await _seqSleep(impactWait);
        }
    }

    // ── 3. 데미지 적용 + 적 hurt ──
    if (groups.damage.length > 0) {
        // 어떤 적이 데미지 받았는지 매핑
        const enemyNames = (bs.enemies || []).map(e => e.name);
        const damagedSlots = new Set();
        for (const m of groups.damage) {
            for (let i = 0; i < enemyNames.length; i++) {
                if (m.includes(enemyNames[i])) {
                    damagedSlots.add(i);
                }
            }
        }
        // 타깃이 명시 안 되면 (단일 공격 "→ N 데미지") 현재 타깃 인덱스 사용
        if (damagedSlots.size === 0 && bs.target_idx !== undefined) {
            damagedSlots.add(bs.target_idx);
        }

        // 적들에게 hurt 적용 — 실제 hurt 시트 길이만큼 대기 (여러 마리면 최댓값)
        let hurtWait = SEQ_TIMING.DAMAGE_APPLY;
        if (typeof setCharState === 'function') {
            for (const slotIdx of damagedSlots) {
                // 슬롯이 살아있는 적인지 확인
                const en = bs.enemies && bs.enemies[slotIdx];
                if (en && en.alive) {
                    const d = _animDuration('enemy_battle', en.name, 'hurt', SEQ_TIMING.DAMAGE_APPLY);
                    setCharState(`enemy_battle:${slotIdx}`, 'hurt', { duration: d });
                    hurtWait = Math.max(hurtWait, d);
                }
            }
        }

        // ★ 데미지 숫자 + 피격 플래시 — hurt 시트가 시작되는 이 프레임에 같이 띄운다.
        //   값은 서버의 구조화 필드(bs.hits)에서 가져오므로 메시지 문자열을
        //   파싱하지 않는다. 적 대상만 여기서 재생하고, 플레이어 피격 숫자는
        //   아래 "6. 플레이어 피격" 단계에서 그 타이밍에 맞춰 따로 재생한다.
        if (typeof playHitFeedback === 'function') {
            playHitFeedback(bs.hits, 'enemy');
        }

        // 메시지 출력
        for (const m of groups.damage) {
            logLine(m, _msgCls(m));
        }

        // 피격 모션과, 위에서 넘겨받은 공격 모션 잔여 시간 중 긴 쪽만큼 대기
        await _seqSleep(Math.max(hurtWait, motionRemainder));
    } else if (motionRemainder > 0) {
        // 피해가 없는 시전(버프·실드·힐)은 이펙트 꼬리만큼만 기다린다 — 안 하면 다음 단계가 이펙트를 덮는다
        await _seqSleep(motionRemainder);
    }

    // ── 4. 적 사망 처리 ──
    if (groups.enemy_dead.length > 0) {
        // 죽은 적 슬롯에 dead 상태 — 마지막 킬이 곧바로 전투 종료(보상/다음 노드)로
        // 이어지는 경우, 죽는 애니메이션이 다 재생되기 전에 화면이 넘어가버리는
        // 문제가 있었음. 실제 사망 시트 재생 시간(프레임수/fps)만큼 대기하도록
        // 계산해서, 여러 마리가 동시에 죽어도(AoE) 가장 긴 애니메이션 기준으로 맞춤.
        let deadWait = SEQ_TIMING.ENEMY_DEAD;
        if (typeof setDeadState === 'function') {
            (bs.enemies || []).forEach((en, i) => {
                if (en && !en.alive && !en.fled) {      // 달아난 적은 사망 연출 대상이 아니다
                    setDeadState(`enemy_battle:${i}`);
                    deadWait = Math.max(deadWait, _deathAnimDuration('enemy_battle', en.name));
                }
            });
        }
        // 사망 대기 = max(사망 시트, 아직 재생 중인 이펙트) — 안 하면 마지막 킬의 이펙트가 잘린다 (12-5 5단계)
        if (typeof skillFxRemainingMs === 'function') deadWait = Math.max(deadWait, skillFxRemainingMs());

        for (const m of groups.enemy_dead) {
            logLine(m, _msgCls(m));
        }

        await _seqSleep(deadWait);
    }

    // ── 5. 적 행동 처리 (다대일은 적별로 순차) ──
    if (groups.enemy.length > 0) {
        // 적 행동 메시지를 적별로 분리
        const enemyMessages = _splitEnemyMessages(groups.enemy, bs);

        for (const enemyGroup of enemyMessages) {
            const { slotIdx, messages: emsgs } = enemyGroup;
            const en = bs.enemies && bs.enemies[slotIdx];
            const enemyName = en ? en.name : '';

            // 적 모션 (attack/skill) — 실제 시트 길이만큼 대기
            // ★ 예전엔 메시지에 숫자 '1'/'2'가 있으면 스킬로 판정했는데, 데미지
            //   숫자에도 1/2가 흔히 섞여있어 평범한 공격("... | 12 데미지")까지
            //   스킬로 오판되는 버그가 있었음. 일반 공격 메시지는 항상
            //   "이름 → 공격..." 형태(ai/battle_session/Enemy_Actions.py)라
            //   "→ 공격"이 아닌 경우만 스킬로 판정.
            const isEnemySkill = emsgs.some(m =>
                m.includes('→') && !m.includes('→ 공격')
            );
            const motionState = isEnemySkill ? 'skill' : 'attack';
            const motionTime = _animDuration('enemy_battle', enemyName, motionState, SEQ_TIMING.ENEMY_ACTION);
            if (typeof setCharState === 'function' && slotIdx !== null) {
                setCharState(`enemy_battle:${slotIdx}`, motionState, { duration: motionTime });
            }

            // 메시지 출력
            for (const m of emsgs) {
                logLine(m, _msgCls(m));
            }

            // 임팩트 지점까지만 대기 (플레이어 공격과 같은 규칙 — 대칭 유지).
            //   남은 모션 시간은 아래 피격 단계가 이어서 소화한다.
            const enemyImpactWait = _impactWait('enemy_battle', enemyName, motionState,
                motionTime, IMPACT_RATIO);
            // 적의 시전 이펙트 1회 — action_fx.actor_slot이 이 적일 때만 (한 step에 적은 하나만 행동한다)
            const enemyFxEnd = (typeof playSkillFx === 'function' && bs.action_fx
                                && bs.action_fx.actor === 'enemy' && bs.action_fx.actor_slot === slotIdx)
                ? playSkillFx(bs.action_fx, { impactAt: enemyImpactWait }) : 0;
            const enemyMotionRemainder = Math.max(motionTime - enemyImpactWait, enemyFxEnd - enemyImpactWait);
            await _seqSleep(enemyImpactWait);

            // ── 6. 플레이어 피격 (적 행동 결과) ──
            // 플레이어 HP 메시지가 있으면 피격
            const playerHurtMsg = groups.player_hurt.shift();  // 적별로 하나씩 소비
            if (playerHurtMsg) {
                // 플레이어 hurt 표정 + 배틀 이미지 — 실제 시트 길이만큼 대기
                const job = (window.state && window.state.player) ? window.state.player.job : '';
                const hurtTime = _animDuration('player_battle', job, 'hurt', SEQ_TIMING.PLAYER_HURT);
                if (typeof setCharState === 'function') {
                    setCharState('player_battle', 'hurt', { duration: hurtTime });
                    setCharState('player_panel', 'hurt', { duration: hurtTime + 100 });
                }
                // 플레이어 피격 숫자 + 플래시 (적별 순차 재생이라 이 타이밍에)
                //   ★ 한 step에 적이 여러 마리 때려도 bs.hits의 플레이어 항목은
                //     합계 1개다(스냅샷 차분). 첫 피격 때만 띄우고 소비 처리해
                //     같은 숫자가 적마다 반복되지 않게 한다.
                if (typeof playHitFeedback === 'function' && bs.hits) {
                    playHitFeedback(bs.hits, 'player');
                    bs.hits = bs.hits.filter(h => h.target !== 'player');
                }
                logLine(playerHurtMsg, _msgCls(playerHurtMsg));
                await _seqSleep(Math.max(hurtTime, enemyMotionRemainder));
            } else {
                // 피격이 없었으면(회피/버프 등) 남은 모션 시간을 여기서 소화
                await _seqSleep(enemyMotionRemainder);
            }

            // 다음 적 전환 대기 (다대일)
            if (enemyMessages.length > 1) {
                await _seqSleep(SEQ_TIMING.NEXT_ENEMY_GAP);
            }
        }
    } else if (groups.player_hurt.length > 0) {
        // 적 행동 메시지 없는데 플레이어 HP만 변한 경우 (드물지만 안전망)
        for (const m of groups.player_hurt) {
            logLine(m, _msgCls(m));
        }
    }

    // ── 7. 종료 메시지 ──
    if (groups.ending.length > 0) {
        // 플레이어 사망이면 dead — 적 사망과 동일하게 실제 시트 길이만큼 대기
        // (게임오버 화면으로 넘어가기 전에 애니메이션이 끊기지 않도록)
        let endingWait = SEQ_TIMING.NEXT_TURN_GAP;
        if (typeof setDeadState === 'function') {
            const playerDied = groups.ending.some(m => m.includes('쓰러졌다'));
            if (playerDied) {
                setDeadState('player_battle');
                setDeadState('player_panel');
                const job = window.state && window.state.player ? window.state.player.job : '';
                endingWait = Math.max(endingWait, _deathAnimDuration('player_battle', job));
            }
        }
        if (typeof skillFxRemainingMs === 'function') endingWait = Math.max(endingWait, skillFxRemainingMs());

        for (const m of groups.ending) {
            logLine(m, _msgCls(m));
        }
        await _seqSleep(endingWait);
    }

    // ── 8. 분류 안 된 메시지 (안전망) ──
    for (const m of groups.misc) {
        logLine(m, _msgCls(m));
    }

    // 마지막 다음 턴 준비 대기
    await _seqSleep(SEQ_TIMING.NEXT_TURN_GAP);
}


// 적 메시지를 적별로 분리
// "고블린 → 공격..."  "고블린 HP: ..."  "박쥐 → 공격..."  같이 섞여있을 때
// → [{slotIdx: 0, messages: [...]}, {slotIdx: 2, messages: [...]}]
function _splitEnemyMessages(enemyMessages, bs) {
    const enemyNames = (bs.enemies || []).map(e => e.name);
    const result = [];
    let currentGroup = null;

    for (const m of enemyMessages) {
        // 어떤 적의 메시지인지 찾기
        let foundSlot = null;
        for (let i = 0; i < enemyNames.length; i++) {
            if (m.includes(enemyNames[i])) {
                foundSlot = i;
                break;
            }
        }

        if (foundSlot !== null) {
            // 새 그룹 시작
            if (!currentGroup || currentGroup.slotIdx !== foundSlot) {
                currentGroup = { slotIdx: foundSlot, messages: [] };
                result.push(currentGroup);
            }
            currentGroup.messages.push(m);
        } else if (currentGroup) {
            // 명시 안 된 메시지는 현재 그룹에 (회피 등)
            currentGroup.messages.push(m);
        } else {
            // 첫 그룹도 없는데 분류 안 된 메시지 — 슬롯 0에 배정
            currentGroup = { slotIdx: 0, messages: [m] };
            result.push(currentGroup);
        }
    }

    return result;
}
