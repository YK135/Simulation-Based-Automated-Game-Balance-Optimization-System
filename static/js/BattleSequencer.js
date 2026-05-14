// ─────────────────────────────────────────────
// 타이밍 상수 (밀리초)
// 한 곳에서 모두 조정 가능
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

        // AoE 후속 데미지 ("└ XXX에게 N 데미지")
        if (m.trim().startsWith('└') || m.includes('에게') && m.includes('데미지')) {
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
    if (msg.includes('데미지')) return 'dmg';
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

    // ── 2. 플레이어 행동 + 모션 ──
    if (groups.player.length > 0 || isItem || isEscape) {
        // 모션 트리거 (이미지 변화)
        if (typeof setCharState === 'function') {
            if (isSkill) {
                setCharState('player_battle', 'skill', {
                    duration: SEQ_TIMING.PLAYER_ACTION + SEQ_TIMING.SKILL_MOTION_BONUS
                });
            } else if (isItem) {
                // 아이템은 별도 모션 없음 — 메시지만
            } else if (isEscape) {
                // 도망도 별도 모션 없음
            } else {
                setCharState('player_battle', 'attack', {
                    duration: SEQ_TIMING.PLAYER_ACTION
                });
            }
        }

        // 메시지 출력
        for (const m of groups.player) {
            logLine(m, _msgCls(m));
        }

        // 모션 시간만큼 대기
        let actionTime = SEQ_TIMING.PLAYER_ACTION;
        if (isSkill) actionTime += SEQ_TIMING.SKILL_MOTION_BONUS;
        if (isItem) actionTime = SEQ_TIMING.ITEM_USE;
        if (isEscape) actionTime = SEQ_TIMING.ESCAPE_TRY;
        await _seqSleep(actionTime);
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

        // 적들에게 hurt 적용
        if (typeof setCharState === 'function') {
            for (const slotIdx of damagedSlots) {
                // 슬롯이 살아있는 적인지 확인
                const en = bs.enemies && bs.enemies[slotIdx];
                if (en && en.alive) {
                    setCharState(`enemy_battle:${slotIdx}`, 'hurt', {
                        duration: SEQ_TIMING.DAMAGE_APPLY
                    });
                }
            }
        }

        // 메시지 출력
        for (const m of groups.damage) {
            logLine(m, _msgCls(m));
        }

        await _seqSleep(SEQ_TIMING.DAMAGE_APPLY);
    }

    // ── 4. 적 사망 처리 ──
    if (groups.enemy_dead.length > 0) {
        // 죽은 적 슬롯에 dead 상태
        if (typeof setDeadState === 'function') {
            (bs.enemies || []).forEach((en, i) => {
                if (en && !en.alive) {
                    setDeadState(`enemy_battle:${i}`);
                }
            });
        }

        for (const m of groups.enemy_dead) {
            logLine(m, _msgCls(m));
        }

        await _seqSleep(SEQ_TIMING.ENEMY_DEAD);
    }

    // ── 5. 적 행동 처리 (다대일은 적별로 순차) ──
    if (groups.enemy.length > 0) {
        // 적 행동 메시지를 적별로 분리
        const enemyMessages = _splitEnemyMessages(groups.enemy, bs);

        for (const enemyGroup of enemyMessages) {
            const { slotIdx, messages: emsgs } = enemyGroup;

            // 적 모션 (attack/skill)
            if (typeof setCharState === 'function' && slotIdx !== null) {
                // 스킬 메시지인지 확인
                const isEnemySkill = emsgs.some(m =>
                    m.includes('홀리볼트') || m.includes('사제힐') || m.includes('사제축복') ||
                    m.includes('1') || m.includes('2')  // 스킬명에 숫자 포함
                );
                const motionState = isEnemySkill ? 'skill' : 'attack';
                setCharState(`enemy_battle:${slotIdx}`, motionState, {
                    duration: SEQ_TIMING.ENEMY_ACTION
                });
            }

            // 메시지 출력
            for (const m of emsgs) {
                logLine(m, _msgCls(m));
            }

            // 모션 시간 대기
            await _seqSleep(SEQ_TIMING.ENEMY_ACTION);

            // ── 6. 플레이어 피격 (적 행동 결과) ──
            // 플레이어 HP 메시지가 있으면 피격
            const playerHurtMsg = groups.player_hurt.shift();  // 적별로 하나씩 소비
            if (playerHurtMsg) {
                // 플레이어 hurt 표정 + 배틀 이미지
                if (typeof setCharState === 'function') {
                    setCharState('player_battle', 'hurt', {
                        duration: SEQ_TIMING.PLAYER_HURT
                    });
                    setCharState('player_panel', 'hurt', {
                        duration: SEQ_TIMING.PLAYER_HURT + 100
                    });
                }
                logLine(playerHurtMsg, _msgCls(playerHurtMsg));
                await _seqSleep(SEQ_TIMING.PLAYER_HURT);
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
        // 플레이어 사망이면 dead
        if (typeof setDeadState === 'function') {
            const playerDied = groups.ending.some(m => m.includes('쓰러졌다'));
            if (playerDied) {
                setDeadState('player_battle');
                setDeadState('player_panel');
            }
        }

        for (const m of groups.ending) {
            logLine(m, _msgCls(m));
        }
        await _seqSleep(SEQ_TIMING.NEXT_TURN_GAP);
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
