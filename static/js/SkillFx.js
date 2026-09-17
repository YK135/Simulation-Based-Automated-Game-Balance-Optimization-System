/* SkillFx.js — 시전 이펙트 시트 재생 (Combat Content Brief 12장)
   ─────────────────────────────────────────────────────────
   서버의 구조화 필드만 읽는다 — bs.action_fx(시전당 1개)와 bs.hits(대상 × 종류별 1개).
   한글 메시지는 절대 파싱하지 않는다(12-1의 함정).

   층 규칙(12-1):
     RULE 1  시전 이펙트는 시전당 1회 — playSkillFx(bs.action_fx). 와이드 AoE도 1장.
     RULE 2  숫자는 「대상 × 종류」별 1개 — BattleEffects.playHitFeedback()이 담당(여기 아님).
     RULE 3  플래시는 피해 대상별 1회 — 마찬가지로 BattleEffects.
     반응 이펙트는 대상별 1회(playReactionFx — hits의 reaction 필드), DoT 틱은 틱마다 1회(playDotFx).

   에셋 자리(12-3의 14계열)는 FX_SHEETS의 src로 비워 두었다. src가 비어 있으면 모든 함수가
   즉시 0을 돌려주고 아무것도 그리지 않는다 — 에셋 0장으로도 게임은 그대로 동작하고,
   경로만 채우면 이펙트가 나온다(12-4 폴백). 규격도 12-4 그대로: 가로 1열 스트립 PNG,
   {frames, fps}로 재생 시간 계산, impact_frame으로 임팩트 정렬, 동시 재생 상한 4.

   재생 방식은 CharSprite.js의 시트 재생(background-size (frames×100%) + steps 키프레임)을
   그대로 쓴다 — _injectSheetKeyframes()를 공유하므로 새 렌더링 경로가 없다.
   로드 순서: CharSprite.js 다음, BattleSequencer.js 이전 (시퀀서가 impact_frame 리드를 읽는다). */

/* ── 14계열 에셋 표 (12-3) — src는 비워 둔다. 에셋이 들어오면 "img/fx/<파일>"로 채운다.
     frames·fps·frameW·frameH·blend·anchor·impact_frame은 12-3/12-4 규격.
       anchor : center(슬롯 중앙) | chest(가슴 높이) | feet(발밑) | top(슬롯 상단)
                | bottom(슬롯 중앙 하단) | whole(슬롯 전체) | area(적 영역 전체 — 와이드)
       blend  : screen(발광계) | normal(물리계)
       impact_frame : 시트에서 실제로 "닿는" 프레임 — 시퀀서가 임팩트 시점 − impact_frame/fps에 시작 */
const FX_SHEETS = {
    slash:      { src: '', frames: 6,  fps: 16, frameW: 128, frameH: 128, blend: 'normal', anchor: 'center', impact_frame: 3 },
    slash_wide: { src: '', frames: 8,  fps: 18, frameW: 384, frameH: 128, blend: 'normal', anchor: 'area',   impact_frame: 3 },
    fire:       { src: '', frames: 8,  fps: 14, frameW: 128, frameH: 128, blend: 'screen', anchor: 'chest',  impact_frame: 3 },
    ice:        { src: '', frames: 8,  fps: 14, frameW: 128, frameH: 128, blend: 'screen', anchor: 'chest',  impact_frame: 3 },
    lightning:  { src: '', frames: 7,  fps: 16, frameW: 128, frameH: 128, blend: 'screen', anchor: 'top',    impact_frame: 2 },
    impact:     { src: '', frames: 6,  fps: 14, frameW: 128, frameH: 128, blend: 'normal', anchor: 'bottom', impact_frame: 2 },
    holy:       { src: '', frames: 6,  fps: 12, frameW: 128, frameH: 128, blend: 'screen', anchor: 'chest',  impact_frame: 2 },
    heal:       { src: '', frames: 10, fps: 10, frameW: 128, frameH: 128, blend: 'screen', anchor: 'feet',   impact_frame: 0 },
    buff:       { src: '', frames: 10, fps: 10, frameW: 128, frameH: 128, blend: 'screen', anchor: 'feet',   impact_frame: 0 },
    debuff:     { src: '', frames: 8,  fps: 10, frameW: 128, frameH: 128, blend: 'normal', anchor: 'top',    impact_frame: 0 },
    shield:     { src: '', frames: 8,  fps: 12, frameW: 128, frameH: 128, blend: 'screen', anchor: 'whole',  impact_frame: 0 },
    explosion:  { src: '', frames: 10, fps: 16, frameW: 384, frameH: 128, blend: 'screen', anchor: 'area',   impact_frame: 3 },
    react:      { src: '', frames: 6,  fps: 18, frameW: 128, frameH: 128, blend: 'screen', anchor: 'center', impact_frame: 0 },
    dot:        { src: '', frames: 4,  fps: 8,  frameW: 64,  frameH: 64,  blend: 'screen', anchor: 'chest',  impact_frame: 0 },
};

