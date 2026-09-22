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
from scipy.optimize import linprog, minimize

from .model import MilpData
from .orders import BUY, SELL

PENALTY = 1e4   # poids de la violation de cohérence des blocs face au terme de rapprochement
MAX_QP_VARS = 600  # taille au-delà de laquelle l'affinage SLSQP (secours sans highspy) est sauté


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
                     tol: float = 1e-6, family_rule: bool = True, price_rule: str = "dual",
                     price_bounds: tuple[float, float] | None = None) -> tuple[dict[tuple[str, int], float], dict[str, float]]:
    """Retourne (prix par (zone, heure), violation par bloc accepté en USD/MWh moyen).

    Cohérence d'un bloc accepté b : surplus de son sous-arbre accepté >= 0 (règle de famille) ; pour une feuille
    ou si la règle de famille est désactivée, le sous-arbre se réduit à b (bloc dans la monnaie en moyenne pondérée).

    Levée de l'indétermination (price_rule) : "dual", au plus près du dual du solveur (norme L1) ; "midpoint",
    au plus près du milieu de l'intervalle admissible de chaque (zone, MTU) donné par les ordres horaires mono-MTU
    (moindres carrés, comme EUPHEMIA, EPD-2025 annexe C), après une première passe L1 qui fixe la cohérence des blocs.
    """
    idx = d.idx
    zh = list(idx.balance_index.keys())
    pos = {k: i for i, k in enumerate(zh)}
    n_pi = len(zh)
    pmin, pmax = price_bounds if price_bounds else (-np.inf, np.inf)
    lo = np.full(n_pi, -np.inf)
    hi = np.full(n_pi, np.inf)
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
    # Pour un ordre multi-MTU, pi est la moyenne arithmétique des prix de ses MTU (EPD-2025 §5.1).
    for i, o in enumerate(idx.hourly):
        xi = x[idx.col_x(i)]
        full, none = xi >= 1 - tol, xi <= tol
        if o.n_mtu == 1:                                   # bornes de variable, sans ligne de contrainte
            k = pos[(o.zone, o.hour)]
            if o.side == BUY:
                if not none:
                    hi[k] = min(hi[k], o.price)
                if not full:
                    lo[k] = max(lo[k], o.price)
            else:
                if not none:
                    lo[k] = max(lo[k], o.price)
                if not full:
                    hi[k] = min(hi[k], o.price)
            continue
        w = 1.0 / o.n_mtu
        ks = {}
        for h in o.mtus:
            k = pos[(o.zone, h)]
            ks[k] = ks.get(k, 0.0) + w
        if o.side == BUY:
            if not none:
                add(dict(ks), o.price)                              # moyenne pi <= p
            if not full:
                add({k: -v for k, v in ks.items()}, -o.price)       # moyenne pi >= p
        else:
            if not none:
                add({k: -v for k, v in ks.items()}, -o.price)       # moyenne pi >= p
            if not full:
                add(dict(ks), o.price)                              # moyenne pi <= p
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
    lo_b = np.where(np.isfinite(lo), lo, pmin)
    hi_b = np.where(np.isfinite(hi), hi, pmax)
    mid = (np.where(np.isfinite(lo_b), lo_b, hi_b) + np.where(np.isfinite(hi_b), hi_b, lo_b)) / 2.0
    mid = np.where(np.isfinite(mid), mid, 0.0)
    target = mid if price_rule == "midpoint" else np.array([dual_hint[k] for k in zh])
    bounds = [(None if not np.isfinite(lo[i]) else float(lo[i]), None if not np.isfinite(hi[i]) else float(hi[i]))
              for i in range(n_pi)] + [(0, None)] * (2 * n_pi + n_s)
    res = linprog(c, A_ub=A_ub, b_ub=np.array(b_ub) if r else None, A_eq=A_eq, b_eq=target,
                  bounds=bounds, method="highs")
    if res.status != 0:
        raise RuntimeError(f"LP de détermination des prix non résolu : {res.message}")
    pi = np.array(res.x[:n_pi], dtype=float)
    slack = np.array(res.x[3 * n_pi:], dtype=float)
    if price_rule == "midpoint" and (n_s == 0 or float(np.max(slack)) <= 1e-7):
        pi = _least_squares_refine(pi, mid, A_ub, np.array(b_ub) if r else None, n_pi, bounds[:n_pi])
    prices = {k: float(pi[pos[k]]) for k in zh}
    viol = {idx.blocks[j].id: float(slack[s]) / max(float(x[idx.col_r(j)]) * idx.blocks[j].volume, 1e-9)
            for s, j in enumerate(acc)}
    return prices, viol


