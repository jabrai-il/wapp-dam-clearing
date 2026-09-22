"""Algorithme de clearing (spec §4.6, révisé v0.2 d'après EPD-2025) :
MILP, fixation des blocs incohérents (règles de famille), LP de prix, départage, arrondi, rapport de cohérence."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import numpy as np

from .model import MilpData, build
from .orders import BUY, SELL, BlockOrder, HourlyOrder, Market
from .prices import PriceDeterminer, accepted_subtree
from .solvers import DEFAULT_SOLVER, LpSolution, Solver
from .validation import ValidationReport, validate

log = logging.getLogger("wapp_dam")

BLOCK_ACCEPTED = "accepted"
BLOCK_REJECTED = "rejected"                 # hors de la monnaie, rejeté
BLOCK_PARADOX = "paradoxically_rejected"    # dans la monnaie mais rejeté : admis (EPD-2025 §5.4)
BLOCK_FORCED = "forced_rejected"            # rejeté par l'itération de cohérence

LEVEL_OK, LEVEL_TECH, LEVEL_DECOUPLING = "OK", "TECHNICAL", "DECOUPLING"


def round_half_up(v: float, decimals: int = 0) -> float:
    q = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(v)).quantize(q, rounding=ROUND_HALF_UP))


@dataclass
class BlockResult:
    id: str
    participant: str
    zone: str
    side: int
    price: float
    ratio: float                    # ratio non arrondi
    status: str
    weighted_price: float | None    # prix moyen pondéré par le profil sur les heures du bloc
    mw: dict[int, float] = field(default_factory=dict)   # MW publiés par heure (arrondis si round_volumes)
    ratio_published: float = 0.0    # somme des MW publiés / volume
    family_surplus: float | None = None  # surplus du sous-arbre accepté (USD), blocs acceptés seulement


@dataclass
class LinkHourResult:
    link: str
    from_zone: str
    to_zone: str
    hour: int
    flow: float
    atc: float
    congested: bool
    rent: float                     # ((1-λ) π_to - π_from) f, revient au SMO (MC 16.1)


@dataclass
class CoherenceCheck:
    name: str
    gap: float
    level: str
    detail: str = ""


@dataclass
class CoherenceReport:
    """Rapport de validation de la solution (EPD-2025 §8.2) : écart max par famille de contrainte et niveau."""
    checks: list[CoherenceCheck]

    @property
    def level(self) -> str:
        order = {LEVEL_OK: 0, LEVEL_TECH: 1, LEVEL_DECOUPLING: 2}
        return max((c.level for c in self.checks), key=lambda l: order[l], default=LEVEL_OK)


@dataclass
class ClearingResult:
    validation: ValidationReport
    prices: dict[tuple[str, int], float]           # (zone, heure) -> USD/MWh, écrêtés et arrondis
    raw_prices: dict[tuple[str, int], float]       # prix déterminés avant écrêtage/arrondi
    clipped: set[tuple[str, int]]
    hourly_ratio: dict[str, float]                 # id -> ratio accepté (non arrondi)
    hourly_mw: dict[str, float]                    # id -> MW publiés (arrondis si round_volumes)
    blocks: list[BlockResult]
    links: list[LinkHourResult]
    welfare: float                                 # bien-être régional (objectif MILP, dernière itération)
    welfare_first: float                           # bien-être de la première itération (avant rejets forcés)
    iterations: int
    coherence: CoherenceReport
    log: list[str] = field(default_factory=list)

    # ---- sorties dérivées (spec §5) ----
    def positions(self) -> dict[tuple[str, int], tuple[float, float]]:
        """(participant, heure) -> (MW net, USD net). Achat positif ; l'acheteur doit π·q, le vendeur reçoit π·q."""
        pos: dict[tuple[str, int], list[float]] = {}
        for o in self.validation.accepted_hourly:
            mw = o.side * self.hourly_mw[o.id]
            for h in o.mtus:
                p = pos.setdefault((o.participant, h), [0.0, 0.0])
                p[0] += mw
                p[1] += mw * self.prices[(o.zone, h)]
        for br in self.blocks:
            for h, q in br.mw.items():
                mw = br.side * q
                p = pos.setdefault((br.participant, h), [0.0, 0.0])
                p[0] += mw
                p[1] += mw * self.prices[(br.zone, h)]
        return {k: (v[0], v[1]) for k, v in pos.items()}

    def welfare_by_zone(self) -> dict[str, float]:
        """Surplus des ordres de chaque zone aux prix de clearing (hors rentes de congestion)."""
        w: dict[str, float] = {}
        for o in self.validation.accepted_hourly:
            for h in o.mtus:
                w[o.zone] = w.get(o.zone, 0.0) + o.side * (o.price - self.prices[(o.zone, h)]) * self.hourly_mw[o.id]
        for br in self.blocks:
            for h, q in br.mw.items():
                w[br.zone] = w.get(br.zone, 0.0) + br.side * (br.price - self.prices[(br.zone, h)]) * q
        return w

    def congestion_rent(self) -> float:
        return float(sum(l.rent for l in self.links))

    def accepted_volume(self, zone: str, hour: int, side: int) -> float:
        v = sum(self.hourly_mw[o.id] for o in self.validation.accepted_hourly
                if o.zone == zone and hour in o.mtus and o.side == side)
        v += sum(br.mw.get(hour, 0.0) for br in self.blocks if br.zone == zone and br.side == side)
        return v

    def curtailed_price_takers(self, price_max: float) -> dict[tuple[str, int], float]:
        """(zone, heure) -> MW de demande preneuse de prix (au plafond) non servie."""
        out: dict[tuple[str, int], float] = {}
        for o in self.validation.accepted_hourly:
            if o.side == BUY and o.price >= price_max - 1e-9:
                for h in o.mtus:
                    out[(o.zone, h)] = out.get((o.zone, h), 0.0) + o.quantity - self.hourly_mw[o.id]
        return {k: v for k, v in out.items() if v > 1e-6}

    def hhi(self, zone: str, hour: int, side: int = SELL) -> float | None:
        """Indice de Herfindahl-Hirschman des volumes acceptés (base MC 21/22), None si volume nul."""
        shares: dict[str, float] = {}
        for o in self.validation.accepted_hourly:
            if o.zone == zone and hour in o.mtus and o.side == side:
                shares[o.participant] = shares.get(o.participant, 0.0) + self.hourly_mw[o.id]
        for br in self.blocks:
            if br.zone == zone and br.side == side and hour in br.mw:
                shares[br.participant] = shares.get(br.participant, 0.0) + br.mw[hour]
        tot = sum(shares.values())
        if tot <= 0:
            return None
        return float(sum((s / tot * 100) ** 2 for s in shares.values()))


