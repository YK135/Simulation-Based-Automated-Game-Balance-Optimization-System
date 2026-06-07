/* battle/BattleSidePanel.js — 좌측 ATB 바 + 펜타곤 차트 */

// 좌측 ATB 바 + 펜타곤 차트
function renderBattleSidePanel(bs) {
    const p = state.player;
    const enemiesArr = bs.enemies || [];
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

    updateBattlePentagon(bs);
}

// ── 펜타곤 차트: 플레이어 vs 적(다대일이면 평균×위협보정) ──
function updateBattlePentagon(bs) {
    const p = state.player;
    const enemiesArr = bs.enemies || [];
    const aliveEnemies = enemiesArr.filter(e => e.alive);
    if (aliveEnemies.length > 0) {
        const avg = (key) => aliveEnemies.reduce((s, e) => s + (e[key] || 0), 0) / aliveEnemies.length;
        const avgStg = avg('stg'), avgArm = avg('arm'),
              avgSpd = avg('spd'), avgLuc = avg('luc'), avgSp = avg('sp');

        const threatMul = Math.sqrt(aliveEnemies.length);
        const norm = v => Math.min(1, Math.max(0.1, v / 50));
        const enemyVec = [
            norm(avgStg * threatMul), norm(avgArm * threatMul),
            norm(avgSpd), 0.5, norm((avgLuc + avgSp) * threatMul)
        ];
        const playerVec = [norm(p.stg), norm(p.arm), norm(p.spd),
                           0.5, norm(p.luc + p.sp)];
        updatePentagon(playerVec, enemyVec);

        const firstAlive = aliveEnemies[0];
        const baseLabel = firstAlive.difficulty_label
                          ? '['+firstAlive.difficulty_label.toUpperCase()+']'
                          : '[STABLE]';
        const multiTag = enemiesArr.length > 1 ? ` × ${aliveEnemies.length}` : '';
        document.getElementById('balance-label').textContent = baseLabel + multiTag;
    }
}