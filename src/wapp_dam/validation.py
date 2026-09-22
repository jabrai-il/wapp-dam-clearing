"""Validation des ordres à l'import, reproduisant MC 13.1.4 (spec §6).

Chaque rejet porte un motif explicite, comme l'exige le Code (MC 13.1.4).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .orders import BUY, SELL, BlockOrder, HourlyOrder, Market


@dataclass
class Rejection:
    order_id: str
    article: str      # article REMC-WA invoqué
    reason: str


@dataclass
class ValidationReport:
    accepted_hourly: list[HourlyOrder] = field(default_factory=list)
    accepted_blocks: list[BlockOrder] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def n_rejected(self) -> int:
        return len(self.rejections)


def _price_ok(p: float, m: Market) -> bool:
    return m.params.price_min <= p <= m.params.price_max


def validate(market: Market) -> ValidationReport:
    """Valide les ordres et retourne ceux admis au clearing plus la liste motivée des rejets."""
    rep = ValidationReport()
    p = market.params
    zones = set(market.zones)
    hours = set(market.hour_range)
    atc_out: dict[tuple[str, int], float] = defaultdict(float)
    atc_in: dict[tuple[str, int], float] = defaultdict(float)
    for l in market.links:
        for h, a in l.atc.items():
            atc_out[(l.from_zone, h)] += a
            atc_in[(l.to_zone, h)] += a

    # Quantité engagée par participant et par heure (limite de trading, MC 13.1.4.3)
    committed: dict[tuple[str, int], float] = defaultdict(float)

    def limit_ok(participant: str, per_hour: dict[int, float]) -> bool:
        part = market.participants.get(participant)
        if part is None or part.trading_limit is None:
            return True
        return all(committed[(participant, h)] + q <= part.trading_limit + p.tolerance
                   for h, q in per_hour.items())

    def commit(participant: str, per_hour: dict[int, float]) -> None:
        for h, q in per_hour.items():
            committed[(participant, h)] += q

    seen: set[str] = set()

    for o in market.hourly:
        if o.id in seen:
            rep.rejections.append(Rejection(o.id, "MC 13.1.3.1", "identifiant d'ordre dupliqué"))
            continue
        seen.add(o.id)
        if o.side not in (BUY, SELL) or o.quantity < 0 or any(h not in hours for h in o.mtus) or o.zone not in zones:
            rep.rejections.append(Rejection(o.id, "MC 13.1.4.4", "type, sens, heure, zone ou quantité invalide"))
            continue
        if not _price_ok(o.price, market):
            rep.rejections.append(Rejection(
                o.id, "MC 13.1.4.2",
                f"prix {o.price} hors de la plage [{p.price_min}, {p.price_max}] USD/MWh"))
            continue
        if not limit_ok(o.participant, {h: o.quantity for h in o.mtus}):
            rep.rejections.append(Rejection(
                o.id, "MC 13.1.4.3", f"limite de trading du participant {o.participant} dépassée à l'heure {o.hour}"))
            continue
        if o.cross_border:
            cap = min(atc_out[(o.zone, h)] if o.side == SELL else atc_in[(o.zone, h)] for h in o.mtus)
            if o.quantity > cap + p.tolerance:
                rep.rejections.append(Rejection(
                    o.id, "MC 13.1.4.5",
                    f"quantité {'export' if o.side == SELL else 'import'} {o.quantity} MW supérieure à l'ATC "
                    f"{'sortant' if o.side == SELL else 'entrant'} {cap} MW à l'heure {o.hour}"))
                continue
        commit(o.participant, {h: o.quantity for h in o.mtus})
        rep.accepted_hourly.append(o)

    block_ids = {b.id for b in market.blocks}
    for b in market.blocks:
        if b.id in seen:
            rep.rejections.append(Rejection(b.id, "MC 13.1.3.1", "identifiant d'ordre dupliqué"))
            continue
        seen.add(b.id)
        hs = b.hours
        consecutive = len(hs) > 0 and hs == tuple(range(hs[0], hs[0] + len(hs)))
        if (b.side not in (BUY, SELL) or not (0 < b.mar <= 1) or b.zone not in zones
                or not consecutive or not set(hs) <= hours or any(q < 0 for q in b.profile.values())):
            rep.rejections.append(Rejection(b.id, "MC 13.1.4.4", "paramètres de bloc invalides (MAR, heures, zone, quantités)"))
            continue
        if b.parent is not None and b.parent not in block_ids:
            rep.rejections.append(Rejection(b.id, "MC 13.1.4.4", f"bloc parent {b.parent} inconnu"))
            continue
        if not _price_ok(b.price, market):
            rep.rejections.append(Rejection(
                b.id, "MC 13.1.4.2", f"prix {b.price} hors de la plage [{p.price_min}, {p.price_max}] USD/MWh"))
            continue
        if not limit_ok(b.participant, dict(b.profile)):
            rep.rejections.append(Rejection(b.id, "MC 13.1.4.3", f"limite de trading du participant {b.participant} dépassée"))
            continue
        commit(b.participant, dict(b.profile))
        rep.accepted_blocks.append(b)

    # Un enfant dont le parent a été rejeté est rejeté à son tour (cohérence MC 13.1.2.1 c)
    kept = {b.id for b in rep.accepted_blocks}
    changed = True
    while changed:
        changed = False
        for b in list(rep.accepted_blocks):
            if b.parent is not None and b.parent not in kept:
                rep.accepted_blocks.remove(b)
                kept.discard(b.id)
                rep.rejections.append(Rejection(b.id, "MC 13.1.2.1 c", f"bloc parent {b.parent} rejeté à la validation"))
                changed = True
    return rep
