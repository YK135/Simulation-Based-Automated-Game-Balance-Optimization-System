/* ═══════════════════════════════════════════════════════════
   api.js — Flask 백엔드 호출 래퍼
   사용 예:
     const r = await api('/status');         // GET
     const r = await api('/new_game', {...}); // POST
   ═══════════════════════════════════════════════════════════ */

const API = '/api';

/** 응답에 실려 온 보유 골드를 화면 상태에 반영한다.
 *  ★ 골드는 서버(gs["gold"])가 유일한 기준이고, 골드를 바꾸는 모든 엔드포인트가
 *    응답에 현재 보유액을 `gold`로 실어 보낸다(전투 종료·상점·유물 환전·인벤토리
 *    교체·상태 조회). 예전엔 호출부마다 `if (r.gold !== undefined) state.gold = r.gold`를
 *    따로 적었는데, 하필 전투 종료 경로(Actions.js의 r.done 분기)가 그걸 빠뜨려서
 *    승리 보상 골드가 좌측 패널에 영영 반영되지 않았다 — 상점에서 한 번 사야
 *    그때 맞춰지는 식이라 패널 숫자와 실제 골드가 계속 어긋났다(사용자 제보).
 *    호출부마다 기억하는 대신 여기 한 곳에서 반영한다.
 *  ※ 순수 표시 계층 — 전투 계산은 이 값을 읽지 않는다. */
function _syncGoldFromResponse(data) {
    if (!data || typeof data.gold !== "number" || !isFinite(data.gold)) return;
    if (typeof state === "undefined" || !state) return;
    state.gold = data.gold;
    if (typeof refreshGoldDisplay === "function") refreshGoldDisplay();
}

async function api(path, body = null) {
    const opts = { method: body ? 'POST' : 'GET', credentials: 'same-origin' };
    if (body) {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = JSON.stringify(body);
    }
    try {
        const r = await fetch(API + path, opts);
        // ★ 예전엔 !r.ok일 때 서버 JSON 본문을 아예 안 읽고 버렸음 — 그런데
        //   상점/인벤토리 API는 400 응답에도 reason/candidates 같은 실제 처리에
        //   필요한 필드를 실어 보낸다(예: 인벤토리 가득 참 → 교체 선택창을 띄우는
        //   데 쓰는 reason/candidates). 본문을 버리면 그 분기가 영영 실행 안 됨.
        //   본문 파싱 자체가 안 되는 경우(순수 404 HTML 등)만 범용 메시지로 대체.
        let data = null;
        try { data = await r.json(); } catch (_) { data = null; }
        // 실패 응답(400 등)도 서버가 보유 골드를 실어 보내면 그게 최신이다 —
        // 예: 인벤토리 교체 실패 시 되돌린 결제 금액.
        _syncGoldFromResponse(data);
        if (!r.ok) {
            return { ok: false, error: `HTTP ${r.status}`, ...(data || {}), status: r.status };
        }
        return data ?? { ok: false, error: '빈 응답' };
    } catch (e) {
        return { ok: false, error: e.message };
    }
}