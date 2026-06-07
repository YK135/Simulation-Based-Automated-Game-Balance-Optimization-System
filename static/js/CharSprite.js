// idle 복귀 타이머 관리 (target별 1개)
const _spriteTimers = {};
const _spriteCurrentState = {};


/**
 * 캐릭터 이미지 상태 변경
 * @param {string} target     'player_panel' | 'player_battle' | 'enemy_battle:N'
 * @param {string} stateName  'idle' | 'hurt' | 'attack' | 'skill' | 'dead' | 'happy'
 * @param {object} opts       { duration: 400, persist: false }
 */
function setCharState(target, stateName, opts) {
    opts = opts || {};
    const duration = opts.duration !== undefined ? opts.duration : 400;
    const persist  = opts.persist === true;

    // target 파싱
    let section, slotIdx = 0;
    if (target.indexOf(':') !== -1) {
        const parts = target.split(':');
        section = parts[0];
        slotIdx = parseInt(parts[1], 10) || 0;
    } else {
        section = target;
    }

    // 캐릭터 이름 결정 (전역 state 안전 접근)
    const gameState = window.state || {};
    let charName;
    if (section === 'player_panel' || section === 'player_battle') {
        charName = (gameState.player && gameState.player.job) || '전사';
    } else if (section === 'enemy_battle') {
        const bs = gameState.battleState;
        if (bs && bs.enemies && bs.enemies[slotIdx]) {
            charName = bs.enemies[slotIdx].name;
        }
    }
    if (!charName) return;

    // 이미지 경로 조회
    const imgPath = (typeof getCharImage === 'function')
        ? getCharImage(section, charName, stateName)
        : null;

    const imgEl  = _getImageElement(section, slotIdx);
    const iconEl = _getIconElement(section, slotIdx);

    if (!imgEl && !iconEl) return;

    // 이미지 있으면 <img> 사용, 없으면 이모지 폴백
    if (imgPath && imgEl) {
        imgEl.src = imgPath;
        imgEl.style.display = '';
        imgEl.onerror = function() {
            // 이미지 로드 실패 시 자동으로 이모지로 폴백
            this.style.display = 'none';
            if (iconEl) iconEl.style.display = '';
        };
        imgEl.onload = function() {
            if (iconEl) iconEl.style.display = 'none';
        };
    } else if (iconEl) {
        // 매핑에 이미지 경로 없음 — 이모지 표시
        if (imgEl) imgEl.style.display = 'none';
        iconEl.style.display = '';
    }

    _spriteCurrentState[target] = stateName;

    // 기존 타이머 클리어
    if (_spriteTimers[target]) {
        clearTimeout(_spriteTimers[target]);
        _spriteTimers[target] = null;
    }

    // 자동 idle 복귀 (idle/dead/happy는 복귀 안 함)
    if (!persist && stateName !== 'idle' && stateName !== 'dead' && stateName !== 'happy') {
        _spriteTimers[target] = setTimeout(function() {
            setCharState(target, 'idle');
        }, duration);
    }
}


/**
 * happy 상태 (레벨업/아이템 획득 등) — 지정 시간 후 idle 복귀
 * @param {string} target
 * @param {number} duration 표시 시간 ms (기본 1500)
 */
function showHappyState(target, duration) {
    duration = duration || 1500;
    setCharState(target, 'happy', { duration: duration, persist: false });
    if (_spriteTimers[target]) clearTimeout(_spriteTimers[target]);
    _spriteTimers[target] = setTimeout(function() {
        setCharState(target, 'idle');
    }, duration);
}


/**
 * 사망 상태 (영구 유지)
 */
function setDeadState(target) {
    setCharState(target, 'dead', { persist: true });
}


// ─────────────────────────────────────────────
// DOM 요소 조회
// ───────────────────────────────────────────
// <img> id 규칙: 원본 id + '-img' 접미사
//   원본 div: enemy-art        ← 이모지 폴백용
//   img 태그: enemy-art-img    ← 실제 이미지
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
 * 모든 슬롯을 idle로 초기화 (새 전투 시작 시 등)
 */
function resetAllSprites() {
    // 타이머 클리어
    Object.keys(_spriteTimers).forEach(function(k) {
        if (_spriteTimers[k]) clearTimeout(_spriteTimers[k]);
    });
    Object.keys(_spriteTimers).forEach(function(k) {
        delete _spriteTimers[k];
    });

    setCharState('player_battle', 'idle');
    for (let i = 0; i < 3; i++) {
        const slotEl = document.getElementById('enemy-slot-' + (i + 1));
        if (slotEl && slotEl.style.display !== 'none') {
            setCharState('enemy_battle:' + i, 'idle');
        }
    }
}


// ─────────────────────────────────────────────
// 이미지 폴백 바인딩 (index.html 인라인 onerror 제거 대체)
//   data-fallback-id 속성을 가진 <img>에 error 핸들러 연결.
//   ※ setCharState()가 src 세팅 시 imgEl.onerror를 별도로 덮어쓰므로
//     공존 가능(여기는 초기/미갱신 이미지용 안전망).
// ─────────────────────────────────────────────
function bindImageFallbacks() {
    document.querySelectorAll('img[data-fallback-id]').forEach(function (img) {
        img.addEventListener('error', function () {
            img.style.display = 'none';
            var fb = document.getElementById(img.dataset.fallbackId);
            if (fb) fb.style.display = '';
        });
    });
}

document.addEventListener('DOMContentLoaded', bindImageFallbacks);