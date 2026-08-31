// idle 복귀 타이머 관리 (target별 1개)
const _spriteTimers = {};
const _spriteCurrentState = {};

// 1x1 투명 PNG — 스프라이트시트 모드에서 <img src>를 완전히 비우면 브라우저가
// 기본 "깨진 이미지" 장식을 그리므로, 유효한(그러나 안 보이는) src로 채워둔다.
// 하드코딩된 base64 문자열은 오타로 불투명 픽셀이 되기 쉬워, 캔버스로 직접
// 생성해 확실히 투명한 PNG를 만든다(1x1 캔버스의 기본값은 완전 투명).
const _TRANSPARENT_PIXEL = (function () {
    const c = document.createElement('canvas');
    c.width = 1; c.height = 1;
    return c.toDataURL('image/png');
})();


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
        if (imgEl) {
            if (typeof _clearSheet === 'function') _clearSheet(imgEl);
            imgEl.removeAttribute('src');     // src="" 잔여로 깨진 박스 생기는 것 방지
            imgEl.style.display = 'none';
        }
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
        // ★ src를 완전히 지우면(removeAttribute) 브라우저가 <img>에 기본
        //   "깨진 이미지" 테두리/아이콘을 그린다 — background-image로 실제
        //   그림을 깔아도 그 장식은 그대로 남아있음. 1x1 투명 픽셀로 채워서
        //   "정상 로드된 이미지" 취급을 받게 해 그 장식을 없앤다.
        imgEl.src = _TRANSPARENT_PIXEL;
        // ★ src가 있어도(위 1x1 픽셀) CSS 안전망이 "src=''"만 걸러내진 않으므로
        //   이 클래스로 시트 모드임을 명시해 관련 규칙에서 안전하게 예외 처리.
        imgEl.classList.add('sprite-sheet-active');
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
        imgEl.style.animation = animName + ' ' + dur + ' linear ' + iter + ' ' + fill;
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
    imgEl.classList.remove('sprite-sheet-active');
}

// steps 키프레임 동적 주입 — background-position % 기반 (슬롯 크기 무관)
//   N프레임: 0% → -(N-1)*100%? 아니다. background-size가 (N*100%)이므로
//   position-x는 0%에서 100%까지 이동하면 마지막 프레임에 닿는다 (CSS % 특성).
const _injectedSheetAnims = {};
function _injectSheetKeyframes(name, frames) {
    if (_injectedSheetAnims[name]) return;
    // 프레임별 구간을 명시 → linear 재생 시 각 프레임이 정확히 고정된다.
    //   background-size-x = frames*100% 이므로 프레임 i의 position-x는
    //   (i/(frames-1))*100% (CSS background % 정렬 규칙).
    //   시간 구간 [i/frames, (i+1)/frames)에 그 위치를 고정.
    frames = Math.max(1, frames || 1);
    const parts = [];
    for (let i = 0; i < frames; i++) {
        const start = (i / frames) * 100;
        const end   = ((i + 1) / frames) * 100;
        const pos   = frames <= 1 ? 0 : (i / (frames - 1)) * 100;
        const safeEnd = (i === frames - 1) ? end : end - 0.001;
        parts.push(
            start.toFixed(3) + '%, ' + safeEnd.toFixed(3) + '% { background-position-x: ' + pos.toFixed(3) + '%; }'
        );
    }
    const css = '@keyframes ' + name + ' { ' + parts.join(' ') + ' }';
    let styleEl = document.getElementById('sprite-sheet-keyframes');
    if (!styleEl) {
        styleEl = document.createElement('style');
        styleEl.id = 'sprite-sheet-keyframes';
        document.head.appendChild(styleEl);
    }
    styleEl.appendChild(document.createTextNode(css));
    _injectedSheetAnims[name] = true;
}