def _least_squares_refine(pi0: np.ndarray, mid: np.ndarray, A_ub, b_ub, n_pi: int, bounds) -> np.ndarray:
    """Dans le polyèdre des prix cohérents (blocs sans slack), prix au plus près des milieux au sens L2.

    Programme quadratique convexe : min sum (pi - mid)^2 s.c. A pi <= b, lo <= pi <= hi. Résolu par HiGHS (highspy,
    creux, quelques secondes pour des milliers de variables) ; à défaut, SLSQP de SciPy, réservé aux petites tailles.
    """
    if A_ub is not None:
        A = A_ub.tocsc()[:, :n_pi].tocsr()
        keep = np.asarray(np.abs(A).sum(axis=1)).ravel() > 0
        A, b = A[keep], b_ub[keep]
    else:
        A, b = sparse.csr_matrix((0, n_pi)), np.zeros(0)
    lo = np.array([-np.inf if l is None else l for l, _ in bounds], dtype=float)
    hi = np.array([np.inf if u is None else u for _, u in bounds], dtype=float)
    p = _qp_highs(mid, A, b, lo, hi)
    if p is None:
        if n_pi > MAX_QP_VARS:
            return pi0
        p = _qp_slsqp(pi0, mid, A.toarray(), b, bounds)
        if p is None:
            return pi0
    if len(b) and float(np.max(A @ p - b)) > 1e-6:
        return pi0
    return p


def _qp_highs(mid, A, b, lo, hi):
    try:
        import highspy
    except ImportError:
        return None
    n, m = len(mid), A.shape[0]
    inf = highspy.kHighsInf
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = n, m
    lp.col_cost_ = (-2.0 * mid).astype(float)
    lp.col_lower_ = np.where(np.isfinite(lo), lo, -inf)
    lp.col_upper_ = np.where(np.isfinite(hi), hi, inf)
    lp.row_lower_ = np.full(m, -inf)
    lp.row_upper_ = np.asarray(b, dtype=float)
    Ac = A.tocsc()
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = Ac.indptr.astype(np.int32)
    lp.a_matrix_.index_ = Ac.indices.astype(np.int32)
    lp.a_matrix_.value_ = Ac.data.astype(float)
    hess = highspy.HighsHessian()
    hess.dim_ = n
    hess.format_ = highspy.HessianFormat.kTriangular
    hess.start_ = np.arange(n + 1, dtype=np.int32)
    hess.index_ = np.arange(n, dtype=np.int32)
    hess.value_ = np.full(n, 2.0)
    model = highspy.HighsModel()
    model.lp_, model.hessian_ = lp, hess
    h = highspy.Highs()
    h.silent()
    h.passModel(model)
    h.run()
    if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        return None
    return np.array(h.getSolution().col_value, dtype=float)


def _qp_slsqp(pi0, mid, A, b, bounds):
    cons = [{"type": "ineq", "fun": lambda p, A=A, b=b: b - A @ p, "jac": lambda p, A=A: -A}] if len(b) else []
    res = minimize(lambda p: float(np.sum((p - mid) ** 2)), pi0, jac=lambda p: 2.0 * (p - mid),
                   bounds=bounds, constraints=cons, method="SLSQP", options={"maxiter": 500, "ftol": 1e-12})
    return np.array(res.x, dtype=float) if res.success else None
