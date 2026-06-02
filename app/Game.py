"""
game/Map.py — 슬레이 더 스파이어 스타일 노드맵 (좌/우 갈래 구조)
─────────────────────────────────────────────
구조:
  챕터 1: 계층 1~14 (일반) + 계층 15 (중간 보스)
  챕터 2: 계층 1~14 (일반) + 계층 15 (최종 보스)
  전체 30턴

갈래 구조:
  - 계층 1에서 left / right 두 갈래로 분기
  - 한번 선택한 branch는 챕터 내에서 고정
  - 계층 15 보스는 양쪽 모두 연결

노드 ID 형식: "ch{chapter}_l{layer}_{branch}_{index}"
  예: "ch1_l3_left_0", "ch1_l15_boss_0"

노드 타입 분포 규칙 (챕터당 1~14계층 전체):
  event : 1~4개
  shop  : 1~2개
  rest  : 1~2개
  elite : 1~3개
  나머지: battle

직렬화: to_dict() / from_dict() — JSON 직렬화 가능
"""
from __future__ import annotations

import random
from typing import List, Dict, Any, Optional

# ─────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────
TOTAL_LAYERS    = 15          # 계층 1~15 (보스 = 15)
BOSS_LAYER      = 15
NORMAL_LAYERS   = 14          # 계층 1~14 일반
BRANCHES        = ["left", "right"]

# 계층별 각 branch 노드 수 (1~14계층)
# 마지막 일반 계층(14)은 최대 2개
NODES_PER_BRANCH_NORMAL = (1, 2)   # min, max
NODES_LAYER_14_MAX      = 2        # 보스 직전 계층 최대

# 챕터별 타입 분포 제약 (전체 맵 기준)
TYPE_CONSTRAINTS = {
    "event": (1, 4),
    "shop":  (1, 2),
    "rest":  (1, 2),
    "elite": (1, 3),
}


# ─────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────
class Node:
    """
    단일 노드.

    Attributes:
        node_id   : 고유 ID ("ch1_l3_left_0")
        chapter   : 챕터 번호
        layer     : 계층 번호 (1~15)
        branch    : "left" | "right" | "boss"
        index     : 같은 branch 내 위치
        node_type : battle/elite/event/rest/shop/boss
        next_ids  : 다음 계층 연결 노드 ID 목록
        visited   : 방문 완료 여부
        available : 현재 선택 가능 여부
        on_path   : 플레이어가 지나온 경로 여부 (하이라이트용)
    """

    def __init__(self, chapter: int, layer: int, branch: str,
                 index: int, node_type: str):
        self.node_id   = f"ch{chapter}_l{layer}_{branch}_{index}"
        self.chapter   = chapter
        self.layer     = layer
        self.branch    = branch
        self.index     = index
        self.node_type = node_type
        self.next_ids: List[str] = []
        self.visited   = False
        self.available = False
        self.on_path   = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id":   self.node_id,
            "chapter":   self.chapter,
            "layer":     self.layer,
            "branch":    self.branch,
            "index":     self.index,
            "node_type": self.node_type,
            "next_ids":  self.next_ids,
            "visited":   self.visited,
            "available": self.available,
            "on_path":   self.on_path,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Node":
        n = cls(d["chapter"], d["layer"], d["branch"], d["index"], d["node_type"])
        n.next_ids  = d["next_ids"]
        n.visited   = d["visited"]
        n.available = d["available"]
        n.on_path   = d.get("on_path", False)
        return n


