// ═══════════════════════════════════════════════════════════
// RelicModal.js — 유물 3종 택 1 선택 팝업 (Combat Content Brief 7장)
// ───────────────────────────────────────────────────────────
// 엘리트·보스 승리 응답의 result.relic_offer = {ticket_id, choices:[{id,name,icon,desc}], gold_alt}
// 를 받아 카드 3장 + "골드로 환전" 버튼을 띄운다. 고르면 POST /api/relic/choose
// {ticket_id, relic_id} — 서버가 티켓으로 검증하므로 여기서 보내는 값은 id뿐이다.
// openRelicChoice(offer)는 서버 응답을 받은 뒤 resolve되는 Promise — showRewardModal()/
// openStatAllocate()와 같은 패턴이라 Actions.js가 순서대로 await한다.
// 유물의 이름·아이콘·설명은 전부 서버가 내려주는 값 — 프론트 표(State.js)를 늘리지 않는다.
// ═══════════════════════════════════════════════════════════

let _relicResolvePending = null;
let _relicSending = false;

function openRelicChoice(offer) {
    return new Promise((resolve) => {
        const modal = document.getElementById('modal-relic');
        if (!modal || !offer || !Array.isArray(offer.choices) || !offer.choices.length) { resolve(); return; }
        _relicResolvePending = resolve;
        _relicSending = false;

        const list = document.getElementById('relic-choice-list');
        list.innerHTML = '';
        offer.choices.forEach(c => {
            const card = document.createElement('div');
            card.className = 'relic-card';
            card.dataset.relicId = c.id;
            card.innerHTML = `
                <div class="relic-card-icon">${c.icon || '✦'}</div>
                <div class="relic-card-name"></div>
                <div class="relic-card-desc"></div>`;
            card.querySelector('.relic-card-name').textContent = c.name;
            card.querySelector('.relic-card-desc').textContent = c.desc;
            card.addEventListener('click', () => _relicSubmit(offer.ticket_id, c.id));
            list.appendChild(card);
        });

        const goldBtn = document.getElementById('relic-gold-btn');
        goldBtn.textContent = `전부 거절하고 골드로 환전 (+${offer.gold_alt || 0} G)`;
        goldBtn.onclick = () => _relicSubmit(offer.ticket_id, 'gold');

        modal.classList.add('active');
    });
}

async function _relicSubmit(ticketId, relicId) {
    if (_relicSending) return;
    _relicSending = true;
    document.querySelectorAll('#modal-relic .relic-card').forEach(el => el.style.pointerEvents = 'none');
    try {
        const r = await api('/relic/choose', { ticket_id: ticketId, relic_id: relicId });
        if (!r.ok) {
            toast(r.error || '유물 선택 실패', 'error');
            _relicSending = false;
            document.querySelectorAll('#modal-relic .relic-card').forEach(el => el.style.pointerEvents = '');
            return;     // 티켓은 서버에 남아 있으므로 다시 고를 수 있다
        }
        if (r.player) state.player = r.player;
        if (typeof refreshPlayer === 'function') refreshPlayer();   // 골드는 api()가 반영
        if (r.message) {
            logLine(r.message, 'heal');
            if (typeof logAdventure === 'function') logAdventure(r.message, 'loot');
            toast(r.message, 'ok');
        }
    } catch (e) {
        console.error('[relic]', e);
    }
    _relicClose();
}

function _relicClose() {
    const modal = document.getElementById('modal-relic');
    if (modal) modal.classList.remove('active');
    const resolve = _relicResolvePending;
    _relicResolvePending = null;
    _relicSending = false;
    if (resolve) resolve();
}

/** 좌측 플레이어 패널의 유물 줄 — state.player.relics = [{id,name,icon,desc}] (서버 값 그대로) */
function renderPlayerRelics(p) {
    const row = document.getElementById('player-relics');
    if (!row) return;
    const relics = (p && p.relics) || [];
    row.innerHTML = '';
    row.style.display = relics.length ? '' : 'none';
    relics.forEach(r => {
        const chip = document.createElement('span');
        chip.className = 'relic-chip';
        chip.title = `${r.name} — ${r.desc}`;
        chip.textContent = `${r.icon || '✦'} ${r.name}`;
        row.appendChild(chip);
    });
}
