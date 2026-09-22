"""Abstraction du solveur numérique.

Le moteur n'appelle jamais SciPy ou HiGHS directement : il passe par un objet `Solver` qui expose trois
problèmes canoniques (MILP du clearing, LP générique avec duals, QP de projection). L'implémentation par
défaut, `HighsSolver`, s'appuie sur HiGHS (via SciPy pour le MILP et le LP, via highspy pour le QP).
Un autre solveur (CPLEX, Gurobi) s'ajoute en implémentant le même protocole, sans toucher au reste du code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

import numpy as np
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, linprog, milp, minimize

from .model import MilpData

MAX_QP_VARS = 600  # taille au-delà de laquelle le secours SLSQP (sans highspy) est sauté


@dataclass
class MilpSolution:
    x: np.ndarray
    objective: float          # valeur de l'objectif minimisé (= - bien-être)


@dataclass
class LpSolution:
    x: np.ndarray
    duals_eq: np.ndarray      # multiplicateurs des contraintes d'égalité (vide si absentes)


class Solver(Protocol):
    """Protocole minimal attendu par `Clearing` et `PriceDeterminer`."""

    def solve_milp(self, d: MilpData, time_limit: Optional[float] = None) -> MilpSolution: ...

    def solve_lp(self, c: np.ndarray, A_ub, b_ub, A_eq, b_eq,
                 bounds: Sequence[tuple[Optional[float], Optional[float]]]) -> LpSolution: ...

    def solve_projection(self, target: np.ndarray, A, b: np.ndarray, lo: np.ndarray, hi: np.ndarray,
                         x0: Optional[np.ndarray] = None) -> Optional[np.ndarray]: ...


class HighsSolver:
    """HiGHS : MILP et LP par SciPy (method="highs"), QP de projection par highspy, secours SLSQP."""

    def solve_milp(self, d: MilpData, time_limit: Optional[float] = None) -> MilpSolution:
        cons = [LinearConstraint(d.A_eq, d.b_eq, d.b_eq)]
        if d.A_ub.shape[0] > 0:
            cons.append(LinearConstraint(d.A_ub, -np.inf, d.b_ub))
        opts = {} if time_limit is None else {"time_limit": time_limit}
        res = milp(d.c, constraints=cons, integrality=d.integrality, bounds=Bounds(d.lb, d.ub), options=opts)
        if res.status != 0 or res.x is None:
            raise RuntimeError(f"MILP non résolu : {res.message}")
        return MilpSolution(np.array(res.x, dtype=float), float(res.fun))

    def solve_lp(self, c, A_ub, b_ub, A_eq, b_eq, bounds) -> LpSolution:
        res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
        if res.status != 0:
            raise RuntimeError(f"LP non résolu : {res.message}")
        duals = np.asarray(res.eqlin.marginals, dtype=float) if A_eq is not None else np.zeros(0)
        return LpSolution(np.array(res.x, dtype=float), duals)

    def solve_projection(self, target, A, b, lo, hi, x0=None) -> Optional[np.ndarray]:
        """min sum (x - target)^2  s.c.  A x <= b,  lo <= x <= hi.  None si non résolu."""
        p = self._qp_highs(target, A, b, lo, hi)
        if p is None and x0 is not None and len(target) <= MAX_QP_VARS:
            p = self._qp_slsqp(x0, target, A, b, lo, hi)
        return p

    @staticmethod
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
        Ac = sparse.csc_matrix(A)
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

    @staticmethod
    def _qp_slsqp(x0, mid, A, b, lo, hi):
        Ad = sparse.csr_matrix(A).toarray()
        bounds = [(None if not np.isfinite(l) else float(l), None if not np.isfinite(u) else float(u))
                  for l, u in zip(lo, hi)]
        cons = [{"type": "ineq", "fun": lambda p, A=Ad, b=b: b - A @ p, "jac": lambda p, A=Ad: -A}] if len(b) else []
        res = minimize(lambda p: float(np.sum((p - mid) ** 2)), x0, jac=lambda p: 2.0 * (p - mid),
                       bounds=bounds, constraints=cons, method="SLSQP", options={"maxiter": 500, "ftol": 1e-12})
        return np.array(res.x, dtype=float) if res.success else None


DEFAULT_SOLVER: Solver = HighsSolver()
