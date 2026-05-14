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
        if (!r.ok) {
            // 404 등은 정상 응답으로 처리 (콘솔 에러 안 띄움)
            return { ok: false, error: `HTTP ${r.status}`, status: r.status };
        }
        return await r.json();
    } catch (e) {
        return { ok: false, error: e.message };
    }
}