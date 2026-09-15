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

    // ★ dead는 마지막 프레임에 정지된 채로 영구 유지되어야 함. 그런데
    //   renderEnemySlots/renderPlayerCombatant는 매 렌더(다른 객체가 행동할 때마다)
    //   죽은 슬롯에도 setCharState(...,'dead')를 계속 재호출한다 — _playSheet는
    //   호출될 때마다 새 CSS 애니메이션을 프레임 0부터 재생하므로, 죽은 지 한참
    //   지나도 매 렌더마다 첫 프레임(죽음 시트 초반 = 서 있는 자세)으로 리셋되어
    //   "반투명 대기모션으로 돌아간 것처럼" 보이는 버그가 있었다. 이미 dead면
    //   재적용을 건너뛰어 마지막 프레임에서 그대로 멈춰있게 한다.
    if (stateName === 'dead' && _spriteCurrentState[target] === 'dead') {
        return;
    }

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
            _playSheet(imgEl, iconEl, meta, charName);   // sprite sheet 애니메이션
        } else {
            _playStatic(imgEl, iconEl, meta.src, charName);  // 단일 PNG
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

/**
 * 이 target이 이미 dead 상태로 표시돼 있는지 (아직 한 번도 dead로 안
 * 바뀐 슬롯은 false — 이번에 "방금 죽었는지" 새로 죽은 건지 구분하는 데 쓰임.
 * static/js/battle/BattleRender.js의 refreshBattle deferDeathAnim 옵션 참고.
 */
function isCharDead(target) {
    return _spriteCurrentState[target] === 'dead';
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

// 단일 PNG 표시 — 로드 성공 후에만 교체한다.
//   ★ 예전엔 즉시 _clearSheet() + src 교체를 하고, 404가 확정된 뒤에야
//     onerror로 img를 숨겨 이모지를 띄웠다. 그래서 아직 그려지지 않은
//     상태(예: goblin_D=hurt)를 요청하면 피격 순간에 "멀쩡히 재생 중이던
//     idle 시트가 사라지고 → 100ms쯤 뒤 이모지로 튀는" 2단 깜빡임이
//     생겼다(실측: 숫자 t=627 / 이모지 전환 t=749 — 122ms 어긋남).
//     아트가 5상태 × 10종 다 채워지기 전까진 대부분의 피격이 이 경로라,
//     타격 연출이 구조적으로 어긋나 보였다.
//     이제 프로브로 먼저 로드해 보고, 성공하면 교체 / 실패하면 현재 화면을
//     그대로 유지한다(이미 아무것도 없을 때만 이모지 폴백).
function _playStatic(imgEl, iconEl, src, charName) {
    const probe = new Image();
    const seqId = ++_sheetSeq;
    imgEl.dataset.sheetSeq = String(seqId);

    probe.onload = function () {
        if (imgEl.dataset.sheetSeq !== String(seqId)) return;   // 더 최신 상태로 교체됨
        _clearSheet(imgEl);
        imgEl.src = src;
        imgEl.style.display = '';
        imgEl.dataset.charName = charName || '';
        if (iconEl) iconEl.style.display = 'none';
    };
    probe.onerror = function () {
        if (imgEl.dataset.sheetSeq !== String(seqId)) return;
        // 이 상태의 아트가 없음 — 같은 캐릭터를 이미 그리고 있었다면 그 화면을
        // 유지한다(피격 포즈만 없는 흔한 경우).
        //   ★ charName 확인이 필수: 확인 없이 "현재 유지"만 하면, 아트가 있는
        //     몬스터를 표시한 뒤 아트 없는 몬스터로 바뀌는 전투에서 이전
        //     몬스터 그림이 그대로 남아 엉뚱한 적이 보인다.
        const sameChar = imgEl.dataset.charName === (charName || '');
        const showingSomething = imgEl.style.display !== 'none'
            && (imgEl.classList.contains('sprite-sheet-active') || imgEl.naturalWidth > 1);
        if (!(sameChar && showingSomething)) {
            _clearSheet(imgEl);
            imgEl.removeAttribute('src');
            imgEl.style.display = 'none';
            imgEl.dataset.charName = '';
            if (iconEl) iconEl.style.display = '';
        }
    };
    probe.src = src;
}

// sprite sheet 재생 — 가로 배열 프레임을 background-position steps()로 전환
//   <img>의 src는 비우고 background-image로 시트를 깐다.
//   ★ 슬롯 크기 보존: imgEl의 CSS width/height(예 100x130)는 건드리지 않고,
//     background-size를 (frames*100%) auto 로 잡아 프레임 1칸이 슬롯에 꽉 차게 한다.
//     → frameWidth 픽셀값에 상관없이 기존 전투 슬롯 레이아웃 유지.
//   이미지 로드 실패 시 이모지 폴백.
let _sheetSeq = 0;
function _playSheet(imgEl, iconEl, meta, charName) {
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
        imgEl.dataset.charName = charName || '';
        if (iconEl) iconEl.style.display = 'none';
    };
    probe.onerror = function () {
        if (imgEl.dataset.sheetSeq !== String(seqId)) return;
        _clearSheet(imgEl);
        imgEl.style.display = 'none';
        imgEl.dataset.charName = '';
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
        // ★ mask-position-x를 같은 키프레임에 함께 선언한다 — 피격 플래시
        //   오버레이(flashHitMask)가 시트를 mask-image로 쓰면서 이 애니메이션을
        //   그대로 재사용하므로, 키프레임 하나를 스프라이트와 마스크가 공유해
        //   프레임 동기가 구조적으로 어긋날 수 없다. 별도 키프레임 두 개를
        //   각각 재생시키면 시작 시점이 미세하게 달라질 수 있음.
        const p = pos.toFixed(3) + '%';
        parts.push(
            start.toFixed(3) + '%, ' + safeEnd.toFixed(3) + '% {' +
            ' background-position-x: ' + p + ';' +
            ' mask-position-x: ' + p + ';' +
            ' -webkit-mask-position-x: ' + p + ';' +
            ' }'
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


// ═══════════════════════════════════════════════════════════
// 피격 플래시 — 스프라이트 실루엣을 단색으로 덮는 마스크 레이어
// ───────────────────────────────────────────────────────────
// 시트 모드: 같은 시트를 mask-image로 쓰고, 재생 중인 애니메이션을 그대로
//   재사용한다(_injectSheetKeyframes가 mask-position-x도 선언함). 더해서
//   Web Animations API로 원본의 currentTime을 복사해 애니메이션 중간에
//   맞아도 프레임이 정확히 일치하게 한다.
// 정지 PNG 모드: object-fit:contain과 맞추기 위해 mask-size:contain 사용.
// 이모지 폴백: 마스크할 알파가 없으므로 호출부가 CSS 클래스 플래시로 폴백.
//
// ※ 오버레이는 .combatant(position:relative) 안에 img의 offset 박스로
//   절대배치한다. .combatant.acting의 pulse(transform:scale)는 art에만
//   걸리므로 펄스 중엔 최대 몇 px 어긋날 수 있다 — 플래시가 140ms라 체감되지
//   않아 DOM 구조(5칸 그리드/보스 nth-child 규칙)를 건드리지 않는 쪽을 택했다.
// ═══════════════════════════════════════════════════════════
function flashHitMask(target, opts) {
    opts = opts || {};
    const color    = opts.color || '#ffffff';
    const duration = opts.duration || 140;

    let section = target, slotIdx = 0;
    if (target.indexOf(':') !== -1) {
        const parts = target.split(':');
        section = parts[0];
        slotIdx = parseInt(parts[1], 10) || 0;
    }

    const imgEl = _getImageElement(section, slotIdx);
    if (!imgEl || imgEl.style.display === 'none') return false;

    const host = imgEl.parentElement;
    if (!host) return false;

    const isSheet = imgEl.classList.contains('sprite-sheet-active');
    const sheetUrl = isSheet ? imgEl.style.backgroundImage : '';
    // 정지 PNG는 src가 실제 이미지(시트 모드는 1x1 투명 픽셀이라 마스크 불가).
    //   ★ 404난 경로도 src 속성은 남아 있어서, 그것만 보고 마스크를 만들면
    //     알파가 없는 투명 레이어가 생기고 호출부의 이모지 폴백(hit-punch)까지
    //     건너뛰어 "피격 표시가 아무것도 안 뜨는" 상태가 된다. 실제로 로드된
    //     이미지인지(naturalWidth) 확인한다.
    const loadedStatic = !isSheet && imgEl.complete && imgEl.naturalWidth > 1;
    const staticUrl = loadedStatic ? "url('" + imgEl.getAttribute('src') + "')" : '';
    const maskUrl = sheetUrl || staticUrl;
    if (!maskUrl) return false;

    const layer = document.createElement('div');
    layer.className = 'hit-mask-layer';
    layer.style.left   = imgEl.offsetLeft + 'px';
    layer.style.top    = imgEl.offsetTop + 'px';
    layer.style.width  = imgEl.offsetWidth + 'px';
    layer.style.height = imgEl.offsetHeight + 'px';
    layer.style.backgroundColor = color;
    layer.style.webkitMaskImage = maskUrl;
    layer.style.maskImage = maskUrl;
    layer.style.webkitMaskRepeat = 'no-repeat';
    layer.style.maskRepeat = 'no-repeat';

    if (isSheet) {
        const size = imgEl.style.backgroundSize || '100% 100%';
        layer.style.webkitMaskSize = size;
        layer.style.maskSize = size;
        layer.style.webkitMaskPosition = '0 0';
        layer.style.maskPosition = '0 0';
        // 원본과 같은 애니메이션을 그대로 재사용 (프레임 공유)
        if (imgEl.style.animation) layer.style.animation = imgEl.style.animation;
    } else {
        layer.style.webkitMaskSize = 'contain';
        layer.style.maskSize = 'contain';
        layer.style.webkitMaskPosition = 'center';
        layer.style.maskPosition = 'center';
    }

    host.appendChild(layer);

    // 애니메이션 진행 위치 동기 (중간 프레임에 맞아도 정확히 겹치게)
    if (isSheet && typeof imgEl.getAnimations === 'function') {
        try {
            const src = imgEl.getAnimations()[0];
            const dst = layer.getAnimations()[0];
            if (src && dst && src.currentTime !== null) dst.currentTime = src.currentTime;
        } catch (e) { /* Web Animations 미지원 — 시작 시점 동기로 충분 */ }
    }

    // 짧게 보였다가 페이드아웃 후 제거
    layer.style.transition = 'opacity ' + duration + 'ms ease-out';
    requestAnimationFrame(function () {
        layer.style.opacity = '0';
    });
    setTimeout(function () {
        if (layer.parentElement) layer.parentElement.removeChild(layer);
    }, duration + 60);

    return true;
}