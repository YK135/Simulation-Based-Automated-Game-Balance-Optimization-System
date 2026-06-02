"""
game/Map.py — 노드맵 시스템
─────────────────────────────────────────────
슬레이 더 스파이어 스타일 층 기반 랜덤 맵.

구조:
  챕터 1: 10층 (Layer 0~9) + 보스층 (Layer 10)
  챕터 2: 12층 (Layer 0~11) + 보스층 (Layer 12)

각 Layer: 2~3개 노드 → 플레이어가 연결된 노드 중 1개 선택.

노드 타입 비율 (보스 Layer 제외):
  battle  45% — 일반 몬스터
  elite   15% — 엘리트 몬스터
  event   15% — 랜덤 이벤트
  rest    15% — 휴식/수련
  shop    10% — 상점

직렬화:
  to_dict() / from_dict() — GAME_SESSIONS 저장 및 JSON 응답용.
  모든 필드가 순수 Python 기본 타입 (나중에 DB 저장 시 json.dumps만 하면 됨).
"""
from __future__ import annotations

import random
from typing import List, Optional, Dict, Any


# ─────────────────────────────────────────────
# 노드 타입 상수
# ─────────────────────────────────────────────
NODE_TYPES = ["battle", "elite", "event", "rest", "shop", "boss"]

# 챕터별 일반 층 타입 가중치 (보스 층 제외)
_TYPE_WEIGHTS = [
    ("battle", 45),
    ("elite",  15),
    ("event",  15),
    ("rest",   15),
    ("shop",   10),
]
_NAMES  = [t for t, _ in _TYPE_WEIGHTS]
_WGHTS  = [w for _, w in _TYPE_WEIGHTS]

# 챕터 설정
CHAPTER_CONFIG = {
    1: {"normal_layers": 10, "boss_layer": 10},  # Layer 0~9 일반, Layer 10 보스
    2: {"normal_layers": 12, "boss_layer": 12},  # Layer 0~11 일반, Layer 12 보스
}

# Layer당 노드 수 범위
NODES_PER_LAYER_MIN = 2
NODES_PER_LAYER_MAX = 3


# ─────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────
class Node:
    """
    맵의 단일 노드.

    Attributes:
        node_id   : 고유 ID (f"{layer}_{index}")
        layer     : 층 번호 (0 = 시작)
        index     : 같은 층 내 위치 (0, 1, 2)
        node_type : "battle" | "elite" | "event" | "rest" | "shop" | "boss"
        next_ids  : 다음 층에서 연결된 node_id 목록
        visited   : 플레이어가 이 노드를 방문했는지
        available : 현재 선택 가능한 노드인지
    """

    def __init__(
        self,
        layer: int,
        index: int,
        node_type: str,
    ):
        self.node_id   = f"{layer}_{index}"
        self.layer     = layer
        self.index     = index
        self.node_type = node_type
        self.next_ids: List[str] = []
        self.visited   = False
        self.available = False  # 시작 노드만 True로 시작

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id":   self.node_id,
            "layer":     self.layer,
            "index":     self.index,
            "node_type": self.node_type,
            "next_ids":  self.next_ids,
            "visited":   self.visited,
            "available": self.available,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Node":
        node = cls(d["layer"], d["index"], d["node_type"])
        node.next_ids  = d["next_ids"]
        node.visited   = d["visited"]
        node.available = d["available"]
        return node