/* ── 스킬/아이템/행동 이름 → 계열 (12-3의 "대상 스킬" 열 그대로)
     tint  : CSS filter 문자열 — 한 시트를 색만 바꿔 재사용(스탯별 버프 색, MP 포션 청색 등)
     scale : 상위 티어는 시트를 새로 만들지 않고 키운다(파이어볼2 = 1.35)
     flip  : 급소찌르기는 참격 각도를 반대로 (도적 = 찌르기 느낌)
   서버 action_fx.name은 스킬명(괄호 접미 제거) / 아이템명 / 기본공격은 "basic_attack". */
const SKILL_FX = {
    // slash
    basic_attack: { family: 'slash' },
    '강타1': { family: 'slash' }, '강타2': { family: 'slash', scale: 1.2 },
    '급소찌르기1': { family: 'slash', flip: true }, '급소찌르기2': { family: 'slash', flip: true, scale: 1.2 },
    '연속찌르기': { family: 'slash', flip: true },
    '연속공격1': { family: 'slash' }, '연속공격2': { family: 'slash', scale: 1.2 },
    // slash_wide
    '슬래시1': { family: 'slash_wide' }, '슬래시2': { family: 'slash_wide' },
    '난사1': { family: 'slash_wide' }, '난사2': { family: 'slash_wide' },
    // fire / ice / lightning (스킬 + 원소병)
    '파이어볼1': { family: 'fire' }, '파이어볼2': { family: 'fire', scale: 1.35 }, fire_vial: { family: 'fire' },
    '아이스볼릿1': { family: 'ice' }, '아이스볼릿2': { family: 'ice', scale: 1.35 }, ice_vial: { family: 'ice' },
    '라이트닝1': { family: 'lightning' }, '라이트닝2': { family: 'lightning', scale: 1.35 }, lightning_crystal: { family: 'lightning' },
    // impact — 둔기·충격. 중간 보스 「대지 균열」도 여기(4장) — 전용 시트가 오면 계열만 바꾼다
    '몸통박치기1': { family: 'impact' }, '몸통박치기2': { family: 'impact' }, '몸통박치기_강화': { family: 'impact', scale: 1.2 },
    '되갚기1': { family: 'impact' }, '되갚기2': { family: 'impact' },
    '대지 균열': { family: 'impact', scale: 1.3 }, '대지 균열_강화': { family: 'impact', scale: 1.5 },
    // holy
    '홀리볼트': { family: 'holy' },
    // heal (MP는 같은 시트에 청색 틴트)
    '힐1': { family: 'heal' }, '힐2': { family: 'heal', scale: 1.2 }, '사제힐': { family: 'heal' },
    HP_S_potion: { family: 'heal' }, HP_M_potion: { family: 'heal' }, HP_L_potion: { family: 'heal', scale: 1.2 },
    MP_S_potion: { family: 'heal', tint: 'hue-rotate(120deg)' }, MP_M_potion: { family: 'heal', tint: 'hue-rotate(120deg)' },
    MP_L_potion: { family: 'heal', tint: 'hue-rotate(120deg)', scale: 1.2 },
    // buff — 스탯별 틴트: stg=금(기본) / arm=청 / spd=녹 / mp=자
    '강화1': { family: 'buff' }, '강화2': { family: 'buff', scale: 1.2 },
    '수비태세1': { family: 'buff', tint: 'hue-rotate(170deg)' }, '수비태세2': { family: 'buff', tint: 'hue-rotate(170deg)', scale: 1.2 },
    '효율성1': { family: 'buff', tint: 'hue-rotate(240deg)' }, '효율성2': { family: 'buff', tint: 'hue-rotate(240deg)', scale: 1.2 },
    '추진력': { family: 'buff', tint: 'hue-rotate(80deg)' }, '사제축복': { family: 'buff' },
    focus_drug: { family: 'buff' }, haste_drug: { family: 'buff', tint: 'hue-rotate(80deg)' },
    // debuff
    '약화1': { family: 'debuff' }, '약화2': { family: 'debuff' }, '미약화1': { family: 'debuff' }, '미약화2': { family: 'debuff' },
    '저주1': { family: 'debuff' }, '저주2': { family: 'debuff' }, '둔화1': { family: 'debuff' }, '둔화2': { family: 'debuff' },
    '초음파비명': { family: 'debuff' },
    // shield
    '실드': { family: 'shield' },
    // explosion
    bomb: { family: 'explosion' }, web_bomb: { family: 'explosion' },
    // ── 신규 스킬 6종 (2차 6번) — 기존 계열 재사용, 전용 시트가 오면 계열만 바꾼다 ──
    '화염 폭풍': { family: 'explosion', tint: 'hue-rotate(-20deg) saturate(1.3)' },   // 와이드 화염
    '원소 폭발': { family: 'react', scale: 1.5 },                                       // 반응을 강제로 터뜨린다
    '방패치기':  { family: 'impact' },
    '피의 격노': { family: 'buff', tint: 'hue-rotate(320deg) saturate(1.4)' },        // 붉은 자기 강화
    '패 고치기': { family: 'buff', tint: 'hue-rotate(200deg)' },                        // 준비 행동 — 자기 대상
    '피의 수확': { family: 'slash', flip: true, tint: 'hue-rotate(330deg) saturate(1.5)' },
    // ── 남은 신규 스킬 11종 (2차 8번) — 광역은 area 계열이어야 적 영역 전체에 1장이 깔린다 ──
    '광풍 베기': { family: 'slash_wide', scale: 1.1 },
    '칼날 폭풍': { family: 'slash_wide', tint: 'hue-rotate(330deg) saturate(1.3)' },    // 2타 광역 — 시전당 1장
    '연쇄 번개': { family: 'explosion', tint: 'hue-rotate(200deg) saturate(1.4)' },    // 와이드 번개
    '혈흔 추적': { family: 'slash', flip: true, tint: 'hue-rotate(330deg) saturate(1.3)' },
    '약점 표식': { family: 'debuff', tint: 'hue-rotate(330deg)' },
    '불굴':      { family: 'shield', tint: 'hue-rotate(20deg) saturate(1.3)' },        // 자기 실드
    '철벽 의지': { family: 'buff', tint: 'hue-rotate(170deg)', scale: 1.2 },          // 받는 피해 감소 — 방어 버프 색
    '피의 맹세': { family: 'buff', tint: 'hue-rotate(320deg) saturate(1.4)', scale: 1.2 },
    '마나 장막': { family: 'shield', tint: 'hue-rotate(240deg)' },                     // MP로 받는 막 — 마나 색
    '서리 결계': { family: 'ice', tint: 'saturate(0.7) brightness(1.1)' },             // 자기 주변 서리
    '연막':      { family: 'debuff', tint: 'grayscale(1) brightness(1.2)' },           // 자기 대상 회피 — 회색 연기
    // ── 몬스터 · 최종 보스 신규 행동 (2차 3·8번) ──
    '날갯소리':     { family: 'debuff', tint: 'hue-rotate(80deg)' },                   // ATB 감소 — 속도 색
    '심연의 손아귀': { family: 'impact', tint: 'hue-rotate(260deg) brightness(0.8)', scale: 1.5 },
    '종언':         { family: 'impact', tint: 'hue-rotate(260deg) brightness(0.6)', scale: 1.8 },
};

