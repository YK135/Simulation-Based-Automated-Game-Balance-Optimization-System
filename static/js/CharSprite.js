// 진행 중인 idle 복귀 타이머 관리 (target별로 1개)
const _spriteTimers = {};

// 현재 적용 중인 상태 (디버그/조건 분기용)
const _spriteCurrentState = {};


/**
 * 캐릭터 이미지 상태 변경.
 * @param {string} target  'player_panel' | 'player_battle' | 'enemy_battle:N' (N=0/1/2)
 * @param {string} state   'idle' | 'hurt' | 'attack' | 'skill' | 'dead' | 'happy'
 * @param {object} opts    {duration: 400, persist: false}
 */
function setCharState(target, state, opts) {
    opts = opts || {};
    const duration = opts.duration !== undefined ? opts.duration : 400;
    const persist  = opts.persist === true;

    // target 파싱: enemy_battle:0 → section='enemy_battle', slotIdx=0
    let section, slotIdx = 0;
    if (target.includes(':')) {
        const parts = target.split(':');
        section = parts[0];
        slotIdx = parseInt(parts[1], 10) || 0;
    } else {
        section = target;
    }

    // 캐릭터 이름 결정
    let charName;
    if (section === 'player_panel' || section === 'player_battle') {
        charName = (state && state.player) ? state.player.job : (window.state?.player?.job || '전사');
    } else if (section === 'enemy_battle') {
        const bs = window.state?.battleState;
        if (bs && bs.enemies && bs.enemies[slotIdx]) {
            charName = bs.enemies[slotIdx].name;
        }
    }
    if (!charName) return;

    // 이미지 경로 조회
    const imgPath = getCharImage(section, charName, state);
    const imgEl   = _getImageElement(section, slotIdx);
    const iconEl  = _getIconElement(section, slotIdx);

    if (!imgEl && !iconEl) return;

    // 이미지가 있으면 <img> 사용, 없으면 이모지 폴백
    if (imgPath && imgEl) {
        imgEl.src = imgPath;
        imgEl.style.display = '';
        if (iconEl) iconEl.style.display = 'none';
    } else if (iconEl) {
        // 이미지 없음 — 이모지만 표시 (상태 변화는 텍스트로 못 보여줌)
        if (imgEl) imgEl.style.display = 'none';
        iconEl.style.display = '';
    }

    _spriteCurrentState[target] = state;

    // 기존 타이머 클리어
    if (_spriteTimers[target]) {
        clearTimeout(_spriteTimers[target]);
        _spriteTimers[target] = null;
    }

    // 자동 idle 복귀 (idle/dead/happy는 복귀 안 함)
    if (!persist && state !== 'idle' && state !== 'dead' && state !== 'happy') {
        _spriteTimers[target] = setTimeout(() => {
            setCharState(target, 'idle');
        }, duration);
    }
}


/**
 * happy 상태 (레벨업/아이템 획득 등) 특별 처리:
 * 자동 복귀 + 길이 조절 가능.
 * @param {string} target  'player_panel' 권장
 * @param {number} duration  표시 시간 (기본 1500ms)
 */
function showHappyState(target, duration) {
    duration = duration || 1500;
    setCharState(target, 'happy', { duration: duration, persist: false });
    // happy는 setCharState 안에서 자동 복귀 안 하므로 직접 타이머
    if (_spriteTimers[target]) clearTimeout(_spriteTimers[target]);
    _spriteTimers[target] = setTimeout(() => {
        setCharState(target, 'idle');
    }, duration);
}


/**
 * 영구 상태 (사망 시 부활할 때까지 유지).
 * @param {string} target  'player_battle' or 'enemy_battle:N'
 */
function setDeadState(target) {
    setCharState(target, 'dead', { persist: true });
}


// ─────────────────────────────────────────────
// 내부 헬퍼: DOM 요소 조회
// ─────────────────────────────────────────────

function _getImageElement(section, slotIdx) {
    if (section === 'player_panel') {
        return document.getElementById('player-portrait');
    }
    if (section === 'player_battle') {
        return document.getElementById('player-combatant-art-img');
    }
    if (section === 'enemy_battle') {
        if (slotIdx === 0) return document.getElementById('enemy-art-img');
        if (slotIdx === 1) return document.getElementById('enemy-art-2-img');
        if (slotIdx === 2) return document.getElementById('enemy-art-3-img');
    }
    return null;
}

function _getIconElement(section, slotIdx) {
    if (section === 'player_panel') {
        return document.getElementById('player-icon');
    }
    if (section === 'player_battle') {
        return document.getElementById('player-combatant-art');
    }
    if (section === 'enemy_battle') {
        if (slotIdx === 0) return document.getElementById('enemy-art');
        if (slotIdx === 1) return document.getElementById('enemy-art-2');
        if (slotIdx === 2) return document.getElementById('enemy-art-3');
    }
    return null;
}


/**
 * 전투 시작 시 모든 슬롯을 idle로 초기화.
 * 새 전투마다 호출 권장.
 */
function resetAllSprites() {
    // 진행 중인 모든 타이머 클리어
    Object.keys(_spriteTimers).forEach(k => {
        if (_spriteTimers[k]) clearTimeout(_spriteTimers[k]);
    });
    Object.keys(_spriteTimers).forEach(k => delete _spriteTimers[k]);

    // 각 슬롯을 idle로
    setCharState('player_battle', 'idle');
    for (let i = 0; i < 3; i++) {
        const slotEl = document.getElementById(`enemy-slot-${i + 1}`);
        if (slotEl && slotEl.style.display !== 'none') {
            setCharState(`enemy_battle:${i}`, 'idle');
        }
    }
}