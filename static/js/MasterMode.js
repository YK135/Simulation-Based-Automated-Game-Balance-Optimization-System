/* ═══════════════════════════════════════════════════════════
   MasterMode.js — 로컬 전용 디버그 패널 (레벨업 / 보스전 / 지정 몬스터전)
   서버가 MASTER_MODE로 부팅됐을 때만 /api/master/status가 200을 반환함 —
   그 외(라우트 자체가 없어 404)에는 패널을 계속 숨겨둔다.
   ═══════════════════════════════════════════════════════════ */

let _masterModeEnabled = false;
let _masterActionProcessing = false;

async function _initMasterMode() {
    const r = await api('/master/status');
    if (!r.ok) return;

    _masterModeEnabled = true;
    const panel = document.getElementById('master-panel');
    if (panel) panel.hidden = false;

    const sel = document.getElementById('master-monster-select');
    if (sel && Array.isArray(r.monsters)) {
        sel.innerHTML = r.monsters
            .map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
            .join('');
    }

    refreshMasterPanel();
}

/** state.inBattle 변화에 맞춰 패널 버튼 활성/비활성 동기화.
 *  UI_Player.js의 refreshPlayer()가 refreshInventoryPanel()과 같은 시점에 호출함. */
function refreshMasterPanel() {
    if (!_masterModeEnabled) return;
    const disabled = !!state.inBattle || _masterActionProcessing;
    document.querySelectorAll('#master-panel button, #master-panel select').forEach(el => {
        el.disabled = disabled;
    });
}

async function _masterLevelUp() {
    if (state.inBattle || _masterActionProcessing) return;
    _masterActionProcessing = true;
    refreshMasterPanel();
    try {
        const r = await api('/master/level_up', {});
        if (!r.ok) { toast(r.error || '레벨업 실패', 'error'); return; }
        state.player = r.player;
        if (typeof refreshPlayer === 'function') refreshPlayer();
        if (typeof checkPendingPoints === 'function') checkPendingPoints();
        toast(`Lv.${r.player.lv}로 레벨업!`, 'info');
    } finally {
        _masterActionProcessing = false;
        refreshMasterPanel();
    }
}

/* /map/choose의 handleNodeResult() "battle"/"boss" 분기와 동일한 처리 —
   맵 노드가 아니라 마스터 모드에서 열었다는 것만 다름. */
function _masterEnterBattle(r) {
    hideMapMode();
    state.battleMessages = [];
    if (r.battle_state && typeof refreshBattle === 'function') {
        refreshBattle(r.battle_state);
        if (typeof _kickoffBattleTurn === 'function') _kickoffBattleTurn(r.battle_state);
    }
}

async function _masterStartBoss(which) {
    if (state.inBattle || _masterActionProcessing) return;
    _masterActionProcessing = true;
    refreshMasterPanel();
    try {
        const r = await api('/master/battle/boss', { boss: which });
        if (!r.ok) { toast(r.error || '전투 시작 실패', 'error'); return; }
        logLine(`⚔ ${r.enemy?.name || '보스'}이(가) 나타났다!`, 'crit');
        _masterEnterBattle(r);
    } finally {
        _masterActionProcessing = false;
        refreshMasterPanel();
    }
}

async function _masterStartMonsterBattle() {
    if (state.inBattle || _masterActionProcessing) return;
    const sel = document.getElementById('master-monster-select');
    const gradeSel = document.getElementById('master-grade-select');
    const monster_type = sel ? sel.value : null;
    const grade = gradeSel ? gradeSel.value : '중';
    if (!monster_type) return;

    _masterActionProcessing = true;
    refreshMasterPanel();
    try {
        const r = await api('/master/battle/monster', { monster_type, grade });
        if (!r.ok) { toast(r.error || '전투 시작 실패', 'error'); return; }
        logLine(`⚔ ${r.enemy?.name || '적'}이(가) 나타났다!`, 'crit');
        _masterEnterBattle(r);
    } finally {
        _masterActionProcessing = false;
        refreshMasterPanel();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    _initMasterMode();

    const btnLevelUp = document.getElementById('master-btn-levelup');
    if (btnLevelUp) btnLevelUp.onclick = _masterLevelUp;

    const btnMid = document.getElementById('master-btn-midboss');
    if (btnMid) btnMid.onclick = () => _masterStartBoss('mid');

    const btnFinal = document.getElementById('master-btn-finalboss');
    if (btnFinal) btnFinal.onclick = () => _masterStartBoss('final');

    const btnMonster = document.getElementById('master-btn-monster');
    if (btnMonster) btnMonster.onclick = _masterStartMonsterBattle;
});
