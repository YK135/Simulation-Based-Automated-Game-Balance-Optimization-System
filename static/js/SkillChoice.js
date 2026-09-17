// ═══════════════════════════════════════════════════════════
// SkillChoice.js — 스킬 2택 1 선택 팝업 (Combat Content Brief 10-6)
// ───────────────────────────────────────────────────────────
// 레벨업으로 선택 지점(game/Lv.py JOB_SKILL_CHOICES)에 닿으면 서버가
// state.player.pending_skill_choices = [{lv, options:[{name, mp, type, desc}]}]를 내려준다.
// 한 레벨씩 카드 두 장을 보여주고, 고르면 POST /api/skill/choose {lv, skill} — 서버가 대기열로 검증한다.
// 고르지 않은 쪽은 그 런에서 다시 배울 수 없으므로 닫기 버튼은 없다(선택이 곧 닫기).
// checkPendingSkillChoices()는 대기열이 빌 때 resolve되는 Promise — checkPendingPoints()가 스탯 분배 뒤에 부른다.
// ═══════════════════════════════════════════════════════════

let _scResolve = null;
let _scSending = false;

function checkPendingSkillChoices() {
    const list = (state.player && state.player.pending_skill_choices) || [];
    if (!list.length) return Promise.resolve();
    return new Promise(resolve => {
        _scResolve = resolve;
        _scRender(list[0]);
    });
}

function _scRender(choice) {
    const modal = document.getElementById('modal-skill-choice');
    if (!modal) { _scDone(); return; }
    document.getElementById('sc-level').textContent = `Lv ${choice.lv}`;
    const box = document.getElementById('sc-options');
    box.innerHTML = '';
    choice.options.forEach(opt => {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'sc-card';
        const name = document.createElement('div');
        name.className = 'sc-name';
        name.textContent = opt.name;
        const cost = document.createElement('div');
        cost.className = 'sc-cost';
        cost.textContent = opt.mp > 0 ? `MP ${opt.mp}` : (opt.hp_cost > 0 ? `현재 HP ${opt.hp_cost}%` : '');
        const desc = document.createElement('div');
        desc.className = 'sc-desc';
        desc.textContent = opt.desc || '';
        card.append(name, cost, desc);
        card.addEventListener('click', () => _scSubmit(choice.lv, opt.name));
        box.appendChild(card);
    });
    _scSending = false;
    modal.classList.add('active');
}

async function _scSubmit(lv, skill) {
    if (_scSending) return;
    _scSending = true;
    try {
        const r = await api('/skill/choose', { lv, skill });
        if (!r.ok) {
            toast(r.error || '스킬 선택 실패', 'error');
            _scSending = false;
            return;
        }
        if (r.player) state.player = r.player;
        if (typeof refreshPlayer === 'function') refreshPlayer();
        logLine(`📘 ${r.message}`, 'skill');
        if (typeof logAdventure === 'function') logAdventure(`스킬 선택: ${skill}`, 'loot');
        toast(r.message, 'ok');
    } catch (e) {
        console.error('[skillChoice]', e);
        _scSending = false;
        return;
    }
    const next = (state.player.pending_skill_choices || [])[0];
    if (next) _scRender(next);
    else _scDone();
}

function _scDone() {
    const modal = document.getElementById('modal-skill-choice');
    if (modal) modal.classList.remove('active');
    const resolve = _scResolve;
    _scResolve = null;
    if (resolve) resolve();
}
