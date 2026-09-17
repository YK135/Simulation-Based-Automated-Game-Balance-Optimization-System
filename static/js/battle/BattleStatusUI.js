/* battle/BattleStatusUI.js — 원소 색상 / 상태이상 이모지 / 이름 / 좌측 버프·디버프 */

function applyElementNameClass(el, aura) {
    if (!el) return;
    el.classList.remove('element-fire', 'element-ice', 'element-lightning');
    if (aura === 'fire')      el.classList.add('element-fire');
    else if (aura === 'ice')  el.classList.add('element-ice');
    else if (aura === 'lightning') el.classList.add('element-lightning');
}

/** 버프/디버프/상태이상 이모지 반환
 *  ※ 원소 부착(element_aura/element_queue)만으로는 이모지 미표시
 *     색상은 applyElementNameClass가 담당
 *     이모지는 실제 상태이상이 걸렸을 때만 표시
 */
function statusEmojiList(entity) {
    if (!entity) return '';
    const emojis = [];

    // 원소 상태이상 (실제 StatusEffect만)
    (entity.status_effects || []).forEach(e => {
        if (e.type === 'ignite')         emojis.push('🔥');
        else if (e.type === 'frostbite') emojis.push('❄');
        else if (e.type === 'paralyze')  emojis.push('⚡');
        else if (e.type === 'rift')      emojis.push('🌑');
        else if (e.type === 'bleed')     emojis.push('🩸' + ((e.stacks || 1) > 1 ? '×' + e.stacks : ''));
    });

    // 일반 디버프/버프
    if ((entity.debuffs || []).length > 0) emojis.push('↓');
    if ((entity.buffs   || []).length > 0) emojis.push('↑');

    return [...new Set(emojis)].join(' ');
}

/** 상태이상 아이콘 키 목록 반환 (이미지/이모지 공통)
 *  ignite/frostbite/paralyze + 버프/디버프. 원소 부착은 제외(이름 색상으로 표시). */
function getStatusIconKeys(entity) {
    if (!entity) return [];
    const keys = [];
    (entity.status_effects || []).forEach(e => {
        if (e.type === 'ignite')         keys.push('ignite');
        else if (e.type === 'frostbite') keys.push('frostbite');
        else if (e.type === 'paralyze')  keys.push('paralyze');
        else if (e.type === 'rift')      keys.push('rift');
        else if (e.type === 'bleed')     keys.push('bleed');
    });
    if ((entity.debuffs || []).length > 0) keys.push('debuff');
    if ((entity.buffs   || []).length > 0) keys.push('buff');
    return [...new Set(keys)];
}

// STATUS_ICONS(State.js)에 아직 항목이 없는 상태이상의 이모지 폴백 —
// 이미지 에셋이 들어오면 State.js 쪽 표에 넣고 여기는 그대로 둬도 된다(표가 우선).
const _STATUS_ICON_FALLBACK = {
    rift:  { icon: '🌑' },   // 중간 보스 「균열」 (ai/battle/Entity.py rift)
    bleed: { icon: '🩸' },   // 도적 출혈 — 스택은 renderNameWithStatus가 ×n으로 덧붙인다
};

function renderNameWithStatus(el, entity) {
    if (!el) return;
    applyElementNameClass(el, entity.element_aura || '');
    el.innerHTML = '';

    const nameText = document.createElement('span');
    nameText.className = 'name-text';
    nameText.textContent = entity.name;

    const iconsWrap = document.createElement('span');
    iconsWrap.className = 'name-status-icons';
    getStatusIconKeys(entity).forEach(key => {
        const meta = (typeof STATUS_ICONS !== 'undefined' ? STATUS_ICONS[key] : null)
            || _STATUS_ICON_FALLBACK[key] || { icon: '?' };
        if (typeof renderIconWithFallback === 'function') {
            iconsWrap.appendChild(renderIconWithFallback(meta, 'status-icon'));
        } else {
            iconsWrap.textContent += (meta.icon || '');
        }
        // 출혈 스택(bs.*.status_effects[].stacks — 10-4): 2스택부터 ×n을 아이콘 뒤에 붙인다
        if (key === 'bleed') {
            const bleed = (entity.status_effects || []).find(e => e.type === 'bleed');
            if (bleed && (bleed.stacks || 1) > 1) {
                const n = document.createElement('span');
                n.className = 'status-stack';
                n.textContent = '×' + bleed.stacks;
                n.title = `출혈 ${bleed.stacks}스택 — 매 행동 최대 HP ${bleed.stacks * 3}%`;
                iconsWrap.appendChild(n);
            }
        }
    });

    el.appendChild(nameText);
    el.appendChild(iconsWrap);
}

/* ── 적 패턴 배지 (예고 / 스택 / 골렘 사이클 / 그로기) ───────────
   bs.enemies[i].pattern이 실어 오는 표시 전용 파생값을 그대로 그린다.
   서버가 이미 "무엇을, 몇 칸 중 몇 칸" 형태로 정규화해 주므로 여기서는
   몬스터 종류를 전혀 모른 채 배지 배열만 렌더한다 — 새 엘리트가 늘어도
   State._pattern_badges만 고치면 이 함수는 그대로다. */
