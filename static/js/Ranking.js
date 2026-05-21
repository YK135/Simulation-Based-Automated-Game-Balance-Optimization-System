/* ═══════════════════════════════════════════════════════════
   Ranking.js — 랭킹 모달 제어 (깨끗한 통째 교체 버전)
   ─────────────────────────────────────────────────────────
   경로: static/js/Ranking.js

   ⚠ 이 파일이 안 로드되면 typeof openRankingModal === 'undefined'
     → index.html에 <script src="js/Ranking.js"></script> 추가 필요

   기능:
   - 랭킹 모달 열기/닫기
   - 좌우 화살표로 두 가지 랭킹 토글: 점수 ↔ 선구자
   - 매번 열 때 실시간 API 호출
   ═══════════════════════════════════════════════════════════ */

// 현재 보고 있는 랭킹 종류
var _currentRankingType = "score";


// ─────────────────────────────────────────────
// 랭킹 모달 열기
// ─────────────────────────────────────────────
async function openRankingModal() {
    var modal = document.getElementById('modal-ranking');
    if (!modal) {
        console.warn('[Ranking] modal-ranking element not found');
        return;
    }
    modal.classList.add('active');
    _currentRankingType = "score";
    await loadRanking("score");
}


function closeRankingModal() {
    var modal = document.getElementById('modal-ranking');
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
    var titleEl    = document.getElementById('ranking-title');
    var subtitleEl = document.getElementById('ranking-subtitle');
    var tableEl    = document.getElementById('ranking-table');
    var myRankEl   = document.getElementById('ranking-my-rank');
    var loadingEl  = document.getElementById('ranking-loading');

    if (loadingEl) loadingEl.style.display = 'block';
    if (tableEl)   tableEl.innerHTML = '';
    if (myRankEl)  myRankEl.style.display = 'none';

    try {
        if (type === "score") {
            // ── 점수 랭킹 ──
            if (titleEl)    titleEl.textContent = '🏆 점수 랭킹';
            if (subtitleEl) subtitleEl.textContent = '플레이 점수 기준 TOP 20';

            var r = await fetch('/api/ranking', { credentials: 'same-origin' });
            var data = await r.json();
            if (!data.ok) {
                if (typeof toast === 'function') toast('랭킹 로드 실패', 'error');
                return;
            }
            renderScoreRanking(data.rankings || []);

            // 내 랭킹 표시
            if (data.my_rank && myRankEl) {
                var html = '<span class="my-rank-label">내 순위</span>' +
                           '<span class="my-rank-value">' +
                           data.my_rank.rank + ' / ' + data.my_rank.total +
                           ' <span class="my-rank-score">(' +
                           data.my_rank.score.toLocaleString() + ' 점)</span>' +
                           '</span>';
                myRankEl.innerHTML = html;
                myRankEl.style.display = '';
            }
        } else if (type === "pioneers") {
            // ── 선구자 랭킹 ──
            if (titleEl)    titleEl.textContent = '⚔ 최초 클리어';
            if (subtitleEl) subtitleEl.textContent = '최종 보스를 먼저 처치한 영웅들';

            var r2 = await fetch('/api/ranking/pioneers', { credentials: 'same-origin' });
            var data2 = await r2.json();
            if (!data2.ok) {
                if (typeof toast === 'function') toast('선구자 랭킹 로드 실패', 'error');
                return;
            }
            renderPioneerRanking(data2.pioneers || []);
        }
    } catch (e) {
        console.error('[Ranking] load failed:', e);
        if (typeof toast === 'function') toast('네트워크 오류', 'error');
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}


// ─────────────────────────────────────────────
// 점수 랭킹 렌더링
// 컬럼: 등수 | 닉네임 | 직업 | 점수
// ─────────────────────────────────────────────
function renderScoreRanking(rankings) {
    var tableEl = document.getElementById('ranking-table');
    if (!tableEl) return;

    if (rankings.length === 0) {
        tableEl.innerHTML = '<div class="ranking-empty">아직 기록이 없습니다</div>';
        return;
    }

    var html = '' +
        '<div class="ranking-row ranking-header-row">' +
            '<span class="rank-col">RANK</span>' +
            '<span class="nickname-col">NICKNAME</span>' +
            '<span class="job-col">JOB</span>' +
            '<span class="score-col">SCORE</span>' +
        '</div>';

    for (var i = 0; i < rankings.length; i++) {
        var r = rankings[i];
        var rankClass = '';
        if (r.rank === 1) rankClass = 'gold';
        else if (r.rank === 2) rankClass = 'silver';
        else if (r.rank === 3) rankClass = 'bronze';

        var cleared = r.final_boss_cleared ? '👑' : '';

        html += '<div class="ranking-row ' + rankClass + '">' +
                    '<span class="rank-col">' + r.rank + '</span>' +
                    '<span class="nickname-col">' + escapeHtml(r.nickname) + ' ' + cleared + '</span>' +
                    '<span class="job-col">' + escapeHtml(r.job) + '</span>' +
                    '<span class="score-col">' + r.score.toLocaleString() + '</span>' +
                '</div>';
    }

    tableEl.innerHTML = html;
}


// ─────────────────────────────────────────────
// 선구자 랭킹 렌더링
// 컬럼: 등수 | 닉네임 | 직업 | 클리어 일시
// ─────────────────────────────────────────────
function renderPioneerRanking(pioneers) {
    var tableEl = document.getElementById('ranking-table');
    if (!tableEl) return;

    if (pioneers.length === 0) {
        tableEl.innerHTML = '<div class="ranking-empty">아직 최종 보스를 클리어한 사람이 없습니다</div>';
        return;
    }

    var html = '' +
        '<div class="ranking-row ranking-header-row">' +
            '<span class="rank-col">RANK</span>' +
            '<span class="nickname-col">NICKNAME</span>' +
            '<span class="job-col">JOB</span>' +
            '<span class="date-col">CLEARED</span>' +
        '</div>';

    for (var j = 0; j < pioneers.length; j++) {
        var p = pioneers[j];
        var rankClass = '';
        if (p.rank === 1) rankClass = 'gold';
        else if (p.rank === 2) rankClass = 'silver';
        else if (p.rank === 3) rankClass = 'bronze';

        // 날짜 포맷 — "2026-05-17 11:45"
        var dt = new Date(p.cleared_at);
        var dateStr = dt.getFullYear() + '-' +
                      String(dt.getMonth() + 1).padStart(2, '0') + '-' +
                      String(dt.getDate()).padStart(2, '0') + ' ' +
                      String(dt.getHours()).padStart(2, '0') + ':' +
                      String(dt.getMinutes()).padStart(2, '0');

        html += '<div class="ranking-row ' + rankClass + '">' +
                    '<span class="rank-col">' + p.rank + '</span>' +
                    '<span class="nickname-col">' + escapeHtml(p.nickname) + '</span>' +
                    '<span class="job-col">' + escapeHtml(p.job) + '</span>' +
                    '<span class="date-col">' + dateStr + '</span>' +
                '</div>';
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