/* ═══════════════════════════════════════════════════════════
   SidePanel.js — 우측 컬럼: 모험 기록 + 몬스터 도감
   (구 Pentagon.js/AI Monitor 로직 대체)
   - logAdventure(msg, type): 모험 기록에 한 줄 추가 (세션 동안만 유지)
   - recordBestiaryKill(deadNames, battleMessages): 전투 승리 시 호출
       1) 처치한 몬스터 → 이름/기본 설명(line 1) 해금
       2) 그 몬스터의 discovery.match(battleMessages, name)가 true면
          → 약점/특성 설명(line 2) 추가 해금
     (둘 다 localStorage로 영구 보존 — 이미 해금된 것도 매 승리마다 재시도해서
      전에 못 찾았던 discovery를 나중에 채울 수 있음)
   ═══════════════════════════════════════════════════════════ */

// ─────────────────────────────────────────────────────────
// 몬스터 도감 데이터 — CHAR_IMAGES.enemy_battle과 동일한 키 사용
//   tip: 처치 시 해금되는 기본 설명 (line 1)
//   discovery: { tip, match(battleMessages, name) } — 존재하는 몬스터만
//              전투 중 특정 상성/약점을 실제로 발동시키고 승리해야 해금 (line 2)
// ─────────────────────────────────────────────────────────
const BESTIARY_DATA = [
    { name: '고블린',     icon: '👺',
      tip: '초반 전투의 기준이 되는 표준형 몬스터. 특별한 상성은 없다.' },

    { name: '박쥐',       icon: '🦇',
      tip: 'HP는 낮지만 디버프와 속도가 위협적이다. 빠르게 처치하는 것이 유리하다.' },

    { name: '슬라임',     icon: '🟢',
      tip: '물리 피해를 일부 흡수한다. 마법 공격이 더 잘 통한다.' },

    { name: '화염 슬라임', icon: '🔥',
      tip: '화염 계열 공격은 무효화된다.',
      discovery: {
          tip: '번개 공격으로 과부하 반응을 일으키면 큰 추가 피해를 줄 수 있다.',
          match: (msgs) => msgs.some(m => m.includes('과부하')),
      } },

    { name: '빙결 슬라임', icon: '❄',
      tip: '빙결 계열 공격은 무효화된다.',
      discovery: {
          tip: '화염 공격으로 융해, 물리 공격으로 파쇄를 유도할 수 있다.',
          match: (msgs) => msgs.some(m => m.includes('융해') || m.includes('파쇄')),
      } },

    { name: '번개 슬라임', icon: '⚡',
      tip: '번개 계열 공격은 무효화된다.',
      discovery: {
          tip: '화염 공격으로 과부하 반응을 일으킬 수 있다.',
          match: (msgs) => msgs.some(m => m.includes('과부하')),
      } },

    { name: '골렘',       icon: '🗿',
      tip: '느리지만 방어력이 매우 높은 탱커형 몬스터.',
      discovery: {
          tip: '기본 공격을 2회 연속으로 맞으면 그로기 상태가 되어 방어력이 크게 떨어진다.',
          match: (msgs, name) => msgs.some(m => m.includes(name) && m.includes('그로기')),
      } },

    { name: '유령',       icon: '👻',
      tip: '회피율이 매우 높아 공격이 잘 빗나간다.',
      discovery: {
          tip: '연속공격 계열 스킬로 여러 번 몰아치면, 맞을수록 회피율이 낮아져 뒤로 갈수록 잘 맞는다.',
          match: (msgs, name) => msgs.some(m => m.includes(name)) && msgs.some(m => m.includes('연속공격')),
      } },

    { name: '암살자',     icon: '🥷',
      tip: '행운과 치명타 확률이 매우 높다. 장기전으로 끌면 위험하니 빠르게 처치하자.' },

    { name: '사제',       icon: '⚕',
      tip: '아군을 회복·강화한다. 다수 전투에서는 최우선 처치 대상.' },

    { name: '중간 보스',  icon: '👹',
      tip: '오래 버티는 지구전형 보스.' },

    { name: '최종 보스',  icon: '🐉',
      tip: '모든 상성 저항을 갖춘 최종 관문.' },
];

const BESTIARY_KILLED_KEY     = 'bestiary_killed';
const BESTIARY_DISCOVERED_KEY = 'bestiary_discovered';

function _loadSet(key) {
    try {
        const raw = localStorage.getItem(key);
        return new Set(raw ? JSON.parse(raw) : []);
    } catch (e) {
        return new Set();
    }
}
function _saveSet(key, set) {
    try { localStorage.setItem(key, JSON.stringify([...set])); } catch (e) {}
}

