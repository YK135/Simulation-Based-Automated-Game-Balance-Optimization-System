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