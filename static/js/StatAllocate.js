// 분배 가능한 스탯 + 표시명 + 포인트당 효율
const SA_STATS = [
    { key: "stg",   label: "STG",   per: 1.0 },
    { key: "sp",    label: "SP",    per: 1.0 },
    { key: "arm",   label: "ARM",   per: 1.0 },
    { key: "sparm", label: "SPARM", per: 1.0 },
    { key: "spd",   label: "SPD",   per: 0.5 },   // ★ 비싸게
    { key: "luc",   label: "LUC",   per: 1.0 },
];

// 현재 분배 상태
let saAllocation = {};   // { stg: 2, spd: 1, ... }
let saTotalPoints = 0;   // 이번에 분배 가능한 총 포인트
let saResolvePending = null;   // openStatAllocate()이 반환한 Promise의 resolve —
                                // 배틀 종료 시퀀스가 "이 모달이 닫힐 때까지" 기다릴 때 사용

/** 모달 내용을 (다시) 그려서 연다 — Promise/resolver는 건드리지 않는다.
 *  saConfirm()이 "이번 배분 다 씀, 다음 레벨업분 남음"일 때 같은 모달
 *  세션을 이어서 쓰기 위해 분리(아래 openStatAllocate()의 내부 구현). */
function _renderStatAllocateOpen(points) {
    saTotalPoints = points;
    saAllocation = {};
    SA_STATS.forEach(s => saAllocation[s.key] = 0);

    document.getElementById("sa-remaining").textContent = points;
    renderStatAllocList();

    // ★ 휴식 모달과 동일하게 .modal-bg → .active 토글
    const modal = document.getElementById("modal-stat-allocate");
    if (modal) modal.classList.add("active");
}

/**
 * 스탯 분배 모달 열기. 모달이 완전히 닫힐 때(포인트를 다 분배해서) resolve되는
 * Promise를 반환한다 — showRewardModal()/openInvSwap()과 동일한 패턴.
 * 기존 호출부(반환값 무시)는 그대로 동작하므로 하위 호환.
 * @param {number} points - 분배 가능한 포인트 수
 */
function openStatAllocate(points) {
    _renderStatAllocateOpen(points);
    return new Promise(resolve => { saResolvePending = resolve; });
}

/** 분배 UI 렌더 */
function renderStatAllocList() {
    const list = document.getElementById("sa-stat-list");
    if (!list || !state.player) return;

    const p = state.player;
    const spent = Object.values(saAllocation).reduce((a, b) => a + b, 0);
    const remaining = saTotalPoints - spent;

    document.getElementById("sa-remaining").textContent = remaining;

    list.innerHTML = SA_STATS.map(s => {
        const base = p[s.key] !== undefined ? p[s.key] : 0;
        const alloc = saAllocation[s.key] || 0;
        const added = alloc * s.per;
        const newVal = (base + added).toFixed(s.per < 1 ? 1 : 0);
        const perLabel = s.per < 1 ? ` (×${s.per})` : "";

        return `
        <div class="sa-stat-row">
            <span class="sa-stat-label">${s.label}${perLabel}</span>
            <span class="sa-stat-value">
                ${base.toFixed(s.per < 1 ? 1 : 0)}
                ${added > 0 ? `<span class="added">→ ${newVal}</span>` : ""}
            </span>
            <span class="sa-stat-controls">
                <button class="sa-btn-pm" data-stat="${s.key}" data-delta="-1"
                    ${alloc <= 0 ? "disabled" : ""}>−</button>
                <span class="sa-alloc-count">${alloc}</span>
                <button class="sa-btn-pm" data-stat="${s.key}" data-delta="1"
                    ${remaining <= 0 ? "disabled" : ""}>+</button>
            </span>
        </div>`;
    }).join("");

    // +/- 버튼 이벤트 바인딩 (인라인 onclick 대체)
    list.querySelectorAll(".sa-btn-pm[data-stat]").forEach(btn => {
        btn.addEventListener("click", () => {
            if (btn.disabled) return;
            saAdjust(btn.dataset.stat, Number(btn.dataset.delta));
        });
    });

    // 확정 버튼: 1포인트 이상 분배해야 활성화
    const confirmBtn = document.getElementById("sa-confirm");
    if (confirmBtn) confirmBtn.disabled = (spent === 0);
}

