"""Détermination des prix zonaux (spec §4.5).

Une fois les blocs figés, le LP restant peut avoir un ensemble de duals optimaux non réduit à un point
(par exemple une heure où seul un bloc figé fait face à une demande inélastique). Plutôt que de retenir
un dual arbitraire du solveur, on caractérise l'ensemble des prix compatibles avec l'allocation par les
conditions de complémentarité des ordres horaires et des flux, et l'on choisit dans cet ensemble les
prix qui minimisent la violation de cohérence des blocs acceptés, puis l'écart au dual du solveur.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from scipy import sparse

from .model import MilpData
from .orders import BUY, MarketParams
from .solvers import DEFAULT_SOLVER, Solver

log = logging.getLogger("wapp_dam")

PENALTY = 1e4   # poids de la violation de cohérence des blocs face au terme de rapprochement

Prices = dict[tuple[str, int], float]


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


class PriceDeterminer:
    """Prix zonaux compatibles avec une allocation donnée.

    Variables du LP : pi (une par (zone, MTU)), dplus et dminus (écart signé à la cible), slack (une par bloc
    accepté). Contraintes : conditions de complémentarité des ordres horaires (bornes de variable pour les ordres
    mono-MTU, contrainte sur la moyenne des prix pour les ordres multi-MTU, EPD-2025 §5.1), conditions de flux
    (congestion), cohérence des familles de blocs acceptés (surplus >= -slack).

    Cohérence d'un bloc accepté b : surplus de son sous-arbre accepté >= 0 (règle de famille) ; pour une feuille
    ou si la règle de famille est désactivée, le sous-arbre se réduit à b (bloc dans la monnaie en moyenne pondérée).

    Levée de l'indétermination (params.price_rule) : "dual", au plus près du dual du solveur (norme L1) ;
    "midpoint", au plus près du milieu de l'intervalle admissible de chaque (zone, MTU) donné par les ordres
    horaires mono-MTU (moindres carrés, comme EUPHEMIA, EPD-2025 annexe C), après une première passe L1 qui fixe
    la cohérence des blocs.
    """

    def __init__(self, d: MilpData, x: np.ndarray, params: MarketParams, solver: Optional[Solver] = None):
        self.d, self.idx, self.x, self.p = d, d.idx, x, params
        self.solver = solver or DEFAULT_SOLVER
        self.tol = params.tolerance
        self.zh = list(self.idx.balance_index.keys())
        self.pos = {k: i for i, k in enumerate(self.zh)}
        self.n_pi = len(self.zh)
        self.acc = [j for j, b in enumerate(self.idx.blocks) if x[self.idx.col_r(j)] > self.tol and b.volume > 0]
        self.n_s = len(self.acc)
        self.n = 3 * self.n_pi + self.n_s
        self.refine_failed = False      # vrai si la projection quadratique a échoué (prix L1 conservés)
        self.lo = np.full(self.n_pi, -np.inf)     # bornes sur pi issues des ordres mono-MTU
        self.hi = np.full(self.n_pi, np.inf)
        self._rows: list[int] = []
        self._cols: list[int] = []
        self._vals: list[float] = []
        self._rhs: list[float] = []

    # ------------------------------------------------------------ construction des contraintes

    def _add(self, coefs: dict[int, float], rhs: float) -> None:
        r = len(self._rhs)
        for col, v in coefs.items():
            self._rows.append(r); self._cols.append(col); self._vals.append(v)
        self._rhs.append(rhs)

    def _hourly_conditions(self) -> None:
        """Achat accepté -> pi <= p ; rejeté -> pi >= p ; partiel -> pi = p (les deux). Symétrique en vente.
        Pour un ordre multi-MTU, pi est la moyenne arithmétique des prix de ses MTU (EPD-2025 §5.1)."""
        idx, x, pos, tol = self.idx, self.x, self.pos, self.tol
        for i, o in enumerate(idx.hourly):
            xi = x[idx.col_x(i)]
            full, none = xi >= 1 - tol, xi <= tol
            if o.n_mtu == 1:                                   # bornes de variable, sans ligne de contrainte
                k = pos[(o.zone, o.hour)]
                if o.side == BUY:
                    if not none:
                        self.hi[k] = min(self.hi[k], o.price)
                    if not full:
                        self.lo[k] = max(self.lo[k], o.price)
                else:
                    if not none:
                        self.lo[k] = max(self.lo[k], o.price)
                    if not full:
                        self.hi[k] = min(self.hi[k], o.price)
                continue
            w = 1.0 / o.n_mtu
            ks: dict[int, float] = {}
            for h in o.mtus:
                k = pos[(o.zone, h)]
                ks[k] = ks.get(k, 0.0) + w
            if o.side == BUY:
                if not none:
                    self._add(dict(ks), o.price)                              # moyenne pi <= p
                if not full:
                    self._add({k: -v for k, v in ks.items()}, -o.price)       # moyenne pi >= p
            else:
                if not none:
                    self._add({k: -v for k, v in ks.items()}, -o.price)       # moyenne pi >= p
                if not full:
                    self._add(dict(ks), o.price)                              # moyenne pi <= p

    def _flow_conditions(self) -> None:
        """f = 0 -> (1-λ) pi_to <= pi_from ; f = A -> (1-λ) pi_to >= pi_from ; intermédiaire -> égalité."""
        idx, x, pos, tol = self.idx, self.x, self.pos, self.tol
        for l in idx.links:
            for h in idx.hours:
                f = x[idx.col_f(l.id, h)]
                a = float(l.atc.get(h, 0.0))
                kf, kt = pos[(l.from_zone, h)], pos[(l.to_zone, h)]
                g = 1.0 - l.loss_factor
                if a <= tol:
                    continue
                if f >= tol:                          # utilisé : (1-λ) pi_to >= pi_from
                    self._add({kt: -g, kf: 1.0}, 0.0)
                if f <= a - tol:                      # non saturé : (1-λ) pi_to <= pi_from
                    self._add({kt: g, kf: -1.0}, 0.0)

    def _block_conditions(self) -> None:
        """Surplus du sous-arbre accepté de b >= -slack, où surplus(b') = s r (p V - sum q pi)
        <=>  sum_{b'} s r sum_h q pi  -  slack  <=  sum_{b'} s r p V."""
        idx, x, pos, tol = self.idx, self.x, self.pos, self.tol
        for s, j in enumerate(self.acc):
            sub = accepted_subtree(idx, x, j, tol) if self.p.linked_family_rule else [j]
            coefs: dict[int, float] = {}
            rhs = 0.0
            for k in sub:
                bk = idx.blocks[k]
                rk = float(x[idx.col_r(k)])
                for h, q in bk.profile.items():
                    key = pos[(bk.zone, h)]
                    coefs[key] = coefs.get(key, 0.0) + bk.side * rk * q
                rhs += bk.side * rk * bk.price * bk.volume
            coefs[3 * self.n_pi + s] = -1.0
            self._add(coefs, rhs)

    # ------------------------------------------------------------ résolution

    def _midpoints(self) -> np.ndarray:
        """Milieu de l'intervalle admissible de chaque (zone, MTU), borné par les prix plancher et plafond."""
        lo_b = np.where(np.isfinite(self.lo), self.lo, self.p.price_min)
        hi_b = np.where(np.isfinite(self.hi), self.hi, self.p.price_max)
        mid = (np.where(np.isfinite(lo_b), lo_b, hi_b) + np.where(np.isfinite(hi_b), hi_b, lo_b)) / 2.0
        return np.where(np.isfinite(mid), mid, 0.0)

    def run(self, dual_hint: Prices) -> tuple[Prices, dict[str, float]]:
        """Retourne (prix par (zone, MTU), violation par bloc accepté en USD/MWh moyen)."""
        n_pi, n_s, n = self.n_pi, self.n_s, self.n
        self._hourly_conditions()
        self._flow_conditions()
        self._block_conditions()
        r = len(self._rhs)
        c = np.zeros(n)
        c[n_pi:3 * n_pi] = 1.0
        c[3 * n_pi:] = PENALTY * np.array([self.idx.blocks[j].volume for j in self.acc]) if n_s else []
        A_ub = sparse.csr_matrix((self._vals, (self._rows, self._cols)), shape=(r, n)) if r else None
        b_ub = np.array(self._rhs) if r else None
        # Rapprochement de la cible : pi - dplus + dminus = target
        A_eq = sparse.hstack([sparse.identity(n_pi), -sparse.identity(n_pi), sparse.identity(n_pi),
                              sparse.csr_matrix((n_pi, n_s))]).tocsr()
        mid = self._midpoints()
        target = mid if self.p.price_rule == "midpoint" else np.array([dual_hint[k] for k in self.zh])
        bounds = [(None if not np.isfinite(self.lo[i]) else float(self.lo[i]),
                   None if not np.isfinite(self.hi[i]) else float(self.hi[i]))
                  for i in range(n_pi)] + [(0, None)] * (2 * n_pi + n_s)
        try:
            sol = self.solver.solve_lp(c, A_ub, b_ub, A_eq, target, bounds)
        except RuntimeError as e:
            raise RuntimeError(f"LP de détermination des prix non résolu : {e}") from e
        pi = sol.x[:n_pi].copy()
        slack = sol.x[3 * n_pi:].copy()
        if self.p.price_rule == "midpoint" and (n_s == 0 or float(np.max(slack)) <= 1e-7):
            pi = self._refine(pi, mid, A_ub, b_ub)
        prices = {k: float(pi[self.pos[k]]) for k in self.zh}
        viol = {self.idx.blocks[j].id: float(slack[s]) / max(float(self.x[self.idx.col_r(j)]) * self.idx.blocks[j].volume, 1e-9)
                for s, j in enumerate(self.acc)}
        return prices, viol

    def _refine(self, pi0: np.ndarray, mid: np.ndarray, A_ub, b_ub) -> np.ndarray:
        """Dans le polyèdre des prix cohérents (blocs sans slack), prix au plus près des milieux au sens L2
        (programme quadratique convexe délégué au solveur ; on garde pi0 si la projection échoue)."""
        n_pi = self.n_pi
        if A_ub is not None:
            A = A_ub.tocsc()[:, :n_pi].tocsr()
            keep = np.asarray(np.abs(A).sum(axis=1)).ravel() > 0
            A, b = A[keep], b_ub[keep]
        else:
            A, b = sparse.csr_matrix((0, n_pi)), np.zeros(0)
        p = self.solver.solve_projection(mid, A, b, self.lo, self.hi, x0=pi0)
        if p is None or (len(b) and float(np.max(A @ p - b)) > 1e-6):
            # Signalé, et non silencieux : le point L1 est admissible mais n'est pas l'optimum de la règle « midpoint »
            # (cause d'un écart de 0.01 EUR/MWh sur l'écart moyen du rejeu GME publié en 0.4.0).
            self.refine_failed = True
            log.warning("affinage quadratique des prix non résolu : prix de la passe L1 conservés")
            return pi0
        return p


def determine_prices(d: MilpData, x: np.ndarray, dual_hint: Prices, params: MarketParams,
                     solver: Optional[Solver] = None) -> tuple[Prices, dict[str, float]]:
    """Façade fonctionnelle de `PriceDeterminer`."""
    return PriceDeterminer(d, x, params, solver).run(dual_hint)
