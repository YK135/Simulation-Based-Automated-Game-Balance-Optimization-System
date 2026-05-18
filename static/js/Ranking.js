/* ═══════════════════════════════════════════════════════════
   Ranking.js — 랭킹 모달 제어
   ─────────────────────────────────────────────────────────
   ★ 신규 파일 ★
   경로: static/js/Ranking.js
   index.html에 <script> 추가 필요

   기능:
   - 랭킹 모달 열기/닫기
   - 좌우 화살표로 두 가지 랭킹 토글:
     [점수 랭킹] ↔ [선구자 랭킹 (최초 클리어)]
   - 매번 열 때 실시간 API 호출
   ═══════════════════════════════════════════════════════════ */

// 현재 보고 있는 랭킹 종류
let _currentRankingType = "score";   // "score" | "pioneers"


// ─────────────────────────────────────────────
// 랭킹 모달 열기
// ─────────────────────────────────────────────
async function openRankingModal() {
    const modal = document.getElementById('modal-ranking');
    if (!modal) {
        console.warn('[Ranking] modal-ranking element not found');
        return;
    }

    modal.classList.add('active');
    _currentRankingType = "score";
    await loadRanking("score");
}


function closeRankingModal() {
    const modal = document.getElementById('modal-ranking');
    if (modal) modal.classList.remove('active');
}


// ─────────────────────────────────────────────
// 화살표 토글 — score ↔ pioneers
// ─────────────────────────────────────────────
async function toggleRanking() {
    _currentRankingType = (_currentRankingType === "score") ? "pioneers" : "score";
    await loadRanking(_currentRankingType);
}


// ─────────────────────────────────────────────
// 랭킹 데이터 로드 + 렌더링
// ─────────────────────────────────────────────
async function loadRanking(type) {
    const titleEl   = document.getElementById('ranking-title');
    const subtitleEl = document.getElementById('ranking-subtitle');
    const tableEl   = document.getElementById('ranking-table');
    const myRankEl  = document.getElementById('ranking-my-rank');
    const loadingEl = document.getElementById('ranking-loading');

    if (loadingEl) loadingEl.style.display = 'block';
    if (tableEl)   tableEl.innerHTML = '';
    if (myRankEl)  myRankEl.style.display = 'none';

    try {
        if (type === "score") {
            // ── 점수 랭킹 ──
            if (titleEl)    titleEl.textContent = '🏆 점수 랭킹';
            if (subtitleEl) subtitleEl.textContent = '플레이 점수 기준 TOP 20';

            const r = await fetch('/api/ranking', { credentials: 'same-origin' });
            const data = await r.json();
            if (!data.ok) {
                toast('랭킹 로드 실패', 'error');
                return;
            }

            renderScoreRanking(data.rankings || []);

            // 내 랭킹 표시
            if (data.my_rank && myRankEl) {
                myRankEl.innerHTML = `
                    <span class="my-rank-label">내 순위</span>
                    <span class="my-rank-value">
                        ${data.my_rank.rank} / ${data.my_rank.total}
                        <span class="my-rank-score">(${data.my_rank.score.toLocaleString()} 점)</span>
                    </span>
                `;
                myRankEl.style.display = '';
            }

        } else if (type === "pioneers") {
            // ── 선구자 랭킹 ──
            if (titleEl)    titleEl.textContent = '⚔ 최초 클리어';
            if (subtitleEl) subtitleEl.textContent = '최종 보스를 먼저 처치한 영웅들';

            const r = await fetch('/api/ranking/pioneers', { credentials: 'same-origin' });
            const data = await r.json();
            if (!data.ok) {
                toast('선구자 랭킹 로드 실패', 'error');
                return;
            }

            renderPioneerRanking(data.pioneers || []);
        }
    } catch (e) {
        console.error('[Ranking] load failed:', e);
        toast('네트워크 오류', 'error');
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}


// ─────────────────────────────────────────────
// 점수 랭킹 렌더링
// 컬럼: 등수 | 닉네임 | 직업 | 점수
// ─────────────────────────────────────────────
function renderScoreRanking(rankings) {
    const tableEl = document.getElementById('ranking-table');
    if (!tableEl) return;

    if (rankings.length === 0) {
        tableEl.innerHTML = '<div class="ranking-empty">아직 기록이 없습니다</div>';
        return;
    }

    let html = `
        <div class="ranking-row ranking-header-row">
            <span class="rank-col">RANK</span>
            <span class="nickname-col">NICKNAME</span>
            <span class="job-col">JOB</span>
            <span class="score-col">SCORE</span>
        </div>
    `;

    for (const r of rankings) {
        const rankClass = r.rank === 1 ? 'gold'
                        : r.rank === 2 ? 'silver'
                        : r.rank === 3 ? 'bronze' : '';
        const cleared = r.final_boss_cleared ? '👑' : '';

        html += `
            <div class="ranking-row ${rankClass}">
                <span class="rank-col">${r.rank}</span>
                <span class="nickname-col">${escapeHtml(r.nickname)} ${cleared}</span>
                <span class="job-col">${escapeHtml(r.job)}</span>
                <span class="score-col">${r.score.toLocaleString()}</span>
            </div>
        `;
    }

    tableEl.innerHTML = html;
}


// ─────────────────────────────────────────────
// 선구자 랭킹 렌더링
// 컬럼: 등수 | 닉네임 | 직업 | 클리어 일시
// ─────────────────────────────────────────────
function renderPioneerRanking(pioneers) {
    const tableEl = document.getElementById('ranking-table');
    if (!tableEl) return;

    if (pioneers.length === 0) {
        tableEl.innerHTML = '<div class="ranking-empty">아직 최종 보스를 클리어한 사람이 없습니다</div>';
        return;
    }

    let html = `
        <div class="ranking-row ranking-header-row">
            <span class="rank-col">RANK</span>
            <span class="nickname-col">NICKNAME</span>
            <span class="job-col">JOB</span>
            <span class="date-col">CLEARED</span>
        </div>
    `;

    for (const p of pioneers) {
        const rankClass = p.rank === 1 ? 'gold'
                        : p.rank === 2 ? 'silver'
                        : p.rank === 3 ? 'bronze' : '';

        // 날짜 포맷팅 — "2026-05-17 11:45"
        const dt = new Date(p.cleared_at);
        const dateStr = `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')} ${String(dt.getHours()).padStart(2,'0')}:${String(dt.getMinutes()).padStart(2,'0')}`;

        html += `
            <div class="ranking-row ${rankClass}">
                <span class="rank-col">${p.rank}</span>
                <span class="nickname-col">${escapeHtml(p.nickname)}</span>
                <span class="job-col">${escapeHtml(p.job)}</span>
                <span class="date-col">${dateStr}</span>
            </div>
        `;
    }

    tableEl.innerHTML = html;
}

// ─────────────────────────────────────────────
// 헬퍼: HTML 이스케이프 (XSS 방지)
// ─────────────────────────────────────────────
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
