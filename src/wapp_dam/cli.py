"""Ligne de commande : wapp-dam clear orders.csv atc.csv [--participants p.csv] [--out results]"""
from __future__ import annotations

import argparse
import json
import logging

from .clearing import clear
from .io import load_market, write_results
from .orders import MarketParams


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wapp-dam", description="Moteur de clearing day-ahead REMC-WA")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clear", help="exécute le clearing d'une journée")
    c.add_argument("orders"); c.add_argument("atc")
    c.add_argument("--participants", default=None)
    c.add_argument("--out", default="results")
    c.add_argument("--hours", type=int, default=24)
    c.add_argument("--price-min", type=float, default=0.0)
    c.add_argument("--price-max", type=float, default=500.0)
    c.add_argument("--time-limit", type=float, default=None)
    c.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(message)s")
    params = MarketParams(hours=a.hours, price_min=a.price_min, price_max=a.price_max, time_limit_s=a.time_limit)
    market = load_market(a.orders, a.atc, a.participants, params)
    res = clear(market)
    write_results(res, a.out, params.price_max)
    print(json.dumps({"welfare_usd": round(res.welfare, 2), "congestion_rent_usd": round(res.congestion_rent(), 2),
                      "iterations": res.iterations, "coherence": res.coherence.level,
                      "rejected_at_validation": res.validation.n_rejected,
                      "out": a.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