/** +/- 버튼 */
function saAdjust(statKey, delta) {
    const spent = Object.values(saAllocation).reduce((a, b) => a + b, 0);
    const remaining = saTotalPoints - spent;

    if (delta > 0 && remaining <= 0) return;
    if (delta < 0 && saAllocation[statKey] <= 0) return;

    saAllocation[statKey] = (saAllocation[statKey] || 0) + delta;
    if (saAllocation[statKey] < 0) saAllocation[statKey] = 0;

    renderStatAllocList();
}

/** 초기화 */
function saReset() {
    SA_STATS.forEach(s => saAllocation[s.key] = 0);
    renderStatAllocList();
}

/** 확정 — 백엔드 전송 */
async function saConfirm() {
    const payload = {};
    Object.entries(saAllocation).forEach(([k, v]) => {
    if (v > 0) payload[k] = v;
    });
    const confirmBtn = document.getElementById("sa-confirm");
    if (confirmBtn?.disabled) return;

    const spent = Object.values(saAllocation).reduce((a, b) => a + b, 0);
    if (spent === 0) return;

    if (confirmBtn) confirmBtn.disabled = true;

    try {
        const r = await api("/levelup/allocate", { allocation: payload });
        if (!r.ok) {
            toast(r.error || "분배 실패", "error");
            return;
        }

        // 플레이어 상태 갱신
        state.player = r.player;
        if (typeof refreshPlayer === "function") refreshPlayer();

        const remaining = r.remaining || 0;
        if (remaining > 0) {
            // 남은 포인트 있으면 모달 유지(다음 레벨업분) — 같은 모달 세션을
            // 이어가므로 openStatAllocate()을 다시 부르지 않는다. 그러면
            // 원래 Promise의 resolver(saResolvePending)가 새 Promise로
            // 덮어써져서, 처음 이 모달을 열며 await하고 있던 쪽(배틀 종료
            // 시퀀스)이 영원히 안 풀리는 버그가 생긴다.
            _renderStatAllocateOpen(remaining);
            toast(`분배 완료! 남은 포인트: ${remaining}`, "ok");
        } else {
            // 모두 분배 → 닫기
            closeStatAllocate();
            toast("스탯 분배 완료!", "ok");
        }
    } catch (e) {
        console.error("[saConfirm]", e);
        toast("네트워크 오류", "error");
    } finally {
        if (confirmBtn) confirmBtn.disabled = false;
    }
}

/** 모달 닫기 — 대기 중인 Promise가 있으면 resolve. */
function closeStatAllocate() {
    const modal = document.getElementById("modal-stat-allocate");
    if (modal) modal.classList.remove("active");
    if (saResolvePending) {
        const resolve = saResolvePending;
        saResolvePending = null;
        resolve();
    }
}

/**
 * 레벨업 후 호출 — pending_points 있으면 모달 자동 오픈.
 * loadStatus() 또는 전투 종료 후 호출하면 됨. 모달이 닫힐 때(포인트 없으면
 * 즉시) resolve되는 Promise를 반환 — Actions.js의 battleAction()이 보상
 * 모달/오버플로 처리 뒤에 이걸 await해서 레벨업 모달과 겹치지 않게 한다.
 */
function checkPendingPoints() {
    if (!state.player) return Promise.resolve();
    const pending = state.player.pending_points || 0;
    if (pending > 0) {
        return openStatAllocate(pending);
    }
    return Promise.resolve();
}

// 버튼 이벤트 바인딩 (DOMContentLoaded 후)
document.addEventListener("DOMContentLoaded", () => {
    const resetBtn = document.getElementById("sa-reset");
    const confirmBtn = document.getElementById("sa-confirm");
    if (resetBtn) resetBtn.onclick = saReset;
    if (confirmBtn) confirmBtn.onclick = saConfirm;
});