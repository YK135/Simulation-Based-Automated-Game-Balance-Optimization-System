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
                if (!m.includes('회피') && /\d+ 데미지/.test(m)) {
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
        if (/[가-힣\w]+ 사용/.test(m) && !m.includes('아이템')) {
            playerSkillUsed = true;
            playerActed = true;
            continue;
        }

        // 적 데미지: "└ XXX에게 ... 데미지" (AoE 후속 적) 또는 "XXX HP: NNN"
        for (const [name, slotIdx] of Object.entries(enemyNameToSlot)) {
            if (m.includes(name + '에게') && /\d+ 데미지/.test(m)) {
                damagedEnemies.add(slotIdx);
            }
            if (m.includes(name + ' HP:') && /HP: 0/.test(m)) {
                deadEnemies.add(slotIdx);
            }
        }

        // 일반 플레이어 공격 메시지 ("→ NN 데미지")
        if (/^→ \d+ 데미지/.test(m) || /^\s*→ \d+/.test(m)) {
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
    }
}

// ※ 예전엔 여기 _updateBattleSprite(raw img.src 갱신)가 있었는데, 스프라이트시트
//   메타({src,type:'sheet',...})를 문자열로 착각해 깨진 src를 만들고 이모지
//   폴백을 잠깐 보여주는 버그가 있었음. BattleRender.js가 이제 CharSprite.js의
//   setCharState를 직접 쓰도록 바꾸면서 이 함수는 제거함 (더 이상 호출부 없음).