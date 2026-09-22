"""Détermination des prix zonaux (spec §4.5).

Une fois les blocs figés, le LP restant peut avoir un ensemble de duals optimaux non réduit à un point
(par exemple une heure où seul un bloc figé fait face à une demande inélastique). Plutôt que de retenir
un dual arbitraire du solveur, on caractérise l'ensemble des prix compatibles avec l'allocation par les
conditions de complémentarité des ordres horaires et des flux, et l'on choisit dans cet ensemble les
prix qui minimisent la violation de cohérence des blocs acceptés, puis l'écart au dual du solveur.
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.optimize import linprog

from .model import MilpData
from .orders import BUY, SELL

PENALTY = 1e4   # poids de la violation de cohérence des blocs face au terme de rapprochement


def accepted_subtree(idx, x: np.ndarray, j: int, tol: float) -> list[int]:
    """Indices du bloc j et de ses descendants acceptés (famille de blocs liés, EPD-2025 §5.4.1)."""
    children: dict[str, list[int]] = {}
    for k, b in enumerate(idx.blocks):
        if b.parent is not None:
            children.setdefault(b.parent, []).append(k)
    out, stack = [], [j]
    while stack:
        k = stack.pop()
        if x[idx.col_r(k)] > tol:
            out.append(k)
            stack.extend(children.get(idx.blocks[k].id, []))
    return out


def determine_prices(d: MilpData, x: np.ndarray, dual_hint: dict[tuple[str, int], float],
                     tol: float = 1e-6, family_rule: bool = True) -> tuple[dict[tuple[str, int], float], dict[str, float]]:
    """Retourne (prix par (zone, heure), violation par bloc accepté en USD/MWh moyen).

    Cohérence d'un bloc accepté b : surplus de son sous-arbre accepté >= 0 (règle de famille) ; pour une feuille
    ou si la règle de famille est désactivée, le sous-arbre se réduit à b (bloc dans la monnaie en moyenne pondérée).
    """
    idx = d.idx
    zh = list(idx.balance_index.keys())
    pos = {k: i for i, k in enumerate(zh)}
    n_pi = len(zh)
    acc = [j for j, b in enumerate(idx.blocks) if x[idx.col_r(j)] > tol and b.volume > 0]
    n_s = len(acc)
    # variables : pi (n_pi), dplus (n_pi), dminus (n_pi), slack (n_s)
    n = 3 * n_pi + n_s
    c = np.zeros(n)
    c[n_pi:3 * n_pi] = 1.0
    c[3 * n_pi:] = PENALTY * np.array([idx.blocks[j].volume for j in acc]) if n_s else []

    rows, cols, vals, b_ub = [], [], [], []
    r = 0

    def add(coefs: dict[int, float], rhs: float):
        nonlocal r
        for col, v in coefs.items():
            rows.append(r); cols.append(col); vals.append(v)
        b_ub.append(rhs); r += 1

    # Ordres horaires : achat accepté -> pi <= p ; rejeté -> pi >= p ; partiel -> pi = p (les deux). Symétrique en vente.
    for i, o in enumerate(idx.hourly):
        k = pos[(o.zone, o.hour)]
        xi = x[idx.col_x(i)]
        full, none = xi >= 1 - tol, xi <= tol
        if o.side == BUY:
            if not none:
                add({k: 1.0}, o.price)          # pi <= p
            if not full:
                add({k: -1.0}, -o.price)        # pi >= p
        else:
            if not none:
                add({k: -1.0}, -o.price)        # pi >= p
            if not full:
                add({k: 1.0}, o.price)          # pi <= p
    # Flux : f = 0 -> (1-λ) pi_to <= pi_from ; f = A -> (1-λ) pi_to >= pi_from ; intermédiaire -> égalité.
    for l in idx.links:
        for h in idx.hours:
            f = x[idx.col_f(l.id, h)]
            a = float(l.atc.get(h, 0.0))
            kf, kt = pos[(l.from_zone, h)], pos[(l.to_zone, h)]
            g = 1.0 - l.loss_factor
            if a <= tol:
                continue
            if f >= tol:                          # utilisé : (1-λ) pi_to >= pi_from
                add({kt: -g, kf: 1.0}, 0.0)
            if f <= a - tol:                      # non saturé : (1-λ) pi_to <= pi_from
                add({kt: g, kf: -1.0}, 0.0)
    # Cohérence : surplus du sous-arbre accepté de b >= -slack, où surplus(b') = s r (p V - sum q pi)
    #   <=>  sum_{b'} s r sum_h q pi  -  slack  <=  sum_{b'} s r p V
    for s, j in enumerate(acc):
        sub = accepted_subtree(idx, x, j, tol) if family_rule else [j]
        coefs: dict[int, float] = {}
        rhs = 0.0
        for k in sub:
            bk = idx.blocks[k]
            rk = float(x[idx.col_r(k)])
            for h, q in bk.profile.items():
                key = pos[(bk.zone, h)]
                coefs[key] = coefs.get(key, 0.0) + bk.side * rk * q
            rhs += bk.side * rk * bk.price * bk.volume
        coefs[3 * n_pi + s] = -1.0
        add(coefs, rhs)
    A_ub = sparse.csr_matrix((vals, (rows, cols)), shape=(r, n)) if r else None
    # Rapprochement du dual du solveur : pi - dplus + dminus = hint
    A_eq = sparse.hstack([sparse.identity(n_pi), -sparse.identity(n_pi), sparse.identity(n_pi),
                          sparse.csr_matrix((n_pi, n_s))]).tocsr()
    b_eq = np.array([dual_hint[k] for k in zh])
    bounds = [(None, None)] * n_pi + [(0, None)] * (2 * n_pi + n_s)
    res = linprog(c, A_ub=A_ub, b_ub=np.array(b_ub) if r else None, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, method="highs")
    if res.status != 0:
        raise RuntimeError(f"LP de détermination des prix non résolu : {res.message}")
    prices = {k: float(res.x[pos[k]]) for k in zh}
    viol = {idx.blocks[j].id: float(res.x[3 * n_pi + s]) / max(float(x[idx.col_r(j)]) * idx.blocks[j].volume, 1e-9)
            for s, j in enumerate(acc)}
    return prices, viol
