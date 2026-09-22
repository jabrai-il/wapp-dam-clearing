"""Import/export tabulaire (spec §6). Champs repris de MC 13.1.3.1.

orders.csv : order_id,participant,zone,type,side,hour,quantity_mw,price,mar,parent_id,exclusive_group,cross_border
  - type ∈ {hourly, block} ; side ∈ {buy, sell} ; un bloc occupe une ligne par heure de son profil.
  - hour d'un ordre horaire : un entier, ou une plage « 5-8 » pour un ordre multi-MTU (un seul ratio, dans la monnaie
    sur la moyenne des prix des MTU, EPD-2025 §5.1).
atc.csv    : link_id,from_zone,to_zone,hour,atc_mw,loss_factor
participants.csv (optionnel) : participant,trading_limit_mw
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .clearing import ClearingResult
from .orders import BUY, SELL, BlockOrder, HourlyOrder, Link, Market, MarketParams, Participant

_SIDE = {"buy": BUY, "sell": SELL, "achat": BUY, "vente": SELL}


def _f(v: str | None, default: float | None = None) -> float | None:
    if v is None or v.strip() == "":
        return default
    return float(v)



def _parse_hours(s: str) -> tuple[int, ...]:
    """« 7 » -> (7,) ; « 5-8 » -> (5, 6, 7, 8)."""
    s = s.strip()
    if "-" in s:
        a, b = s.split("-", 1)
        return tuple(range(int(a), int(b) + 1))
    return (int(s),)


def _fmt_hours(o: HourlyOrder) -> str:
    hs = o.mtus
    return f"{hs[0]}-{hs[-1]}" if len(hs) > 1 else str(hs[0])

def load_market(orders_csv: str | Path, atc_csv: str | Path, participants_csv: str | Path | None = None,
                params: MarketParams | None = None) -> Market:
    params = params or MarketParams()
    hourly: list[HourlyOrder] = []
    block_rows: dict[str, list[dict]] = {}
    zones: set[str] = set()
    with open(orders_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            zones.add(row["zone"])
            if row["type"].strip().lower() == "hourly":
                hs = _parse_hours(row["hour"])
                hourly.append(HourlyOrder(
                    id=row["order_id"], participant=row["participant"], zone=row["zone"],
                    hour=hs[0], side=_SIDE[row["side"].strip().lower()],
                    quantity=float(row["quantity_mw"]), price=float(row["price"]),
                    cross_border=str(row.get("cross_border", "")).strip() in ("1", "true", "yes", "oui"),
                    hours=hs if len(hs) > 1 else None,
                ))
            else:
                block_rows.setdefault(row["order_id"], []).append(row)
    blocks: list[BlockOrder] = []
    for bid, rows in block_rows.items():
        r0 = rows[0]
        blocks.append(BlockOrder(
            id=bid, participant=r0["participant"], zone=r0["zone"], side=_SIDE[r0["side"].strip().lower()],
            price=float(r0["price"]), mar=_f(r0.get("mar"), 1.0),
            profile={int(r["hour"]): float(r["quantity_mw"]) for r in rows},
            parent=(r0.get("parent_id") or None) or None,
            exclusive_group=(r0.get("exclusive_group") or None) or None,
        ))
    link_rows: dict[str, list[dict]] = {}
    with open(atc_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            link_rows.setdefault(row["link_id"], []).append(row)
            zones.add(row["from_zone"]); zones.add(row["to_zone"])
    links = []
    for lid, rows in link_rows.items():
        r0 = rows[0]
        links.append(Link(id=lid, from_zone=r0["from_zone"], to_zone=r0["to_zone"],
                          atc={int(r["hour"]): float(r["atc_mw"]) for r in rows},
                          loss_factor=_f(r0.get("loss_factor"), 0.0)))
    participants: dict[str, Participant] = {}
    if participants_csv:
        with open(participants_csv, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                participants[row["participant"]] = Participant(row["participant"], _f(row.get("trading_limit_mw")))
    return Market(zones=sorted(zones), hourly=hourly, blocks=blocks, links=links,
                  participants=participants, params=params)


def write_results(res: ClearingResult, out_dir: str | Path, price_max: float = float('inf')) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "prices.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["zone", "hour", "price_usd_mwh", "clipped"])
        for (z, h), p in sorted(res.prices.items()):
            w.writerow([z, h, f"{p:.2f}", int((z, h) in res.clipped)])
    with open(out / "hourly_orders.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["order_id", "participant", "zone", "hour", "side", "quantity_mw", "price", "ratio", "accepted_mw"])
        for o in res.validation.accepted_hourly:
            w.writerow([o.id, o.participant, o.zone, _fmt_hours(o), "buy" if o.side == BUY else "sell", o.quantity, o.price,
                        f"{res.hourly_ratio[o.id]:.6f}", f"{res.hourly_mw[o.id]:.3f}"])
    with open(out / "blocks.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["order_id", "participant", "zone", "side", "price", "ratio", "ratio_published", "status",
                                        "weighted_price", "family_surplus_usd", "mw_by_hour"])
        for b in res.blocks:
            w.writerow([b.id, b.participant, b.zone, "buy" if b.side == BUY else "sell", b.price, f"{b.ratio:.6f}",
                        f"{b.ratio_published:.6f}", b.status,
                        "" if b.weighted_price is None else f"{b.weighted_price:.2f}",
                        "" if b.family_surplus is None else f"{b.family_surplus:.2f}",
                        ";".join(f"{h}:{q:g}" for h, q in sorted(b.mw.items()))])
    with open(out / "flows.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["link_id", "from_zone", "to_zone", "hour", "flow_mw", "atc_mw", "congested", "rent_usd"])
        for l in res.links:
            w.writerow([l.link, l.from_zone, l.to_zone, l.hour, f"{l.flow:.3f}", l.atc, int(l.congested), f"{l.rent:.2f}"])
    with open(out / "positions.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["participant", "hour", "net_mw", "net_usd"])
        for (pid, h), (mw, usd) in sorted(res.positions().items()):
            w.writerow([pid, h, f"{mw:.3f}", f"{usd:.2f}"])
    with open(out / "rejections.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["order_id", "article", "reason"])
        for r in res.validation.rejections:
            w.writerow([r.order_id, r.article, r.reason])
    summary = {
        "welfare_usd": round(res.welfare, 2),
        "welfare_first_iteration_usd": round(res.welfare_first, 2),
        "coherence_level": res.coherence.level,
        "coherence_checks": [{"check": c.name, "gap": round(c.gap, 6), "level": c.level, "detail": c.detail}
                             for c in res.coherence.checks],
        "curtailed_price_takers_mw": {f"{z}:{h}": round(v, 3) for (z, h), v in res.curtailed_price_takers(price_max).items()},
        "congestion_rent_usd": round(res.congestion_rent(), 2),
        "welfare_by_zone_usd": {z: round(v, 2) for z, v in res.welfare_by_zone().items()},
        "iterations": res.iterations,
        "n_hourly_accepted": len(res.validation.accepted_hourly),
        "n_blocks": len(res.blocks),
        "blocks_by_status": {s: sum(1 for b in res.blocks if b.status == s) for s in sorted({b.status for b in res.blocks})},
        "n_rejected_at_validation": res.validation.n_rejected,
        "clipped_prices": sorted([list(k) for k in res.clipped]),
        "journal": res.log,
    }
    with open(out / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
