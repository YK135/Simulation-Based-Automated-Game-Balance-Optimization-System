/* ═══════════════════════════════════════════════════════════
   pentagon.js — AI Monitor 펜타곤 차트
   - drawPentagonBackground: 5겹 배경 + 축선 + 라벨
   - pentagonPoints: 5개 좌표 계산
   - updatePentagon: 이상치/현재치 갱신

   축: POWER / DEFENSE / SPEED / TIME / RESOURCE
   ═══════════════════════════════════════════════════════════ */

function pentagonPoints(cx, cy, r, values=null) {
    const pts = [];
    for (let i = 0; i < 5; i++) {
        const angle = -Math.PI/2 + (2*Math.PI/5) * i;
        const radius = values ? r * Math.max(0.05, Math.min(1, values[i])) : r;
        pts.push((cx + Math.cos(angle)*radius).toFixed(1) + ',' +
                 (cy + Math.sin(angle)*radius).toFixed(1));
    }
    return pts.join(' ');
}

function drawPentagonBackground() {
    const cx = 110, cy = 110;
    const labels = ['POWER', 'DEFENSE', 'SPEED', 'TIME', 'RESOURCE'];
    const bgGroup = document.getElementById('pentagon-bg');
    const lblGroup = document.getElementById('pentagon-labels');
    bgGroup.innerHTML = '';
    lblGroup.innerHTML = '';

    // 5겹 배경 펜타곤
    [80, 60, 40, 20].forEach(r => {
        const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
        poly.setAttribute('points', pentagonPoints(cx, cy, r));
        poly.setAttribute('fill', 'none');
        poly.setAttribute('stroke', '#1e3a4a');
        poly.setAttribute('stroke-width', '0.8');
        bgGroup.appendChild(poly);
    });

    // 축선 + 라벨
    for (let i = 0; i < 5; i++) {
        const angle = -Math.PI/2 + (2*Math.PI/5) * i;
        const x = cx + Math.cos(angle) * 80;
        const y = cy + Math.sin(angle) * 80;

        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', cx); line.setAttribute('y1', cy);
        line.setAttribute('x2', x);  line.setAttribute('y2', y);
        line.setAttribute('stroke', '#1e3a4a');
        line.setAttribute('stroke-width', '0.6');
        bgGroup.appendChild(line);

        const lx = cx + Math.cos(angle) * 96;
        const ly = cy + Math.sin(angle) * 96;
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', lx); text.setAttribute('y', ly);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('dominant-baseline', 'middle');
        text.setAttribute('font-size', '8');
        text.setAttribute('font-family', 'monospace');
        text.setAttribute('font-weight', '700');
        text.setAttribute('fill', '#7a96a3');
        text.textContent = labels[i];
        lblGroup.appendChild(text);
    }
}

function updatePentagon(idealVals, currentVals) {
    document.getElementById('pentagon-ideal').setAttribute(
        'points', pentagonPoints(110, 110, 80, idealVals));
    document.getElementById('pentagon-current').setAttribute(
        'points', pentagonPoints(110, 110, 80, currentVals));
}