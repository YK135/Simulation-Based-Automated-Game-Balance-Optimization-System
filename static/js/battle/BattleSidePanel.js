/* battle/BattleSidePanel.js — 좌측 ATB 바 */

// 좌측 ATB 바
function renderBattleSidePanel(bs) {
    const atbFill = document.getElementById('atb-fill');
    const atbCur  = document.getElementById('atb-cur');
    const leftAtbVal = bs.player_atb !== undefined ? bs.player_atb : 0;
    const leftAtbPct = Math.min(100, Math.max(0, leftAtbVal));
    if (atbFill) {
        atbFill.style.height = leftAtbPct + '%';
        if (leftAtbPct >= 100) {
            atbFill.classList.add('full');
        } else {
            atbFill.classList.remove('full');
        }
    }
    if (atbCur) atbCur.textContent = Math.round(leftAtbVal);
}
