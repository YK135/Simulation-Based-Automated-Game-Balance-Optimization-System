/* ═══════════════════════════════════════════════════════════
   battle/BattleEffects.js — 메시지 기반 캐릭터 스프라이트 상태 전환
   ═══════════════════════════════════════════════════════════ */

/* 스프라이트 상태 전환 — 서버의 구조화 필드(bs.hits / bs.action_fx)만 본다.
   ★ 예전엔 로그 문장에서 적 이름을 찾아 슬롯을 정했는데(이름 → 슬롯 맵),
     같은 종류가 여럿인 전투에서는 이름이 겹쳐 엉뚱한 슬롯이 움직였다
     (박쥐 3마리 중 하나만 맞아도 다른 박쥐가 피격 모션, 죽은 박쥐가 공격 모션).
     hits는 「대상 × 종류」별 1건이고 slot을, action_fx는 행동한 쪽과 슬롯을
     직접 들고 있다(ai/battle_session/State.py) — 메시지는 이제 로그 출력에만 쓴다.
   보통 경로(Actions.js)는 messages를 비운 채 refreshBattle을 부르므로 이 함수는
   시퀀서가 없는 경로(세션 복구·맵 복귀 폴백)에서만 실제로 동작한다. */
function _triggerSpriteStates(bs) {
    if (!bs || !bs.enemies) return;
    const enemies = bs.enemies || [];
    const hits = bs.hits || [];
    const fx = bs.action_fx || null;
    const isCast = (kind) => kind === 'skill' || kind === 'item';

    // 1) 행동한 쪽의 모션 — 살아 있는 슬롯에만
    if (fx && fx.actor === 'player') {
        setCharState('player_battle', isCast(fx.kind) ? 'skill' : 'attack');
    } else if (fx && fx.actor === 'enemy' && fx.actor_slot >= 0) {
        const actor = enemies[fx.actor_slot];
        if (actor && actor.alive) {
            _scheduleSetState(`enemy_battle:${fx.actor_slot}`, isCast(fx.kind) ? 'skill' : 'attack', 600);
        }
    }

    // 2) 적 피격 (200ms 후 — 공격 모션을 보여준 뒤)
    const damaged = new Set(hits
        .filter(h => h && h.target === 'enemy' && h.kind === 'damage' && h.slot >= 0)
        .map(h => h.slot));
    setTimeout(() => {
        damaged.forEach(slotIdx => {
            const en = enemies[slotIdx];
            if (en && en.alive) setCharState(`enemy_battle:${slotIdx}`, 'hurt');
        });
    }, 200);

    // 3) 적 사망 (300ms 후) — 달아난 개체는 시체 포즈 대상이 아니다
    setTimeout(() => {
        enemies.forEach((en, i) => {
            if (en && !en.alive && !en.fled) setDeadState(`enemy_battle:${i}`);
        });
    }, 300);

    // 4) 플레이어 피격 / 사망
    const playerHurt = hits.some(h => h && h.target === 'player' && h.kind === 'damage');
    const playerDead = bs.player_hp <= 0;
    if (playerHurt && !playerDead) {
        setTimeout(() => {
            setCharState('player_battle', 'hurt');
            setCharState('player_panel', 'hurt', { duration: 600 });
        }, 700);
    }
    if (playerDead) {
        setTimeout(() => setDeadState('player_battle'), 900);
    }
}

// 헬퍼: 일정 시간 후 setCharState 호출

function _scheduleSetState(target, state, delay) {
    setTimeout(() => setCharState(target, state), delay);
}


/* ═══════════════════════════════════════════════════════════
   데미지 숫자 팝업 + 피격 플래시
   ───────────────────────────────────────────────────────────
   서버 응답의 구조화 필드 bs.hits를 그대로 쓴다 (한글 메시지 파싱 없음).
     hits: [{target:'player'|'enemy', slot, amount, kind, crit,
             element, reaction, via}]
     kind:     'damage' | 'heal' | 'shield'
     element:  'fire' | 'ice' | 'lightning' | 'physical' | 'bleed' | ''
     reaction: 'melt' | 'shatter' | 'overload' | ''
     via:      'attack' | 'skill' | 'item' | 'dot' | ''
   호출 시점은 BattleSequencer의 "데미지 적용 + hurt" 단계 — hurt 시트가
   시작되는 그 프레임에 숫자와 플래시가 같이 뜬다.
   ═══════════════════════════════════════════════════════════ */

