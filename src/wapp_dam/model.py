"""Construction du programme linéaire mixte (spec §4).

Variables (dans l'ordre) : x_o (ordres horaires), r_b (ratio des blocs), u_b (indicateur des blocs),
f_{l,h} (flux orientés). Contraintes : équilibre zonal par heure (égalité, dont la variable duale
est le prix), MAR, blocs liés, groupes exclusifs, capacités (par bornes).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import sparse

from .orders import BlockOrder, HourlyOrder, Link, Market


@dataclass
class ModelIndex:
    hourly: list[HourlyOrder]
    blocks: list[BlockOrder]
    links: list[Link]
    hours: list[int]
    zones: list[str]
    n_x: int
    n_r: int
    n_u: int
    n_f: int
    flow_index: dict[tuple[str, int], int] = field(default_factory=dict)   # (link_id, hour) -> col
    balance_index: dict[tuple[str, int], int] = field(default_factory=dict)  # (zone, hour) -> row

    @property
    def n_vars(self) -> int:
        return self.n_x + self.n_r + self.n_u + self.n_f

    def col_x(self, i: int) -> int:
        return i

    def col_r(self, j: int) -> int:
        return self.n_x + j

    def col_u(self, j: int) -> int:
        return self.n_x + self.n_r + j

    def col_f(self, link_id: str, h: int) -> int:
        return self.n_x + self.n_r + self.n_u + self.flow_index[(link_id, h)]


@dataclass
class MilpData:
    idx: ModelIndex
    c: np.ndarray                 # objectif à minimiser (= - bien-être)
    A_eq: sparse.csr_matrix       # équilibres zonaux
    b_eq: np.ndarray
    A_ub: sparse.csr_matrix       # MAR, blocs liés, groupes exclusifs
    b_ub: np.ndarray
    lb: np.ndarray
    ub: np.ndarray
    integrality: np.ndarray


def build(market: Market, hourly: list[HourlyOrder], blocks: list[BlockOrder],
          forced_reject: frozenset[str] = frozenset()) -> MilpData:
    hours = list(market.hour_range)
    zones = list(market.zones)
    links = list(market.links)
    n_x, n_r, n_u = len(hourly), len(blocks), len(blocks)
    flow_index: dict[tuple[str, int], int] = {}
    for l in links:
        for h in hours:
            flow_index[(l.id, h)] = len(flow_index)
    n_f = len(flow_index)
    idx = ModelIndex(hourly, blocks, links, hours, zones, n_x, n_r, n_u, n_f, flow_index)
    n = idx.n_vars

    # Objectif : max sum s p q x + sum s p V_b r_b  ->  min -(...)
    c = np.zeros(n)
    for i, o in enumerate(hourly):
        c[idx.col_x(i)] = -o.side * o.price * o.quantity
    for j, b in enumerate(blocks):
        c[idx.col_r(j)] = -b.side * b.price * b.volume

    # Équilibre zonal (z, h) : sum(-s q x) + sum(-s q_bh r_b) - sum_out f + sum_in (1-λ) f = 0
    rows, cols, vals = [], [], []
    for z in zones:
        for h in hours:
            idx.balance_index[(z, h)] = len(idx.balance_index)
    for i, o in enumerate(hourly):
        rows.append(idx.balance_index[(o.zone, o.hour)]); cols.append(idx.col_x(i)); vals.append(-o.side * o.quantity)
    for j, b in enumerate(blocks):
        for h, q in b.profile.items():
            rows.append(idx.balance_index[(b.zone, h)]); cols.append(idx.col_r(j)); vals.append(-b.side * q)
    for l in links:
        for h in hours:
            col = idx.col_f(l.id, h)
            rows.append(idx.balance_index[(l.from_zone, h)]); cols.append(col); vals.append(-1.0)
            rows.append(idx.balance_index[(l.to_zone, h)]); cols.append(col); vals.append(1.0 - l.loss_factor)
    m_eq = len(idx.balance_index)
    A_eq = sparse.csr_matrix((vals, (rows, cols)), shape=(m_eq, n))
    b_eq = np.zeros(m_eq)

    # Inégalités
    rows, cols, vals, b_ub = [], [], [], []
    r = 0
    by_id = {b.id: j for j, b in enumerate(blocks)}
    for j, b in enumerate(blocks):
        # m_b u_b - r_b <= 0
        rows += [r, r]; cols += [idx.col_u(j), idx.col_r(j)]; vals += [b.mar, -1.0]; b_ub.append(0.0); r += 1
        # r_b - u_b <= 0
        rows += [r, r]; cols += [idx.col_r(j), idx.col_u(j)]; vals += [1.0, -1.0]; b_ub.append(0.0); r += 1
        # u_enfant - u_parent <= 0 (MC 13.1.2.1 c) et r_enfant - r_parent <= 0 (EPD-2025 §5.4.1 règle 1)
        if b.parent is not None and b.parent in by_id:
            rows += [r, r]; cols += [idx.col_u(j), idx.col_u(by_id[b.parent])]; vals += [1.0, -1.0]; b_ub.append(0.0); r += 1
            rows += [r, r]; cols += [idx.col_r(j), idx.col_r(by_id[b.parent])]; vals += [1.0, -1.0]; b_ub.append(0.0); r += 1
    groups: dict[str, list[int]] = {}
    for j, b in enumerate(blocks):
        if b.exclusive_group is not None:
            groups.setdefault(b.exclusive_group, []).append(j)
    for js in groups.values():
        for j in js:
            rows.append(r); cols.append(idx.col_r(j)); vals.append(1.0)
        b_ub.append(1.0); r += 1
    A_ub = sparse.csr_matrix((vals, (rows, cols)), shape=(r, n))

    lb = np.zeros(n)
    ub = np.ones(n)
    for l in links:
        for h in hours:
            ub[idx.col_f(l.id, h)] = max(0.0, float(l.atc.get(h, 0.0)))
    for j, b in enumerate(blocks):
        if b.id in forced_reject:
            ub[idx.col_u(j)] = 0.0
            ub[idx.col_r(j)] = 0.0
    integrality = np.zeros(n, dtype=int)
    for j in range(n_u):
        integrality[idx.col_u(j)] = 1
    return MilpData(idx, c, A_eq, b_eq, A_ub, np.array(b_ub), lb, ub, integrality)