# ─────────────────────────────────────────────
# FloorMap
# ─────────────────────────────────────────────
class FloorMap:
    """
    챕터 1개의 전체 맵.

    생성:
        fmap = FloorMap.generate(chapter=1)

    사용:
        state   = fmap.get_state()         # 현재 선택 가능 노드 목록
        ok, msg = fmap.choose(node_id)     # 노드 선택
        fmap.mark_visited(node_id)         # 노드 처리 완료 후 표시
    """

    def __init__(self, chapter: int, nodes: Dict[str, Node]):
        self.chapter    = chapter
        self.nodes      = nodes           # node_id → Node
        self.current_layer = 0
        cfg = CHAPTER_CONFIG[chapter]
        self.boss_layer = cfg["boss_layer"]
        self.completed  = False           # 보스 처치 시 True

    # ── 생성 ──────────────────────────────────

    @classmethod
    def generate(cls, chapter: int) -> "FloorMap":
        """랜덤 맵 생성."""
        cfg = CHAPTER_CONFIG[chapter]
        total_layers = cfg["boss_layer"] + 1  # 0 ~ boss_layer

        # 층별 노드 생성
        layers: List[List[Node]] = []
        for layer in range(total_layers):
            is_boss = (layer == cfg["boss_layer"])
            is_start = (layer == 0)

            if is_boss:
                # 보스 층: 노드 1개 고정
                nodes_in_layer = [Node(layer, 0, "boss")]
            elif is_start:
                # 시작 층: 2~3개, battle 위주
                count = random.randint(NODES_PER_LAYER_MIN, NODES_PER_LAYER_MAX)
                nodes_in_layer = [
                    Node(layer, i, _pick_type(force_battle=(i == 0)))
                    for i in range(count)
                ]
            else:
                count = random.randint(NODES_PER_LAYER_MIN, NODES_PER_LAYER_MAX)
                nodes_in_layer = [Node(layer, i, _pick_type()) for i in range(count)]

            # 규칙: shop / rest 연속 2층 배치 금지
            if layer >= 2:
                prev_types = {n.node_type for n in layers[layer - 1]}
                for node in nodes_in_layer:
                    if node.node_type in ("shop", "rest") and node.node_type in prev_types:
                        node.node_type = "battle"

            layers.append(nodes_in_layer)

        # 층 간 연결 (각 노드 → 다음 층 1~2개 연결)
        for layer_idx in range(len(layers) - 1):
            cur_layer  = layers[layer_idx]
            next_layer = layers[layer_idx + 1]
            _connect_layers(cur_layer, next_layer)

        # 시작 노드 available = True
        for node in layers[0]:
            node.available = True

        # dict로 변환
        nodes_dict: Dict[str, Node] = {}
        for layer_nodes in layers:
            for node in layer_nodes:
                nodes_dict[node.node_id] = node

        return cls(chapter, nodes_dict)

    # ── 상태 조회 ──────────────────────────────

    def get_available(self) -> List[Node]:
        """현재 선택 가능한 노드 목록."""
        return [n for n in self.nodes.values() if n.available and not n.visited]

    def get_state(self) -> Dict[str, Any]:
        """프론트 응답용 맵 상태."""
        return {
            "chapter":       self.chapter,
            "current_layer": self.current_layer,
            "boss_layer":    self.boss_layer,
            "completed":     self.completed,
            "nodes":         [n.to_dict() for n in self.nodes.values()],
            "available":     [n.node_id for n in self.get_available()],
        }

    # ── 선택 처리 ──────────────────────────────

    def choose(self, node_id: str):
        """
        플레이어가 노드 선택.
        반환: (ok: bool, node: Node | None, error: str)
        """
        node = self.nodes.get(node_id)
        if not node:
            return False, None, "존재하지 않는 노드입니다."
        if not node.available:
            return False, None, "선택할 수 없는 노드입니다."
        if node.visited:
            return False, None, "이미 방문한 노드입니다."
        return True, node, ""

    def mark_visited(self, node_id: str) -> None:
        """노드 처리 완료 후 호출 — 다음 노드 available 업데이트."""
        node = self.nodes.get(node_id)
        if not node:
            return

        node.visited   = True
        node.available = False
        self.current_layer = node.layer

        if node.node_type == "boss":
            self.completed = True
            return

        # 다음 노드 available 활성화
        for next_id in node.next_ids:
            next_node = self.nodes.get(next_id)
            if next_node:
                next_node.available = True

    # ── 직렬화 ────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chapter":       self.chapter,
            "current_layer": self.current_layer,
            "boss_layer":    self.boss_layer,
            "completed":     self.completed,
            "nodes":         {nid: n.to_dict() for nid, n in self.nodes.items()},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FloorMap":
        nodes = {nid: Node.from_dict(nd) for nid, nd in d["nodes"].items()}
        fmap = cls(d["chapter"], nodes)
        fmap.current_layer = d["current_layer"]
        fmap.boss_layer    = d["boss_layer"]
        fmap.completed     = d["completed"]
        return fmap


# ─────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────

def _pick_type(force_battle: bool = False) -> str:
    """가중치 기반 노드 타입 선택."""
    if force_battle:
        return "battle"
    return random.choices(_NAMES, weights=_WGHTS, k=1)[0]


def _connect_layers(cur: List[Node], nxt: List[Node]) -> None:
    """
    현재 층 → 다음 층 연결.
    규칙:
      - 모든 현재 층 노드는 최소 1개의 다음 노드와 연결
      - 모든 다음 층 노드는 최소 1개의 이전 노드와 연결 (고아 방지)
      - 각 노드는 최대 2개까지 연결
    """
    # 1) 다음 층 각 노드에 최소 1개 연결 (고아 방지)
    used_next = set()
    for i, cn in enumerate(cur):
        # 선호 다음 노드: 같은 인덱스 또는 인접
        pref = [n for n in nxt if abs(n.index - cn.index) <= 1]
        target = random.choice(pref if pref else nxt)
        if target.node_id not in cn.next_ids:
            cn.next_ids.append(target.node_id)
        used_next.add(target.node_id)

    # 2) 연결 안 된 다음 층 노드 처리 (고아 방지)
    orphans = [n for n in nxt if n.node_id not in used_next]
    for orphan in orphans:
        donor = random.choice(cur)
        if len(donor.next_ids) < 2 and orphan.node_id not in donor.next_ids:
            donor.next_ids.append(orphan.node_id)
        else:
            # 이미 2개면 다른 노드에서 연결
            for cn in cur:
                if len(cn.next_ids) < 2 and orphan.node_id not in cn.next_ids:
                    cn.next_ids.append(orphan.node_id)
                    break

    # 3) 랜덤 추가 연결 (맵 풍성하게)
    for cn in cur:
        if len(cn.next_ids) < 2 and len(nxt) > 1:
            extras = [n for n in nxt if n.node_id not in cn.next_ids]
            if extras and random.random() < 0.4:
                cn.next_ids.append(random.choice(extras).node_id)