# ---------------------------------------------------------------- algorithme

def _block_key(b: BlockOrder) -> tuple:
    return (b.zone, b.side, b.price, b.mar, tuple(sorted(b.profile.items())), b.exclusive_group)


class Clearing:
    """Clearing d'une journée de marché : validation, itération MILP / prix / cohérence des blocs, départage,
    rapport de cohérence, écrêtage et arrondi. `run()` renvoie le `ClearingResult`.

    L'état de l'itération courante (données du MILP `d`, solution `x`, prix bruts `raw`, violations `viol`) est
    porté par l'instance ; les étapes sont des méthodes qui le lisent ou le modifient en place.
    """

    def __init__(self, market: Market, solver: Optional[Solver] = None):
        self.market = market
        self.p = market.params
        self.tol = market.params.tolerance
        self.solver = solver or DEFAULT_SOLVER
        self.journal: list[str] = []
        self.forced: set[str] = set()
        self.d: MilpData
        self.x: np.ndarray
        self.raw: dict[tuple[str, int], float] = {}
        self.viol: dict[str, float] = {}
        self.welfare: float = 0.0
        self.welfare_first: float | None = None
        self.iterations: int = 0

    # ------------------------------------------------------------ étapes

    def _solve_lp_fixed(self, x_milp: np.ndarray) -> LpSolution:
        """Blocs figés à leur valeur optimale : LP restant, duals des équilibres comme point de référence."""
        d, idx = self.d, self.d.idx
        lb, ub = d.lb.copy(), d.ub.copy()
        for j in range(idx.n_r):
            for col in (idx.col_r(j), idx.col_u(j)):
                v = float(np.clip(round(x_milp[col], 9), lb[col], ub[col]))
                lb[col] = ub[col] = v
        A_ub = d.A_ub if d.A_ub.shape[0] > 0 else None
        b_ub = d.b_ub if d.A_ub.shape[0] > 0 else None
        try:
            return self.solver.solve_lp(d.c, A_ub, b_ub, d.A_eq, d.b_eq, list(zip(lb, ub)))
        except RuntimeError as e:
            raise RuntimeError(f"LP dual non résolu : {e}") from e

    def _iterate(self, hourly: list[HourlyOrder], blocks: list[BlockOrder]) -> None:
        """Boucle de fixation des blocs incohérents (spec §4.6) : à chaque tour, MILP, LP à blocs figés, prix ;
        les blocs acceptés hors de la monnaie (au sens de leur famille) sont forcés au rejet et l'on recommence."""
        p = self.p
        for it in range(1, p.block_fix_max_iter + 1):
            self.iterations = it
            self.d = build(self.market, hourly, blocks, frozenset(self.forced))
            idx = self.d.idx
            res_milp = self.solver.solve_milp(self.d, p.time_limit_s)
            self.welfare = -res_milp.objective
            if self.welfare_first is None:
                self.welfare_first = self.welfare
            res_lp = self._solve_lp_fixed(res_milp.x)
            self.x = res_lp.x
            hint = {zh: float(res_lp.duals_eq[r]) for zh, r in idx.balance_index.items()}
            pd = PriceDeterminer(self.d, self.x, p, self.solver)
            self.raw, self.viol = pd.run(hint)
            if pd.refine_failed:
                self.journal.append(f"itération {it} : affinage quadratique non résolu, prix de la passe L1 conservés")
            self.journal.append(f"itération {it} : objectif {self.welfare:.2f} USD, blocs forcés au rejet {sorted(self.forced)}")
            violated = [bid for bid, v in self.viol.items() if v > 1e-4]
            if not violated:
                return
            if p.force_one_at_a_time:
                # Rejeter d'abord le bloc le plus incohérent seulement : les autres peuvent redevenir cohérents
                # une fois celui-ci écarté (moins de perte de bien-être qu'un rejet groupé).
                violated = [max(violated, key=lambda b: self.viol[b])]
            self.forced |= set(violated)
            self.journal.append(f"itération {it} : blocs acceptés incohérents -> rejet forcé {violated}")
        self.journal.append("nombre maximal d'itérations atteint ; résultat retourné avec blocs éventuellement incohérents")

    def _prorata_hourly(self) -> int:
        """Ordres horaires de même zone, heure, sens et prix, à la monnaie : volume accepté redistribué au prorata
        des quantités (partage du délestage entre preneurs de prix, EPD-2025 §7.9.2 ; règle de départage spec §4.5).
        Neutre pour l'équilibre et le bien-être. Retourne le nombre de groupes modifiés."""
        idx, x, tol = self.d.idx, self.x, self.tol
        groups: dict[tuple, list[int]] = {}
        for i, o in enumerate(idx.hourly):
            groups.setdefault((o.zone, o.mtus, o.side, o.price), []).append(i)
        n = 0
        for ids in groups.values():
            if len(ids) < 2:
                continue
            ratios = [x[idx.col_x(i)] for i in ids]
            if max(ratios) - min(ratios) <= tol:
                continue
            tot_q = sum(idx.hourly[i].quantity for i in ids)
            if tot_q <= 0:
                continue
            acc = sum(idx.hourly[i].quantity * x[idx.col_x(i)] for i in ids)
            for i in ids:
                x[idx.col_x(i)] = acc / tot_q
            n += 1
        return n

    def _tiebreak_blocks(self) -> int:
        """Blocs identiques (EPD-2025 §5.4.4 : même zone, MAR, prix, sens, profil, groupe exclusif, sans liens) :
        les ratios sont réattribués par horodatage croissant puis hachage reproductible des paramètres."""
        idx, x, tol = self.d.idx, self.x, self.tol
        has_child = {b.parent for b in idx.blocks if b.parent is not None}
        groups: dict[tuple, list[int]] = {}
        for j, b in enumerate(idx.blocks):
            if b.parent is None and b.id not in has_child:
                groups.setdefault(_block_key(b), []).append(j)
        n = 0
        for ids in groups.values():
            if len(ids) < 2:
                continue
            ratios = sorted((float(x[idx.col_r(j)]) for j in ids), reverse=True)
            if ratios[0] - ratios[-1] <= tol:
                continue
            def prio(j: int):
                b = idx.blocks[j]
                h = hashlib.sha256(repr((_block_key(b), b.participant, b.id)).encode()).hexdigest()
                return (b.timestamp or "9999", h)
            for j, r in zip(sorted(ids, key=prio), ratios):
                x[idx.col_r(j)] = r
                x[idx.col_u(j)] = 1.0 if r > tol else 0.0
            n += 1
        return n

    def _tiebreak(self) -> None:
        """Départage (neutre pour le bien-être et l'équilibre)."""
        if self.p.prorata_ties:
            n = self._prorata_hourly()
            if n:
                self.journal.append(f"départage : {n} groupe(s) d'ordres horaires à la monnaie redistribués au prorata")
        n = self._tiebreak_blocks()
        if n:
            self.journal.append(f"départage : {n} groupe(s) de blocs identiques réattribués par horodatage puis hachage")

    def _level(self, gap: float) -> str:
        if gap <= self.p.tol_technical:
            return LEVEL_OK
        if gap <= self.p.tol_decoupling:
            return LEVEL_TECH
        return LEVEL_DECOUPLING

    def _coherence(self) -> CoherenceReport:
        """Rapport de cohérence (EPD-2025 §8.2) : écarts numériques et paradoxes, avec leur niveau."""
        d, idx, x, raw, viol, p = self.d, self.d.idx, self.x, self.raw, self.viol, self.p
        checks: list[CoherenceCheck] = []
        bal = d.A_eq @ x - d.b_eq
        checks.append(CoherenceCheck("équilibre zonal (MW)", float(np.max(np.abs(bal))) if bal.size else 0.0, "", ""))
        g = 0.0
        if d.A_ub.shape[0]:
            g = float(np.max(np.maximum(d.A_ub @ x - d.b_ub, 0.0)))
        checks.append(CoherenceCheck("contraintes MAR / liens / groupes exclusifs", g, "", ""))
        g = float(np.max(np.maximum(np.maximum(d.lb - x, x - d.ub), 0.0)))
        checks.append(CoherenceCheck("bornes (ATC, ratios)", g, "", ""))
        g = max((abs(x[idx.col_u(j)] - round(x[idx.col_u(j)])) for j in range(idx.n_u)), default=0.0)
        checks.append(CoherenceCheck("intégralité des blocs", float(g), "", ""))
        g, worst = 0.0, ""
        for i, o in enumerate(idx.hourly):
            pi, xi = sum(raw[(o.zone, h)] for h in o.mtus) / o.n_mtu, x[idx.col_x(i)]
            gap = 0.0
            if xi > p.tolerance:                       # accepté : ne doit pas être hors de la monnaie
                gap = max(gap, o.side * (pi - o.price))
            if xi < 1 - p.tolerance:                   # pas totalement accepté : ne doit pas être dans la monnaie
                gap = max(gap, o.side * (o.price - pi))
            if gap > g:
                g, worst = gap, o.id
        checks.append(CoherenceCheck("ordres horaires paradoxaux (USD/MWh)", float(g), "", worst))
        g, worst = 0.0, ""
        for l in idx.links:
            for h in idx.hours:
                f, a = x[idx.col_f(l.id, h)], float(l.atc.get(h, 0.0))
                if a <= p.tolerance:
                    continue
                pf, pt = raw[(l.from_zone, h)], raw[(l.to_zone, h)]
                gap = 0.0
                if f > p.tolerance:
                    gap = max(gap, pf - (1 - l.loss_factor) * pt)
                if f < a - p.tolerance:
                    gap = max(gap, (1 - l.loss_factor) * pt - pf)
                if gap > g:
                    g, worst = gap, f"{l.id} h{h}"
        checks.append(CoherenceCheck("écart de prix sans congestion (USD/MWh)", float(g), "", worst))
        g = max(viol.values(), default=0.0)
        checks.append(CoherenceCheck("blocs acceptés hors de la monnaie (USD/MWh)", float(g), "",
                                     max(viol, key=viol.get) if viol else ""))
        for c in checks:
            c.level = self._level(c.gap)
        return CoherenceReport(checks)

    def _publish(self, rep: ValidationReport, hourly: list[HourlyOrder], blocks: list[BlockOrder],
                 coherence: CoherenceReport) -> ClearingResult:
        """Écrêtage (MC 15.3.5), arrondi half-up (MC 13.1.3.2, EPD-2025 §8.1) et mise en forme des résultats."""
        p, idx, x, raw, tol = self.p, self.d.idx, self.x, self.raw, self.tol
        prices, clipped = {}, set()
        for zh, v in raw.items():
            c = min(max(v, p.price_min), p.price_max)
            if abs(c - v) > 1e-9:
                clipped.add(zh)
            prices[zh] = round_half_up(c, p.price_decimals)

        def pub(v: float) -> float:
            return round_half_up(v, 0) if p.round_volumes else v

        hourly_ratio = {o.id: float(np.clip(x[idx.col_x(i)], 0.0, 1.0)) for i, o in enumerate(hourly)}
        hourly_mw = {o.id: pub(o.quantity * hourly_ratio[o.id]) for o in hourly}

        block_results: list[BlockResult] = []
        for j, b in enumerate(blocks):
            r = float(x[idx.col_r(j)])
            wp = sum(prices[(b.zone, h)] * q for h, q in b.profile.items()) / b.volume if b.volume > 0 else None
            fam = None
            if r > tol:
                status = BLOCK_ACCEPTED
                fam = 0.0
                for k in accepted_subtree(idx, x, j, tol) if p.linked_family_rule else [j]:
                    bk, rk = blocks[k], float(x[idx.col_r(k)])
                    fam += bk.side * rk * (bk.price * bk.volume - sum(raw[(bk.zone, h)] * q for h, q in bk.profile.items()))
            elif b.id in self.forced:
                status = BLOCK_FORCED
            else:
                in_money = wp is not None and ((b.side == SELL and wp >= b.price - 1e-9) or (b.side == BUY and wp <= b.price + 1e-9))
                status = BLOCK_PARADOX if in_money else BLOCK_REJECTED
            mw = {h: pub(q * r) for h, q in b.profile.items()} if r > tol else {h: 0.0 for h in b.profile}
            rp = sum(mw.values()) / b.volume if b.volume > 0 else 0.0
            block_results.append(BlockResult(b.id, b.participant, b.zone, b.side, b.price, r if r > tol else 0.0,
                                             status, wp, mw, rp, fam))

        link_results: list[LinkHourResult] = []
        for l in self.market.links:
            for h in idx.hours:
                f = float(x[idx.col_f(l.id, h)])
                a = float(l.atc.get(h, 0.0))
                rent = (prices[(l.to_zone, h)] * (1.0 - l.loss_factor) - prices[(l.from_zone, h)]) * f
                link_results.append(LinkHourResult(l.id, l.from_zone, l.to_zone, h, pub(f), a, f >= a - 1e-6 and a > 0, rent))

        return ClearingResult(rep, prices, raw, clipped, hourly_ratio, hourly_mw, block_results, link_results,
                              self.welfare, self.welfare_first, self.iterations, coherence, self.journal)

    # ------------------------------------------------------------ pipeline

    def run(self) -> ClearingResult:
        rep = validate(self.market)
        hourly, blocks = rep.accepted_hourly, rep.accepted_blocks
        self._iterate(hourly, blocks)
        self._tiebreak()
        coherence = self._coherence()
        return self._publish(rep, hourly, blocks, coherence)


def clear(market: Market, solver: Optional[Solver] = None) -> ClearingResult:
    """Exécute le clearing d'une journée de marché (validation, MILP, prix, cohérence, départage, arrondi)."""
    return Clearing(market, solver).run()
