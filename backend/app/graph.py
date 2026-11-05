"""参数依赖图（Constraint Dependency Graph）与变更影响分析。

图节点类型：param / feature / constraint。
边方向：上游 -> 下游（param -> feature -> constraint，或 param -> param）。
"受影响集合" = 变更节点的下游可达集（descendants）。
"""
from __future__ import annotations

from typing import Iterable

import networkx as nx

from .models import Spec

N_PARAM = "param"
N_FEATURE = "feature"
N_CONSTRAINT = "constraint"


def build_graph(spec: Spec) -> nx.DiGraph:
    """由 Spec 构建有向依赖图。"""
    g = nx.DiGraph()
    for pid, p in spec.params.items():
        g.add_node(pid, ntype=N_PARAM)
        for dep in p.depends_on:
            if dep in spec.params:
                g.add_edge(dep, pid)
    for fid, f in spec.features.items():
        g.add_node(fid, ntype=N_FEATURE)
        for pid in f.params:
            if pid in g:
                g.add_edge(pid, fid)
        for dep in f.depends_on:
            if dep in g:
                g.add_edge(dep, fid)
    for cid, c in spec.constraints.items():
        g.add_node(cid, ntype=N_CONSTRAINT)
        for pid in c.params:
            if pid in g:
                g.add_edge(pid, cid)
        for fid in c.features:
            if fid in g:
                g.add_edge(fid, cid)
    return g


def affected_nodes(g: nx.DiGraph, changed: Iterable[str]) -> set[str]:
    """返回变更节点的下游可达集（不含变更节点本身）。"""
    out: set[str] = set()
    for n in changed:
        if n in g:
            out |= nx.descendants(g, n)
    return out


def _by_type(g: nx.DiGraph, nodes: set[str], ntype: str) -> set[str]:
    return {n for n in nodes if g.nodes[n].get("ntype") == ntype}


def affected_features(g: nx.DiGraph, changed: Iterable[str]) -> set[str]:
    return _by_type(g, affected_nodes(g, changed), N_FEATURE)


def affected_constraints(g: nx.DiGraph, changed: Iterable[str]) -> set[str]:
    return _by_type(g, affected_nodes(g, changed), N_CONSTRAINT)


def impact_metrics(predicted: set[str], truth: set[str]) -> dict[str, float]:
    """影响集评估：precision / recall / F1。"""
    tp = len(predicted & truth)
    precision = (tp / len(predicted)) if predicted else (1.0 if not truth else 0.0)
    # 真值为空表示"无约束失效"，应视为无遗漏（recall=1）；预测非空只影响 precision
    recall = (tp / len(truth)) if truth else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": len(predicted - truth),
        "fn": len(truth - predicted),
    }