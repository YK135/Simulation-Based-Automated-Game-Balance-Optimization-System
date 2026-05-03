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
    const r = await fetch(API + path, opts);
    return r.json();
}