// 전투 승리 시 호출 — deadNames: 이번 전투에서 처치한 몬스터 이름 배열(중복 가능)
//                    battleMessages: 이번 전투 전체에서 쌓인 로그 메시지 배열
function recordBestiaryKill(deadNames, battleMessages) {
    if (!deadNames || !deadNames.length) return;
    const killed     = _loadSet(BESTIARY_KILLED_KEY);
    const discovered = _loadSet(BESTIARY_DISCOVERED_KEY);
    const msgs = battleMessages || [];
    let changed = false;

    [...new Set(deadNames)].forEach(name => {
        const entry = BESTIARY_DATA.find(e => e.name === name);
        if (!entry) return;

        if (!killed.has(name)) {
            killed.add(name);
            changed = true;
            if (typeof toast === 'function') toast(`📖 도감에 등록됨: ${name}`, 'ok');
        }

        if (entry.discovery && !discovered.has(name) && entry.discovery.match(msgs, name)) {
            discovered.add(name);
            changed = true;
            if (typeof toast === 'function') toast(`🔍 약점 발견: ${name}`, 'ok');
        }
    });

    if (changed) {
        _saveSet(BESTIARY_KILLED_KEY, killed);
        _saveSet(BESTIARY_DISCOVERED_KEY, discovered);
        renderBestiary();
    }
}

function renderBestiary() {
    const listEl = document.getElementById('bestiary-list');
    if (!listEl) return;
    const killed     = _loadSet(BESTIARY_KILLED_KEY);
    const discovered = _loadSet(BESTIARY_DISCOVERED_KEY);
    listEl.innerHTML = '';

    BESTIARY_DATA.forEach(entry => {
        const known = killed.has(entry.name);
        const row = document.createElement('div');
        row.className = 'bestiary-entry' + (known ? '' : ' unknown');

        const iconEl = document.createElement('div');
        iconEl.className = 'bestiary-icon';
        if (known && typeof getCharImage === 'function') {
            const imgPath = getCharImage('enemy_battle', entry.name, 'idle');
            const src = typeof imgPath === 'string' ? imgPath : (imgPath && imgPath.src);
            if (src) {
                const img = document.createElement('img');
                img.src = src;
                img.alt = '';
                img.addEventListener('error', () => { img.remove(); iconEl.textContent = entry.icon; });
                iconEl.appendChild(img);
            } else {
                iconEl.textContent = entry.icon;
            }
        } else {
            iconEl.textContent = known ? entry.icon : '?';
        }
        row.appendChild(iconEl);

        const body = document.createElement('div');
        body.className = 'bestiary-body';
        const nameEl = document.createElement('div');
        nameEl.className = 'bestiary-name';
        nameEl.textContent = known ? entry.name : '???';
        body.appendChild(nameEl);

        const tipEl = document.createElement('div');
        tipEl.className = 'bestiary-tip';
        tipEl.textContent = known ? entry.tip : '아직 처치한 적이 없다.';
        body.appendChild(tipEl);

        // discovery(약점/특성) 줄 — 존재하는 몬스터만, 발견했을 때만 추가
        if (known && entry.discovery) {
            const discTipEl = document.createElement('div');
            discTipEl.className = 'bestiary-tip bestiary-discovery';
            if (discovered.has(entry.name)) {
                discTipEl.textContent = '🔍 ' + entry.discovery.tip;
            } else {
                discTipEl.textContent = '🔍 ???（전투 중 발견하면 해금됩니다）';
                discTipEl.classList.add('undiscovered');
            }
            body.appendChild(discTipEl);
        }

        row.appendChild(body);
        listEl.appendChild(row);
    });
}

// ─────────────────────────────────────────────────────────
// 모험 기록 — 주요 이벤트만 (매 공격 로그는 배틀 로그(#log-area)가 담당)
// ─────────────────────────────────────────────────────────
function logAdventure(msg, type = '') {
    const el = document.getElementById('adventure-log');
    if (!el) return;
    const d = new Date();
    const ts = String(d.getHours()).padStart(2, '0') + ':' +
               String(d.getMinutes()).padStart(2, '0');
    const line = document.createElement('div');
    line.className = 'adv-line ' + type;
    line.innerHTML = `<span class="adv-ts">${ts}</span><span>${escapeHtml(msg)}</span>`;
    el.appendChild(line);
    while (el.children.length > 30) el.removeChild(el.firstChild);
}

renderBestiary();
