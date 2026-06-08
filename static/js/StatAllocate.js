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

/**
 * 스탯 분배 모달 열기
 * @param {number} points - 분배 가능한 포인트 수
 */
function openStatAllocate(points) {
    saTotalPoints = points;
    saAllocation = {};
    SA_STATS.forEach(s => saAllocation[s.key] = 0);
 
    document.getElementById("sa-remaining").textContent = points;
    renderStatAllocList();
 
    // ★ 휴식 모달과 동일하게 .modal-bg → .active 토글
    const modal = document.getElementById("modal-stat-allocate");
    if (modal) modal.classList.add("active");
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
            // 남은 포인트 있으면 모달 유지 (다음 레벨업분)
            openStatAllocate(remaining);
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

/** 모달 닫기 */
function closeStatAllocate() {
    const modal = document.getElementById("modal-stat-allocate");
    if (modal) modal.classList.remove("active");
}

/**
 * 레벨업 후 호출 — pending_points 있으면 모달 자동 오픈.
 * loadStatus() 또는 전투 종료 후 호출하면 됨.
 */
function checkPendingPoints() {
    if (!state.player) return;
    const pending = state.player.pending_points || 0;
    if (pending > 0) {
        openStatAllocate(pending);
    }
}

// 버튼 이벤트 바인딩 (DOMContentLoaded 후)
document.addEventListener("DOMContentLoaded", () => {
    const resetBtn = document.getElementById("sa-reset");
    const confirmBtn = document.getElementById("sa-confirm");
    if (resetBtn) resetBtn.onclick = saReset;
    if (confirmBtn) confirmBtn.onclick = saConfirm;
});