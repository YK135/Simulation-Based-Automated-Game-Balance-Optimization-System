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

    // 이미지 경로/메타 조회 (문자열 또는 sprite sheet 객체)
    const rawImg = (typeof getCharImage === 'function')
        ? getCharImage(section, charName, stateName)
        : null;
    const meta = _normalizeSpriteMeta(rawImg);   // {src, type, frames, fps, loop, frameWidth, frameHeight} | null

    const imgEl  = _getImageElement(section, slotIdx);
    const iconEl = _getIconElement(section, slotIdx);

    if (!imgEl && !iconEl) return;

    // fallback 순서: sprite sheet 재생 → 단일 PNG → 이모지
    if (meta && meta.src && imgEl) {
        if (meta.type === 'sheet' && meta.frames > 1) {
            _playSheet(imgEl, iconEl, meta);          // sprite sheet 애니메이션
        } else {
            _playStatic(imgEl, iconEl, meta.src);     // 단일 PNG (기존 동작과 동일)
        }
    } else if (iconEl) {
        // 매핑에 이미지 경로 없음 — 이모지 표시
        if (imgEl) { imgEl.style.display = 'none'; imgEl.style.backgroundImage = ''; }
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



// ═══════════════════════════════════════════════════════════
// 스프라이트 메타 정규화 + 재생 helper (정지 PNG / sprite sheet 둘 다 지원)
//   - 문자열 경로     → {src, type:'static'}
//   - 객체 메타       → 그대로 (type:'sheet' 가능)
//   - null/undefined  → null (호출부에서 이모지 폴백)
// ═══════════════════════════════════════════════════════════

function _normalizeSpriteMeta(value) {
    if (!value) return null;
    if (typeof value === 'string') {
        return { src: value, type: 'static' };
    }
    if (typeof value === 'object' && value.src) {
        return {
            src:         value.src,
            type:        value.type || 'static',
            frames:      value.frames || 1,
            fps:         value.fps || 8,
            loop:        value.loop !== false,           // 기본 true
            frameWidth:  value.frameWidth || null,
            frameHeight: value.frameHeight || null,
        };
    }
    return null;
}

// 단일 PNG 표시 (기존 동작과 동일 — <img src>)
function _playStatic(imgEl, iconEl, src) {
    _clearSheet(imgEl);                               // sheet 잔여 제거
    imgEl.src = src;
    imgEl.style.display = '';
    imgEl.onerror = function () {
        this.style.display = 'none';
        if (iconEl) iconEl.style.display = '';
    };
    imgEl.onload = function () {
        if (iconEl) iconEl.style.display = 'none';
    };
}

// sprite sheet 재생 — 가로 배열 프레임을 background-position steps()로 전환
//   <img>의 src는 비우고 background-image로 시트를 깐다.
//   ★ 슬롯 크기 보존: imgEl의 CSS width/height(예 100x130)는 건드리지 않고,
//     background-size를 (frames*100%) auto 로 잡아 프레임 1칸이 슬롯에 꽉 차게 한다.
//     → frameWidth 픽셀값에 상관없이 기존 전투 슬롯 레이아웃 유지.
//   이미지 로드 실패 시 이모지 폴백.
let _sheetSeq = 0;
function _playSheet(imgEl, iconEl, meta) {
    const probe = new Image();
    const frames = meta.frames || 1;
    const seqId = ++_sheetSeq;
    imgEl.dataset.sheetSeq = String(seqId);

    probe.onload = function () {
        if (imgEl.dataset.sheetSeq !== String(seqId)) return;  // 더 최신 상태로 교체됨
        imgEl.removeAttribute('src');                 // <img> 자체 이미지 제거 (background로 표시)
        imgEl.style.display = '';
        imgEl.style.backgroundImage = "url('" + meta.src + "')";
        imgEl.style.backgroundRepeat = 'no-repeat';
        // 슬롯 크기 유지: 프레임 1칸 = 슬롯 너비. 가로 frames칸 시트.
        imgEl.style.backgroundSize = (frames * 100) + '% 100%';
        imgEl.style.backgroundPosition = '0 0';
        // steps 애니메이션 (background-position을 %로 이동 → 슬롯 크기 무관)
        const animName = 'sheet-' + seqId;
        _injectSheetKeyframes(animName, frames);
        const dur = (frames / (meta.fps || 8)).toFixed(3) + 's';
        const iter = meta.loop ? 'infinite' : '1';
        const fill = meta.loop ? 'none' : 'forwards';
        imgEl.style.animation = animName + ' ' + dur + ' steps(' + frames + ') ' + iter + ' ' + fill;
        if (iconEl) iconEl.style.display = 'none';
    };
    probe.onerror = function () {
        if (imgEl.dataset.sheetSeq !== String(seqId)) return;
        _clearSheet(imgEl);
        imgEl.style.display = 'none';
        if (iconEl) iconEl.style.display = '';
    };
    probe.src = meta.src;
}

// 시트 잔여 스타일 제거 (단일 PNG로 돌아갈 때 호출)
function _clearSheet(imgEl) {
    imgEl.style.backgroundImage = '';
    imgEl.style.backgroundSize = '';
    imgEl.style.backgroundPosition = '';
    imgEl.style.animation = '';
}

// steps 키프레임 동적 주입 — background-position % 기반 (슬롯 크기 무관)
//   N프레임: 0% → -(N-1)*100%? 아니다. background-size가 (N*100%)이므로
//   position-x는 0%에서 100%까지 이동하면 마지막 프레임에 닿는다 (CSS % 특성).
const _injectedSheetAnims = {};
function _injectSheetKeyframes(name, frames) {
    if (_injectedSheetAnims[name]) return;
    // background-size-x = frames*100% 일 때, background-position-x: 100%는
    // 마지막 프레임을 정렬한다 (CSS background %는 (container-img)*pct 기준).
    const css = '@keyframes ' + name + ' { from { background-position-x: 0%; } to { background-position-x: 100%; } }';
    let styleEl = document.getElementById('sprite-sheet-keyframes');
    if (!styleEl) {
        styleEl = document.createElement('style');
        styleEl.id = 'sprite-sheet-keyframes';
        document.head.appendChild(styleEl);
    }
    styleEl.appendChild(document.createTextNode(css));
    _injectedSheetAnims[name] = true;
}