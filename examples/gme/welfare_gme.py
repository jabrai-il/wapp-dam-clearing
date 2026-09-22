"""Compare, à ordres identiques, le surplus de l'allocation publiée par GME, celui de l'allocation N2 (blocs fixés
aux volumes publiés, clearing heure par heure) et celui de l'allocation N3 (blocs libres, journée entière).
Usage : .venv/bin/python examples/gme/welfare_gme.py 20260120 20260610 20260915"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import replay_gme as g

for date in sys.argv[1:]:
    limits, transits, prices = g.load_limits(date), g.load_transits(date), g.load_prices(date)
    hourly, blocks = g.load_orders(date)
    zones = sorted({z for (_, z) in hourly} | {b["zone"] for b in blocks.values()} | {a for a, _ in limits} | {b for _, b in limits})
    periods = list(range(1, 97))
    m = g.build(hourly, blocks, limits, transits, zones, periods, level=3)
    m.params = g.MarketParams(hours=96, price_min=g.P_MIN, price_max=g.P_MAX, round_volumes=False, prorata_ties=False,
                              block_fix_max_iter=60, price_rule=g.PRICE_RULE, time_limit_s=300.0)
    r = g.clear(m)
    ids = {br.id for br in r.blocks}
    w_off = sum(side * price * aw * len(mtus) for lst in hourly.values() for side, mw, price, aw, st, oid, mtus in lst if mw > 0)
    w_off += sum(b["side"] * b["price"] * sum(b["awarded"].values()) for bid, b in blocks.items() if bid in ids)
    w_eng = sum(o.side * o.price * r.hourly_mw[o.id] * o.n_mtu for o in r.validation.accepted_hourly if o.participant != "couplage")
    w_eng += sum(br.side * br.price * sum(br.mw.values()) for br in r.blocks)
    diff = sum((b["status"] == "ACC") != (br.ratio > 1e-6) for br in r.blocks for b in [blocks[br.id]])
    # N2 : mêmes blocs que GME (volumes publiés), ordres simples recalculés heure par heure
    w_n2 = sum(b["side"] * b["price"] * sum(b["awarded"].values()) for bid, b in blocks.items() if bid in ids)
    for hour in range(24):
        per = list(range(4 * hour + 1, 4 * hour + 5))
        m2 = g.build(hourly, blocks, limits, transits, zones, per, level=2)
        r2 = g.clear(m2)
        w_n2 += sum(o.side * o.price * r2.hourly_mw[o.id] * o.n_mtu for o in r2.validation.accepted_hourly
                    if o.participant not in ("couplage", "bloc"))
    # surplus par quart d'heure : les MW sont des puissances sur 15 min, le surplus en EUR vaut MW x EUR/MWh / 4
    print(f"{date} : surplus GME {w_off/4:,.0f} EUR ; N2 {w_n2/4:,.0f} EUR (écart {(w_n2-w_off)/4:,.0f}) ; "
          f"N3 {w_eng/4:,.0f} EUR (écart {(w_eng-w_off)/4:,.0f}, {(w_eng-w_off)/w_off*1e6:.2f} par million) ; blocs décidés autrement {diff}")