// 슬롯 DOM 조회 — CharSprite.js의 id 규칙과 동일하게 유지해야 함.
function _hitHostElement(target, slot) {
    if (target === 'player') {
        const art = document.getElementById('player-combatant-art-img')
                 || document.getElementById('player-combatant-art');
        return art ? art.parentElement : null;
    }
    const ids = ['enemy-slot-1', 'enemy-slot-2', 'enemy-slot-3'];
    return document.getElementById(ids[slot] || ids[0]);
}

const _HIT_STYLE = {
    damage: { cls: 'dmg',    sign: '',  color: null },
    heal:   { cls: 'heal',   sign: '+', color: null },
    shield: { cls: 'shield', sign: '+', color: null },
};

/* ── 데미지 숫자 색(tone) 결정 ──────────────────────────────
   우선순위: 원소 반응 > 원소 > 행동 종류.
     반응이 최우선인 이유 — 반응은 원소 조합으로만 나오는 "잘한 플레이"라
     그 한 방을 즉시 알아봐야 한다(마법사 정체성).
   실제 색값은 static/css/battle/BattleCombatant.css의 .tone-* 규칙에 있다
   (JS는 클래스명만 정하고 색은 CSS 한 곳에서만 관리 — 두 곳에 색을 두면
   테마 수정 때 어긋난다). 플래시 색만 CSS 변수를 읽을 수 없어 여기 둔다. */
const _TONE_BY_REACTION = {
    melt:     'tone-melt',
    overload: 'tone-overload',
    shatter:  'tone-shatter',
};
const _TONE_BY_ELEMENT = {
    fire:      'tone-fire',
    ice:       'tone-ice',
    lightning: 'tone-lightning',
    bleed:     'tone-bleed',      // 도적 출혈 — 엔진 원소는 아니고 표시용 값
};
const _TONE_BY_VIA = {
    skill: 'tone-skill',          // 무원소 물리 스킬 (강타/연속공격/몸통박치기…)
    item:  'tone-item',           // 폭탄류 (무원소)
};
// 실루엣 마스크 플래시 색 — .tone-*의 대표색과 같은 계열로 맞춘다
const _FLASH_BY_TONE = {
    'tone-melt':      '#ffc089',
    'tone-overload':  '#d7a8ff',
    'tone-shatter':   '#dcf3ff',
    'tone-fire':      '#ffa478',
    'tone-ice':       '#93e4f7',
    'tone-lightning': '#ffe68a',
    'tone-bleed':     '#ff8b9c',
    'tone-skill':     '#fff0c4',
    'tone-item':      '#ebe2cb',
    'tone-physical':  '#ffffff',
};
const _REACTION_LABEL = { melt: '융해', overload: '과부하', shatter: '파쇄' };

/** 반응 라벨 — 같은 대상에게 한 step에 여러 번 터졌으면 횟수를 붙인다.
    숫자는 대상당 1개로 합쳐지므로(연속공격 4타도 숫자 하나) 라벨이 횟수를
    대신 전한다. hit.reaction_count는 서버 장부(State._hits_from_snapshot)가 센 값. */
function _reactionTag(hit) {
    const name = _REACTION_LABEL[hit.reaction];
    if (!name) return '';
    const n = (hit.reaction_count || {})[hit.reaction] || 0;
    return n > 1 ? `${name} ×${n}` : name;
}

function _hitToneClass(hit) {
    if (!hit) return 'tone-physical';
    return _TONE_BY_REACTION[hit.reaction]
        || _TONE_BY_ELEMENT[hit.element]
        // physical / 무원소는 기본 공격인지 스킬인지로만 나눈다
        || _TONE_BY_VIA[hit.via]
        || 'tone-physical';
}

/** 숫자 하나를 슬롯 위에 띄움 (CSS 애니메이션으로 상승+페이드)
    opts: {tone, tagLabel, yOffset} — 색/반응 라벨/세로 위치 */
function showDamagePopup(target, slot, amount, kind, isCrit, index, opts) {
    const host = _hitHostElement(target, slot);
    if (!host || !amount) return;
    opts = opts || {};

    const style = _HIT_STYLE[kind] || _HIT_STYLE.damage;
    const el = document.createElement('div');
    el.className = 'dmg-popup ' + style.cls
                 + (opts.tone ? ' ' + opts.tone : '')
                 + (isCrit ? ' crit' : '');

    // 반응(융해/과부하/파쇄)은 숫자 위에 작은 라벨을 얹는다 — 색만으로는
    // 화염과 융해처럼 인접한 색조를 구분하기 어렵다.
    if (opts.tagLabel) {
        const lab = document.createElement('span');
        lab.className = 'dmg-popup-tag';
        lab.textContent = opts.tagLabel;
        el.appendChild(lab);
    }
    const num = document.createElement('span');
    num.className = 'dmg-popup-num';
    num.textContent = style.sign + amount;
    el.appendChild(num);

    // 여러 숫자가 겹치지 않게 흩뿌림 — 좌우는 번갈아, 세로는 호출부가 누적해
    // 넘겨준 yOffset만큼 더 높이 띄운다(라벨 있는 팝업은 더 높아서 간격이 다름).
    const spread = (index % 2 === 0 ? 1 : -1) * (10 + index * 6);
    el.style.setProperty('--dx', spread + 'px');
    el.style.top = (-12 - (opts.yOffset || 0)) + 'px';
    el.style.animationDelay = (index * 90) + 'ms';

    host.appendChild(el);
    setTimeout(function () {
        if (el.parentElement) el.parentElement.removeChild(el);
    }, 1200 + index * 90);
}