# ─────────────────────────────────────────────
# FloorMap
# ─────────────────────────────────────────────
class FloorMap:
    """
    챕터 1개의 전체 맵 (좌/우 갈래 구조).

    사용:
        fmap = FloorMap.generate(chapter=1)
        state = fmap.get_state()
        ok, node, err = fmap.choose(node_id)
        fmap.mark_visited(node_id)
    """

    def __init__(self, chapter: int, nodes: Dict[str, Node]):
        self.chapter       = chapter
        self.nodes         = nodes           # node_id → Node
        self.current_layer = 0
        self.player_branch: Optional[str] = None   # 선택된 갈래 ("left"/"right")
        self.completed     = False

    # ── 생성 ──────────────────────────────────

    @classmethod
    def generate(cls, chapter: int) -> "FloorMap":
        """좌/우 갈래 맵 랜덤 생성."""
        nodes: Dict[str, Node] = {}

        # 1) 각 branch별 계층 1~14 노드 생성
        branch_layers: Dict[str, List[List[Node]]] = {"left": [], "right": []}

        for branch in BRANCHES:
            # 타입 할당 계획 생성 (분포 제약 만족)
            type_plan = _make_type_plan(chapter, branch)

            for layer in range(1, NORMAL_LAYERS + 1):
                if layer == NORMAL_LAYERS:
                    # 14계층: 최대 2개
                    count = random.randint(1, NODES_LAYER_14_MAX)
                else:
                    count = random.randint(*NODES_PER_BRANCH_NORMAL)

                layer_nodes = []
                for idx in range(count):
                    ntype = type_plan.pop(0) if type_plan else "battle"
                    node  = Node(chapter, layer, branch, idx, ntype)
                    layer_nodes.append(node)
                    nodes[node.node_id] = node

                branch_layers[branch].append(layer_nodes)

        # 2) 보스 노드 (계층 15, branch="boss")
        boss_type = "boss"
        boss_node = Node(chapter, BOSS_LAYER, "boss", 0, boss_type)
        nodes[boss_node.node_id] = boss_node

        # 3) 계층 간 연결 (각 branch 내부)
        for branch in BRANCHES:
            layers = branch_layers[branch]
            for li in range(len(layers) - 1):
                _connect_branch_layers(layers[li], layers[li + 1])
            # 14계층 → 보스 연결
            for node in layers[-1]:
                if boss_node.node_id not in node.next_ids:
                    node.next_ids.append(boss_node.node_id)

        # 4) 계층 1 노드 available = True (양쪽 모두)
        for branch in BRANCHES:
            for node in branch_layers[branch][0]:
                node.available = True

        fmap = cls(chapter, nodes)
        return fmap

    # ── 상태 조회 ──────────────────────────────

    def get_available(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.available and not n.visited]

    def get_state(self) -> Dict[str, Any]:
        """
        프론트 응답용 맵 상태.
        branch_locked: 플레이어가 이미 갈래를 선택했는지
        """
        return {
            "chapter":        self.chapter,
            "current_layer":  self.current_layer,
            "boss_layer":     BOSS_LAYER,
            "total_layers":   TOTAL_LAYERS,
            "completed":      self.completed,
            "player_branch":  self.player_branch,
            "nodes":          [n.to_dict() for n in self.nodes.values()],
            "available":      [n.node_id for n in self.get_available()],
            # 배경 이미지 자리
            # Chapter 1: static/img/map/chapter_1_bg.png
            # Chapter 2: static/img/map/chapter_2_bg.png
            # 권장 크기: 1280x720px, 16:9, 어두운 배경 권장
            "bg_image": f"img/map/chapter_{self.chapter}_bg.png",
        }

    # ── 선택 처리 ──────────────────────────────

    def choose(self, node_id: str):
        """
        노드 선택.
        반환: (ok, node, error)
        갈래 잠금: 첫 선택 시 player_branch 확정,
                  이후 반대편 branch 선택 불가.
        """
        node = self.nodes.get(node_id)
        if not node:
            return False, None, "존재하지 않는 노드입니다."
        if not node.available:
            return False, None, "선택할 수 없는 노드입니다."
        if node.visited:
            return False, None, "이미 방문한 노드입니다."

        # 갈래 잠금 체크 (보스 노드는 양쪽 모두 허용)
        if node.branch != "boss" and self.player_branch:
            if node.branch != self.player_branch:
                return False, None, f"이미 {self.player_branch} 경로를 선택했습니다."

        # 첫 선택 시 갈래 확정
        if node.branch != "boss" and not self.player_branch:
            self.player_branch = node.branch

        return True, node, ""

    def mark_visited(self, node_id: str) -> None:
        """노드 완료 처리 → 다음 노드 활성화."""
        node = self.nodes.get(node_id)
        if not node:
            return

        node.visited   = True
        node.available = False
        node.on_path   = True
        self.current_layer = node.layer

        if node.node_type == "boss":
            self.completed = True
            return

        # 다음 노드 활성화
        for next_id in node.next_ids:
            next_node = self.nodes.get(next_id)
            if next_node and not next_node.visited:
                next_node.available = True

        # 반대편 branch 전체 비활성화 (갈래 잠금)
        if self.player_branch:
            opposite = "right" if self.player_branch == "left" else "left"
            for n in self.nodes.values():
                if n.branch == opposite and not n.visited:
                    n.available = False

    # ── 직렬화 ────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chapter":       self.chapter,
            "current_layer": self.current_layer,
            "player_branch": self.player_branch,
            "completed":     self.completed,
            "nodes":         {nid: n.to_dict() for nid, n in self.nodes.items()},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FloorMap":
        nodes = {nid: Node.from_dict(nd) for nid, nd in d["nodes"].items()}
        fmap  = cls(d["chapter"], nodes)
        fmap.current_layer = d["current_layer"]
        fmap.player_branch = d.get("player_branch")
        fmap.completed     = d["completed"]
        return fmap


# ─────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────

def _make_type_plan(chapter: int, branch: str) -> List[str]:
    """
    한 branch(14계층)의 타입 시퀀스 생성.
    TYPE_CONSTRAINTS 제약을 만족하면서 나머지는 battle.
    """
    plan: List[str] = []

    # 제약 충족 타입 먼저 추가
    for ntype, (mn, mx) in TYPE_CONSTRAINTS.items():
        count = random.randint(mn, mx)
        plan.extend([ntype] * count)

    # 나머지 슬롯 계산 (branch당 평균 노드 수 추정)
    # 계층 1~13: 1~2개, 계층 14: 1~2개 → 평균 ~20개 슬롯
    target_total = 20
    remaining = max(0, target_total - len(plan))
    plan.extend(["battle"] * remaining)

    random.shuffle(plan)
    return plan


def _connect_branch_layers(cur: List[Node], nxt: List[Node]) -> None:
    """
    같은 branch 내 계층 간 연결.
    각 현재 노드 → 다음 계층 1~2개 연결.
    모든 다음 계층 노드가 최소 1개 연결 보장.
    """
    used_next: set = set()

    for cn in cur:
        # 인덱스 근접 노드 선호
        pref = [n for n in nxt if abs(n.index - cn.index) <= 1]
        target = random.choice(pref if pref else nxt)
        if target.node_id not in cn.next_ids:
            cn.next_ids.append(target.node_id)
        used_next.add(target.node_id)

    # 고아 방지
    for orphan in [n for n in nxt if n.node_id not in used_next]:
        donor = random.choice(cur)
        if orphan.node_id not in donor.next_ids:
            donor.next_ids.append(orphan.node_id)

    # 추가 연결 (30% 확률)
    for cn in cur:
        if len(cn.next_ids) < 2 and len(nxt) > 1:
            extras = [n for n in nxt if n.node_id not in cn.next_ids]
            if extras and random.random() < 0.3:
                cn.next_ids.append(random.choice(extras).node_id)