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
    });
    if ((entity.debuffs || []).length > 0) keys.push('debuff');
    if ((entity.buffs   || []).length > 0) keys.push('buff');
    return [...new Set(keys)];
}

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
        const meta = (typeof STATUS_ICONS !== 'undefined' ? STATUS_ICONS[key] : null) || { icon: '?' };
        if (typeof renderIconWithFallback === 'function') {
            iconsWrap.appendChild(renderIconWithFallback(meta, 'status-icon'));
        } else {
            iconsWrap.textContent += (meta.icon || '');
        }
    });

    el.appendChild(nameText);
    el.appendChild(iconsWrap);
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
        mp_efficiency:'마나효율'
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