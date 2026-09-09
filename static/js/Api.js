/* ═══════════════════════════════════════════════════════════
   api.js — Flask 백엔드 호출 래퍼
   사용 예:
     const r = await api('/status');         // GET
     const r = await api('/new_game', {...}); // POST
   ═══════════════════════════════════════════════════════════ */

const API = '/api';

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
        if (!r.ok) {
            return { ok: false, error: `HTTP ${r.status}`, ...(data || {}), status: r.status };
        }
        return data ?? { ok: false, error: '빈 응답' };
    } catch (e) {
        return { ok: false, error: e.message };
    }
}