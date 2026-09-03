/* map/MapChapter.js — 챕터 클리어/전환 + 게임 오버 */

// 플레이어 사망 시 전체 화면 오버레이 — NEW GAME(restartGame)으로만 재시작 가능.
// (백엔드도 player.hp<=0이면 /api/map/choose를 거부하지만, 애초에 맵으로
//  돌아가지 못하게 여기서 막아 "죽었는데 계속 노드 선택되는" 버그를 차단)
function showGameOver(feedback) {
    if (document.getElementById('chapter-clear-overlay')) return; // 중복 방지
    const overlay = document.createElement('div');
    overlay.id = 'chapter-clear-overlay';
    overlay.className = 'chapter-clear-overlay game-over';

    // ★ 서버가 BehaviorAnalyzer/FeedbackEngine으로 생성한 복기 리포트(있을 때만).
    //   escapeHtml 필수 — headline/good_plays 등에 전투 로그 문구가 그대로 들어있고,
    //   그 문구엔 플레이어가 직접 입력한 이름이 섞여 있을 수 있음(Utils.js 참고).
    //   Ranking.js/SidePanel.js와 동일하게 escapeHtml을 직접 호출한다 — "없으면
    //   그냥 통과시키는" 폴백을 두면 스크립트 로드 순서가 깨졌을 때 조용히
    //   이스케이프가 빠져버려서(에러도 안 남음) 막으려던 XSS가 그대로 재현된다.
    //   escapeHtml이 없으면 즉시 ReferenceError로 시끄럽게 터지는 쪽이 맞다.
    const _list = (arr) => (arr && arr.length)
        ? arr.map(t => `· ${escapeHtml(t)}`).join('<br>') : '';
    const fbHtml = feedback ? `
        <div class="battle-feedback">
            <div class="battle-feedback-score">${feedback.score} / 100</div>
            <div class="battle-feedback-headline">${escapeHtml(feedback.headline)}</div>
            ${feedback.good_plays?.length ? `<div class="fb-good">${_list(feedback.good_plays)}</div>` : ''}
            ${feedback.bad_plays?.length ? `<div class="fb-bad">${_list(feedback.bad_plays)}</div>` : ''}
            ${feedback.suggestions?.length ? `<div class="fb-suggest">${_list(feedback.suggestions)}</div>` : ''}
        </div>` : '';

    overlay.innerHTML = `
        <div class="chapter-clear-title game-over-title">☠ GAME OVER</div>
        <div class="chapter-clear-sub">모험이 여기서 끝났다...</div>
        ${fbHtml}
        <button class="btn chapter-clear-btn" id="game-over-restart-btn">⚡ NEW GAME</button>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('#game-over-restart-btn')
        ?.addEventListener('click', () => {
            overlay.remove();
            restartGame();
        });
}

function _showChapterClear(result) {
    const isGameClear = result.game_clear;
    const nextCh      = result.next_chapter;
    const overlay = document.createElement("div");
    overlay.id = "chapter-clear-overlay";
    overlay.className = "chapter-clear-overlay";
    overlay.innerHTML = `
        <div class="chapter-clear-title">
            ${isGameClear ? "🎉 GAME CLEAR!" : `CHAPTER ${_mapState?.chapter || ""} CLEAR!`}
        </div>
        <div class="chapter-clear-sub">
            ${isGameClear ? "모든 챕터를 클리어했습니다!" : `챕터 ${nextCh}로 진행합니다.`}
        </div>
        <button class="btn chapter-clear-btn"
            id="chapter-clear-btn"
            data-action="${isGameClear ? "restart" : "next"}"
            data-next-chapter="${nextCh || ""}">
            ${isGameClear ? "처음으로" : `챕터 ${nextCh} 시작 ▶`}
        </button>
    `;
    document.body.appendChild(overlay);

    // 이벤트 바인딩 (인라인 onclick 대체)
    const btn = overlay.querySelector("#chapter-clear-btn");
    btn?.addEventListener("click", () => {
        if (btn.dataset.action === "restart") {
            restartGame();
        } else {
            startNextChapter(Number(btn.dataset.nextChapter));
        }
    });
}

async function startNextChapter(chapter) {
    document.getElementById("chapter-clear-overlay")?.remove();
    try {
        const r = await api("/map/next_chapter", {});
        if (!r.ok) { toast(r.error || "챕터 전환 실패", "error"); return; }
        _mapState = r.map;
        setMapMode();
        renderMap(_mapState);
        logLine(`📍 챕터 ${chapter} 시작!`, "system");
        logAdventure(`챕터 ${chapter}에 발을 들였다.`, "system");
        toast(`챕터 ${chapter} 시작!`, "ok");
    } catch (e) {
        console.error("[startNextChapter]", e);
    }
}