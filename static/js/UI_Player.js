/* ═══════════════════════════════════════════════════════════
   UI_Player.js — 좌측 PLAYER 패널 UI 갱신
   ★ 완성본 (통째 교체용) ★

   - refreshPlayer: state.player 기반 좌측 패널 전체 갱신
     (HP/MP/EXP 게이지, 능력치 표, 캐릭터 초상화)
   - 직업별 이미지 자동 갱신 (CHAR_IMAGES 사용)
   - 스킬 아이콘 매핑
   ═══════════════════════════════════════════════════════════ */

function refreshPlayer() {
    if (!state.player) return;
    const p = state.player;
    document.getElementById('player-id').textContent = `${p.name} (LV ${p.lv} ${p.job})`;

    // ── 좌측 패널 캐릭터 표시 (이미지 + 이모지 폴백) ──
    // 직업이 바뀔 때마다 이미지 src를 직접 갱신.
    // CharSprite.js의 setCharState도 있지만, 여기서 직접 처리해서 안정성 보장.
    _updatePlayerPortrait(p.job);

    // ── 좌측 게이지: HP/MP/EXP ──
    document.getElementById('hp-cur').textContent = Math.round(p.hp);
    document.getElementById('hp-max').textContent = p.maxhp;
    document.getElementById('mp-cur').textContent = Math.round(p.mp);
    document.getElementById('mp-max').textContent = p.maxmp;
    document.getElementById('hp-fill').style.height = (p.hp/p.maxhp*100) + '%';
    document.getElementById('mp-fill').style.height = (p.mp/p.maxmp*100) + '%';

    // EXP 게이지 (노란색)
    const expEl = document.getElementById('exp-fill');
    if (expEl) {
        const expRatio = p.maxexp > 0 ? (p.exp / p.maxexp * 100) : 0;
        expEl.style.height = expRatio + '%';
        document.getElementById('exp-cur').textContent = Math.round(p.exp || 0);
        document.getElementById('exp-max').textContent = p.maxexp || 0;
    }

    // ── 능력치 표 (좌측 패널) ──
    document.getElementById('stat-grid').innerHTML = `
        <div class="stat-row"><span>STG</span><span class="v">${p.stg}</span></div>
        <div class="stat-row"><span>SP</span><span class="v">${p.sp}</span></div>
        <div class="stat-row"><span>ARM</span><span class="v">${p.arm}</span></div>
        <div class="stat-row"><span>SPARM</span><span class="v">${p.sparm}</span></div>
        <div class="stat-row"><span>SPD</span><span class="v">${p.spd}</span></div>
        <div class="stat-row"><span>LUC</span><span class="v">${p.luc}</span></div>
    `;

    // ── 탐험 모드 정보 카드 (인벤토리/스킬) ──
    refreshExploreInfo();
}


// ─────────────────────────────────────────────
// 직업별 좌측 패널 이미지 갱신
// ─────────────────────────────────────────────
//
// 동작:
//   1. CHAR_IMAGES.player_panel[job].idle 경로 조회
//   2. <img id="player-portrait"> 가 있으면 src 갱신
//   3. 이미지 로드 실패(onerror)면 자동 숨김 + 이모지 표시
//   4. 이모지(<div id="player-icon">)는 항상 직업에 맞게 갱신
//
// 이미지 없는 직업은 자동으로 이모지 폴백.
function _updatePlayerPortrait(job) {
    const iconEl = document.getElementById('player-icon');
    const imgEl  = document.getElementById('player-portrait');

    // 이모지 갱신 (폴백용)
    if (iconEl) {
        iconEl.textContent = JOB_ICONS[job] || '?';
    }

    // 이미지 갱신
    if (imgEl) {
        const imgPath = (typeof getCharImage === 'function')
            ? getCharImage('player_panel', job, 'idle')
            : null;

        if (imgPath) {
            // 이미지 경로가 있으면 src 갱신 + 표시
            imgEl.src = imgPath;
            imgEl.style.display = '';
            // 로드 성공 시 이모지 숨김 (onload), 실패 시 이미지 숨김 + 이모지 표시 (onerror)
            imgEl.onerror = function() {
                this.style.display = 'none';
                if (iconEl) iconEl.style.display = '';
            };
            imgEl.onload = function() {
                if (iconEl) iconEl.style.display = 'none';
            };
        } else {
            // 매핑에 경로 없으면 이미지 숨김 + 이모지 표시
            imgEl.style.display = 'none';
            if (iconEl) iconEl.style.display = '';
        }
    }
}


// 스킬 이름에 따른 아이콘 매핑
function skillIcon(sk) {
    if (sk.includes('파이어')) return '🔥';
    if (sk.includes('힐')) return '✚';
    if (sk.includes('실드')) return '⛨';
    if (sk.includes('강타')) return '⚒';
    if (sk.includes('연속')) return '⚔';
    if (sk.includes('찌르기')) return '⚡';
    if (sk.includes('아이스')) return '❄';
    if (sk.includes('라이트닝')) return '⚡';
    if (sk.includes('수비')) return '⛨';
    if (sk.includes('몸통')) return '◆';
    if (sk.includes('추진력')) return '➤';
    if (sk.includes('급소')) return '✦';
    return '★';
}