// 반응 이펙트 틴트 — 색값은 BattleEffects.js의 _FLASH_BY_TONE과 같은 계열(융해 주황 / 과부하 보라 / 파쇄 청백)
const REACTION_FX = {
    melt:     { family: 'react', tint: 'hue-rotate(0deg)' },
    overload: { family: 'react', tint: 'hue-rotate(260deg)' },
    shatter:  { family: 'react', tint: 'hue-rotate(190deg) saturate(0.6)' },
};
// DoT 틱 이펙트 틴트 — hits.element 기준 (fire=화상, bleed=출혈, physical=균열)
const DOT_FX = {
    fire:     { family: 'dot' },
    bleed:    { family: 'dot', tint: 'hue-rotate(330deg)' },
    physical: { family: 'dot', tint: 'grayscale(1) brightness(0.8)' },
};

const FX_MAX_CONCURRENT = 4;          // 슬롯 3 + 반응 1 (12-4)
let _fxActive = 0;
let _fxLastEndAt = 0;                 // performance.now() 기준, 가장 늦게 끝나는 이펙트
const _fxLoaded = {};                 // src → true/false (프리로드 결과)

/** 에셋 프리로드 — 없는 파일은 false로 기억해 매번 404를 내지 않는다. */
function _fxPreload(src) {
    if (!src) return Promise.resolve(false);
    if (src in _fxLoaded) return Promise.resolve(_fxLoaded[src]);
    return new Promise(function (resolve) {
        const img = new Image();
        img.onload  = function () { _fxLoaded[src] = true;  resolve(true); };
        img.onerror = function () { _fxLoaded[src] = false; resolve(false); };
        img.src = src;
    });
}
// 표에 경로가 있는 시트는 미리 받아 둔다(첫 시전이 늦게 터지지 않게)
Object.keys(FX_SHEETS).forEach(function (k) { if (FX_SHEETS[k].src) _fxPreload(FX_SHEETS[k].src); });