function renderPatternBadges(el, badges) {
    if (!el) return;
    badges = badges || [];
    el.innerHTML = '';
    // '' 대신 명시적으로 flex — 스타일시트 기본값(none)에 의존하지 않는다
    el.style.display = badges.length ? 'flex' : 'none';

    badges.forEach(b => {
        const max = Math.max(1, b.max || 1);
        const cur = Math.max(0, Math.min(b.cur || 0, max));

        const badge = document.createElement('span');
        badge.className = `pattern-badge kind-${b.kind || 'telegraph'} state-${b.state || 'idle'}`;
        // 스크린리더/툴팁용 — 눈으로는 칸으로, 글자로는 숫자로 읽히게
        badge.title = `${b.label} ${cur}/${max}`;

        const name = document.createElement('span');
        name.className = 'pattern-label';
        name.textContent = b.label || '';
        badge.appendChild(name);

        // max가 1이면(사제 부활 의식처럼 단발) 칸을 그리지 않는다 — 한 칸짜리
        // 게이지는 정보가 없고 배지만 넓어진다
        if (max > 1) {
            const pips = document.createElement('span');
            pips.className = 'pattern-pips';
            for (let i = 0; i < max; i++) {
                const pip = document.createElement('i');
                pip.className = 'pattern-pip' + (i < cur ? ' on' : '');
                pips.appendChild(pip);
            }
            badge.appendChild(pips);
        }
        el.appendChild(badge);
    });
}

function refreshLeftStatsBattle(bs) {
    const grid = document.getElementById('stat-grid');
    if (!grid || !state.player) return;
    const p = state.player;

    // (label, original, effective) 순서
    const rows = [
        ["STG",   p.stg,   bs.player_effective_stg ],
        ["SP",    p.sp,    p.sp                    ],  // SP는 effective 없음
        ["ARM",   p.arm,   bs.player_effective_arm ],
        ["SPARM", p.sparm, bs.player_effective_sparm],
        ["SPD",   p.spd,   bs.player_effective_spd ],
        ["LUC",   p.luc,   p.luc                   ],
    ];
    grid.innerHTML = rows.map(([label, orig, eff]) => {
        const useEff = (typeof eff === 'number') ? eff : orig;
        const changed = Math.abs(useEff - orig) > 0.5;
        return `<div class="stat-row${changed ? ' changed' : ''}">
                  <span>${label}</span>
                  <span class="v">${Math.round(useEff * 10) / 10}</span>
                </div>`;
    }).join('');
}

// ── 좌측 버프/디버프 칩 렌더 ──
//   bs.player_buffs / bs.player_debuffs (각각 [{stat, amount, turns, name}, ...])

function refreshPlayerStatusList(bs) {
    const buffsEl   = document.getElementById('player-buffs');
    const debuffsEl = document.getElementById('player-debuffs');
    if (!buffsEl || !debuffsEl) return;

    const STAT_KOR = {
        stg:'공격', arm:'방어', sparm:'마방', spd:'속도',
        mp_efficiency:'마나효율', lifesteal:'흡혈', lifesteal_oath:'맹세 흡혈',
        lifesteal_amp:'흡혈량', dmg_reduction:'피해 경감', dodge:'회피',
        mana_veil:'MP 대납', frost_ward:'서리 결계', vulnerable:'취약'
    };

    const renderChip = (s, kind) => {
        const stat = STAT_KOR[s.stat] || s.stat;
        const amt  = Math.round((s.amount || 0) * 100);
        const sign = kind === 'buff' ? '+' : '−';
        return `<span class="status-chip ${kind}" title="${s.name || ''}">
                  ${stat} ${sign}${amt}%<span class="turns">${s.turns}T</span>
                </span>`;
    };

    const buffs   = bs.player_buffs   || [];
    const debuffs = bs.player_debuffs || [];
    buffsEl.innerHTML   = buffs.map(b => renderChip(b, 'buff')).join('');
    // 마법사 원소 공명 단계(bs.player_resonance — 서버 표시용 파생값): 같은 원소 연속 시전 n/3
    const res = bs.player_resonance;
    if (res && res.stack > 0) {
        const elemKor = { fire: '화염', ice: '빙결', lightning: '번개' }[res.element] || res.element;
        const pct = Math.max(0, res.stack - 1) * 10;
        buffsEl.innerHTML += `<span class="status-chip buff resonance" title="원소 공명 — 같은 원소 연속 시전 ${res.stack}/${res.max}, 피해 +${pct}%. 다른 원소로 바꾸면 그 시전의 반응 보너스 +20%p">
                  🔮 ${elemKor} 공명<span class="turns">${res.stack}/${res.max}</span>
                </span>`;
    }
    // 도적 「패 고치기」 — 저장된 다음 주사위(bs.player_dice — 서버 표시용 파생값)
    const dice = bs.player_dice;
    if (dice && dice.pending > 0) {
        buffsEl.innerHTML += `<span class="status-chip buff dice" title="패 고치기로 정해 둔 다음 공격 주사위 — 재굴림 ${dice.rerolls_left}회 남음">
                  🎲 다음 주사위 ${dice.pending}<span class="turns">${dice.rerolls_left}회</span>
                </span>`;
    }
    debuffsEl.innerHTML = debuffs.map(d => renderChip(d, 'debuff')).join('');
}

// ═══════════════════════════════════════════════════════════
// 메시지 → 캐릭터 상태(이미지) 매핑
// ─────────────────────────────────────────────────────────
// 서버 응답의 messages를 보고 적절한 setCharState 호출.
// 한 응답에 플레이어 행동 + 적 행동이 섞여있으므로 시간차 적용:
//   - 플레이어 행동: 즉시 (0ms)
//   - 데미지 효과(hurt): 200ms 후 (공격 모션 보여준 뒤 적이 흠칫)
//   - 적 행동: 600ms 후 (플레이어 행동 다 끝나고)
// ═══════════════════════════════════════════════════════════