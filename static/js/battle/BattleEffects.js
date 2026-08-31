/* ═══════════════════════════════════════════════════════════
   battle/BattleEffects.js — 메시지 기반 캐릭터 스프라이트 상태 전환
   ═══════════════════════════════════════════════════════════ */

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

// ※ 예전엔 여기 _updateBattleSprite(raw img.src 갱신)가 있었는데, 스프라이트시트
//   메타({src,type:'sheet',...})를 문자열로 착각해 깨진 src를 만들고 이모지
//   폴백을 잠깐 보여주는 버그가 있었음. BattleRender.js가 이제 CharSprite.js의
//   setCharState를 직접 쓰도록 바꾸면서 이 함수는 제거함 (더 이상 호출부 없음).