/** action_fx → SKILL_FX 항목. 피해를 주지 않는 행동(관망·도주·실패)은 이펙트 없음. */
function _resolveSkillFx(fx) {
    if (!fx || !fx.name) return null;
    if (fx.kind !== 'skill' && fx.kind !== 'item' && fx.kind !== 'attack') return null;
    return SKILL_FX[fx.name] || null;
}

/** 대상 슬롯의 DOM 호스트 — 슬롯 id 규칙은 BattleEffects._hitHostElement와 같다. */
function _fxHost(side, slot) {
    if (typeof _hitHostElement === 'function') return _hitHostElement(side, slot);
    if (side === 'player') {
        const art = document.getElementById('player-combatant-art-img');
        return art ? art.parentElement : null;
    }
    return document.getElementById(['enemy-slot-1', 'enemy-slot-2', 'enemy-slot-3'][slot] || 'enemy-slot-1');
}

/** 시전 이펙트를 어디에, 얼마나 크게 그릴지.
    와이드(anchor area)는 시전 시 기록된 대상 슬롯의 좌우 끝을 감싸는 폭 — 살아있는 슬롯이 아니라
    action_fx.targets 기준(12-6 ②: 이번 공격으로 죽은 적도 폭에 포함, 보스전 3열 폭에도 자동으로 맞는다). */
function _fxPlacement(fx, sheet, entry) {
    const targets = (fx.targets && fx.targets.length) ? fx.targets
                  : [{ side: fx.actor, slot: fx.actor_slot }];
    if (sheet.anchor === 'area') {
        const stage = document.querySelector('.battle-stage');
        if (!stage) return null;
        const rects = targets.filter(function (t) { return t.side === 'enemy'; })
            .map(function (t) { return _fxHost('enemy', t.slot); })
            .filter(function (el) { return el && el.offsetParent !== null; })
            .map(function (el) { return el.getBoundingClientRect(); });
        if (!rects.length) return null;
        const sr = stage.getBoundingClientRect();
        const left  = Math.min.apply(null, rects.map(function (r) { return r.left; }))  - sr.left;
        const right = Math.max.apply(null, rects.map(function (r) { return r.right; })) - sr.left;
        const top   = Math.min.apply(null, rects.map(function (r) { return r.top; }))   - sr.top;
        const width = Math.max(sheet.frameW / 3, right - left);   // 1마리면 128, 3마리면 384 근처
        const height = width * (sheet.frameH / sheet.frameW);
        return { host: stage, wide: true, left: left, top: top + (rects[0].height - height) * 0.35,
                 width: width, height: height };
    }
    // 단일/자기 대상 — 첫 대상 슬롯 하나 (RULE 1: 시전당 1회. 재타겟 2마리여도 한 번)
    const t = targets[0];
    const host = _fxHost(t.side, t.slot);
    if (!host) return null;
    const scale = (entry && entry.scale) || 1;
    return { host: host, wide: false, width: sheet.frameW * scale, height: sheet.frameH * scale };
}

/** 시트 1장을 host 위에 재생하고 끝나면 제거한다. 반환: 재생 시간(ms). */
function _fxSpawn(sheet, entry, placement, extraClass) {
    if (_fxActive >= FX_MAX_CONCURRENT) return 0;
    const frames = Math.max(1, sheet.frames || 1);
    const dur = Math.round(frames / (sheet.fps || 8) * 1000);
    const el = document.createElement('div');
    el.className = 'skill-fx blend-' + (sheet.blend || 'normal')
                 + ' anchor-' + (sheet.anchor || 'center')
                 + (placement.wide ? ' wide' : '')
                 + (extraClass ? ' ' + extraClass : '');
    el.style.width  = Math.round(placement.width) + 'px';
    el.style.height = Math.round(placement.height) + 'px';
    if (placement.wide) {
        el.style.left = Math.round(placement.left) + 'px';
        el.style.top  = Math.round(placement.top) + 'px';
    }
    el.style.backgroundImage = "url('" + sheet.src + "')";
    el.style.backgroundSize = (frames * 100) + '% 100%';
    const flip = (entry && entry.flip) ? -1 : 1;
    el.style.setProperty('--fx-flip', String(flip));
    if (entry && entry.tint) el.style.filter = entry.tint;
    const animName = 'fx-sheet-' + frames;
    if (typeof _injectSheetKeyframes === 'function') _injectSheetKeyframes(animName, frames);
    el.style.animation = animName + ' ' + (dur / 1000).toFixed(3) + 's linear 1 forwards';
    placement.host.appendChild(el);
    _fxActive++;
    setTimeout(function () {
        _fxActive = Math.max(0, _fxActive - 1);
        if (el.parentElement) el.parentElement.removeChild(el);
    }, dur + 40);
    return dur;
}

