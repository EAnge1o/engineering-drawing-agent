"""参数传播：派生参数重算 + 参数变更入口。

变更任一参数后，沿依赖图按拓扑序重算其下游的派生参数（expr），
保证"改一个值 → 相关参数同步"的语义正确。
"""
from __future__ import annotations

import re

import networkx as nx

from .models import Spec

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_FUNCS = {"min": min, "max": max, "abs": abs, "round": round}
_NUM_LIT = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def _sanitize(name: str) -> str:
    return name.replace(".", "_")


def _eval_expr(expr: str, env: dict[str, float]) -> float:
    """在受控命名空间下求值算术表达式（变量名中的 '.' 映射为 '_'）。

    - 支持数字字面量（含科学计数法，如 1e5），不会把 `e5` 误判为变量
    - 支持白名单函数 min/max/abs/round
    """
    holders: dict[str, str] = {}

    def protect_num(m: re.Match) -> str:
        key = f"_num_lit_{len(holders)}"
        holders[key] = m.group(0)
        return key

    tmp = _NUM_LIT.sub(protect_num, expr)

    def repl(m: re.Match) -> str:
        key = m.group(0)
        if key in holders:   # 数字字面量占位符，原样保留
            return key
        if key in _FUNCS:
            return key
        if key in env:
            return _sanitize(key)
        if _sanitize(key) in env:
            return _sanitize(key)
        raise ValueError(f"表达式引用了未知变量: {key}")

    safe = _IDENT_RE.sub(repl, tmp)
    names: dict[str, object] = {_sanitize(k): v for k, v in env.items()}
    names.update(_FUNCS)
    names.update({k: float(v) for k, v in holders.items()})
    return float(eval(safe, {"__builtins__": {}}, names))  # noqa: S307


def recompute_derived(spec: Spec) -> Spec:
    """按拓扑序重算所有派生参数。"""
    g = nx.DiGraph()
    for pid, p in spec.params.items():
        g.add_node(pid)
        for d in p.depends_on:
            if d in spec.params:
                g.add_edge(d, pid)
    if not nx.is_directed_acyclic_graph(g):
        raise ValueError("参数依赖存在环，无法重算")

    for pid in nx.topological_sort(g):
        p = spec.params[pid]
        if p.expr:
            env = {d: spec.params[d].value for d in p.depends_on}
            p.value = _eval_expr(p.expr, env)
    return spec


def set_param(spec: Spec, pid: str, value: float) -> Spec:
    """设置参数值并传播到下游派生参数。"""
    if pid not in spec.params:
        raise KeyError(f"未知参数: {pid}")
    p = spec.params[pid]
    p.value = float(value)
    if p.kind == "derived":
        # 派生参数被直接改写时，视为"观测值"覆盖：断开派生关系，保留当前值
        p.kind = "geometry"
        p.depends_on = []
        p.expr = None
    return recompute_derived(spec)