/** 피격 플래시 — 스프라이트가 있으면 실루엣 마스크, 없으면 CSS 클래스 폴백 */
function flashHitOn(target, slot, isCrit, tone) {
    const charTarget = (target === 'player') ? 'player_battle' : ('enemy_battle:' + slot);
    const color = _FLASH_BY_TONE[tone] || '#ffffff';
    const masked = (typeof flashHitMask === 'function')
        ? flashHitMask(charTarget, { color: color, duration: isCrit ? 200 : 140 })
        : false;

    if (masked) return;

    // 이모지 폴백 — 마스크할 알파가 없으므로 슬롯 전체를 짧게 때린다.
    //   ★ filter로 하면 .combatant-art에 이미 걸린 drop-shadow(발광)를
    //     덮어써서 사라지므로, 두 filter를 합성해 둔 CSS 클래스를 쓴다.
    //     (원소별 색은 마스크 경로에서만 반영 — 이모지엔 칠할 실루엣이 없다)
    const host = _hitHostElement(target, slot);
    if (!host) return;
    host.classList.remove('hit-punch');
    void host.offsetWidth;            // reflow — 연속 피격에도 매번 재생
    host.classList.add('hit-punch');
    setTimeout(function () { host.classList.remove('hit-punch'); }, 260);
}

// 세로 간격 — 치명타 글자(38px)가 아래 숫자를 덮지 않을 만큼. 반응 라벨이
// 붙은 팝업은 라벨 높이만큼 더 차지하므로 따로 잡는다.
const _POPUP_STEP_Y     = 34;
const _POPUP_STEP_Y_TAG = 48;

/** bs.hits 전체를 재생 (숫자 + 플래시). 대상별로 index/세로위치를 나눠 겹침 방지 */
function playHitFeedback(hits, filterTarget) {
    if (!Array.isArray(hits) || hits.length === 0) return;

    const perHost = {};      // 슬롯별 팝업 개수 (좌우 흩뿌림/지연용)
    const perHostY = {};     // 슬롯별 누적 세로 오프셋
    for (const h of hits) {
        if (!h || !h.amount) continue;
        if (filterTarget && h.target !== filterTarget) continue;

        const key = h.target + ':' + h.slot;
        perHost[key]  = (perHost[key]  || 0);
        perHostY[key] = (perHostY[key] || 0);

        // 색/라벨은 피해에만 — 회복(초록)·실드(파랑)는 kind가 곧 의미다
        const isDamage = h.kind === 'damage';
        const tone = isDamage ? _hitToneClass(h) : '';
        const tagLabel = isDamage ? _reactionTag(h) : '';

        showDamagePopup(h.target, h.slot, h.amount, h.kind, h.crit, perHost[key],
                        { tone: tone, tagLabel: tagLabel, yOffset: perHostY[key] });
        perHost[key]++;
        perHostY[key] += tagLabel ? _POPUP_STEP_Y_TAG : _POPUP_STEP_Y;

        if (isDamage) flashHitOn(h.target, h.slot, h.crit, tone);

        // 반응 이펙트는 대상별 1회(12-2 상한 — hits가 이미 대상×종류 단위라 그대로 1회),
        // DoT 틱 이펙트는 틱마다 1회. 둘 다 에셋이 없으면 SkillFx가 no-op (플래시만 남는다).
        if (isDamage && h.reaction && typeof playReactionFx === 'function') playReactionFx(h);
        if (h.via === 'dot' && typeof playDotFx === 'function') playDotFx(h);
    }
}

// ※ 예전엔 여기 _updateBattleSprite(raw img.src 갱신)가 있었는데, 스프라이트시트
//   메타({src,type:'sheet',...})를 문자열로 착각해 깨진 src를 만들고 이모지
//   폴백을 잠깐 보여주는 버그가 있었음. BattleRender.js가 이제 CharSprite.js의
//   setCharState를 직접 쓰도록 바꾸면서 이 함수는 제거함 (더 이상 호출부 없음).