/** 시전 이펙트 1회 (RULE 1).
    fx      : bs.action_fx (없으면 no-op — 상태 조회·마비 실패는 null)
    opts    : {impactAt: ms} — 호출 시점으로부터 임팩트까지의 시간. 시트는 impact_frame이 그 순간에
              오도록 (impactAt − impact_frame/fps)에 시작한다.
    반환    : 호출 시점 기준 이펙트가 끝나는 시각(ms). 에셋이 없거나 해당 없음이면 0.
    시퀀서는 반환값으로 피격·사망 대기를 늘려 이펙트가 잘리지 않게 한다. */
function playSkillFx(fx, opts) {
    opts = opts || {};
    const entry = _resolveSkillFx(fx);
    if (!entry) return 0;
    const sheet = FX_SHEETS[entry.family];
    if (!sheet || !sheet.src) return 0;                       // 에셋 자리 비어 있음 → 폴백(플래시만)
    const placement = _fxPlacement(fx, sheet, entry);
    if (!placement) return 0;
    const lead = Math.round((sheet.impact_frame || 0) / (sheet.fps || 8) * 1000);
    const dur  = Math.round(Math.max(1, sheet.frames || 1) / (sheet.fps || 8) * 1000);
    const startAt = Math.max(0, (opts.impactAt || 0) - lead);
    _fxPreload(sheet.src).then(function (ok) {
        if (!ok) return;
        setTimeout(function () { _fxSpawn(sheet, entry, placement); }, startAt);
    });
    const endsAt = startAt + dur;
    _fxLastEndAt = Math.max(_fxLastEndAt, performance.now() + endsAt);
    return endsAt;
}

/** 반응 이펙트 — 대상별 1회 (12-2 상한). hit는 bs.hits의 damage 항목. 반환: 재생 시간(ms). */
function playReactionFx(hit) {
    if (!hit || !hit.reaction) return 0;
    const entry = REACTION_FX[hit.reaction];
    const sheet = entry && FX_SHEETS[entry.family];
    if (!sheet || !sheet.src) return 0;
    const host = _fxHost(hit.target, hit.slot);
    if (!host) return 0;
    let dur = 0;
    _fxPreload(sheet.src).then(function (ok) {
        if (ok) _fxSpawn(sheet, entry, { host: host, width: sheet.frameW, height: sheet.frameH }, 'fx-react');
    });
    dur = Math.round(sheet.frames / (sheet.fps || 8) * 1000);
    _fxLastEndAt = Math.max(_fxLastEndAt, performance.now() + dur);
    return dur;
}

/** DoT 틱 이펙트 — 틱마다 작게 1회 (12-3 dot 계열). hit.via === 'dot'인 항목. */
function playDotFx(hit) {
    if (!hit || hit.via !== 'dot') return 0;
    const entry = DOT_FX[hit.element] || DOT_FX.fire;
    const sheet = FX_SHEETS[entry.family];
    if (!sheet || !sheet.src) return 0;
    const host = _fxHost(hit.target, hit.slot);
    if (!host) return 0;
    _fxPreload(sheet.src).then(function (ok) {
        if (ok) _fxSpawn(sheet, entry, { host: host, width: sheet.frameW, height: sheet.frameH }, 'fx-dot');
    });
    const dur = Math.round(sheet.frames / (sheet.fps || 8) * 1000);
    _fxLastEndAt = Math.max(_fxLastEndAt, performance.now() + dur);
    return dur;
}

/** 아직 재생 중인 이펙트가 끝나기까지 남은 시간(ms) — 사망 대기 = max(사망 시트, 이펙트) 용. */
function skillFxRemainingMs() {
    return Math.max(0, Math.round(_fxLastEndAt - performance.now()));
}
