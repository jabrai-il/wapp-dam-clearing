"""Reproduit les chiffres de la section « Application illustrative » du working paper (instance wapp4).

Variantes : (A) hivernage, interconnexions en service ; (B) hivernage sans interconnexions (ATC = 0) ;
(C) saison sèche : étiage guinéen et OMVS, crise de combustible au Mali ; (C500) même journée avec un plafond de
prix à 500 USD/MWh ; (D) saison sèche avec la ligne Guinée-Mali (Linsan-Fomi-Bamako, 225 kV, attendue après 2026)
à 200 MW ; (E) saison sèche avec les bids maliens bornés à 180 USD/MWh.
Usage : .venv/bin/python examples/scenarios.py
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

from wapp_dam import BUY, HourlyOrder, Link, MarketParams, clear
from wapp_dam.io import load_market

HERE = Path(__file__).parent / "wapp4"
ZONES = ["SN", "ML", "CI", "GN"]
CAP = 1300.0


def summarize(label, r, m, cap=None):
    cap = cap or CAP
    print(f"\n=== {label} ===")
    print(f"bien-être {r.welfare:,.0f} USD ; rente de congestion {r.congestion_rent():,.0f} USD ; "
          f"itérations {r.iterations} ; cohérence {r.coherence.level}")
    wz = r.welfare_by_zone()
    curt = r.curtailed_price_takers(cap)
    for z in ZONES:
        ps = [r.prices[(z, h)] for h in range(1, 25)]
        c = sum(v for (zz, h), v in curt.items() if zz == z)
        dem = sum(o.quantity for o in m.hourly if o.zone == z and o.side == BUY)
        print(f"  {z}: prix moyen {sum(ps)/24:7.1f}  min {min(ps):6.1f}  max {max(ps):7.1f}  "
              f"h au plafond {sum(p >= cap for p in ps):2d}  surplus {wz.get(z, 0):,.0f} USD  "
              f"demande {dem:,.0f} MWh  délestage {c:,.0f} MWh ({100*c/dem:.1f} %)")
    cong, flows = {}, {}
    for l in r.links:
        flows[l.link] = flows.get(l.link, 0.0) + l.flow
        if l.congested:
            cong[l.link] = cong.get(l.link, 0) + 1
    print("  flux (MWh/j) :", {k: round(v) for k, v in flows.items() if v > 0}, "; heures saturées :", cong)
    for b in r.blocks:
        print(f"  bloc {b.id}: {b.status}, ratio {b.ratio:.3f}, prix pondéré {b.weighted_price:.2f}, "
              f"surplus de famille {'' if b.family_surplus is None else round(b.family_surplus)}")
    return curt


def main():
    params = MarketParams(price_max=CAP)
    m = load_market(HERE / "orders_hivernage.csv", HERE / "atc_hivernage.csv", params=params)
    print(f"instance hivernage : {len(m.zones)} zones, {len(m.hourly)} ordres horaires, {len(m.blocks)} blocs, "
          f"{len(m.links)} liaisons orientées")
    t0 = time.perf_counter()
    r = clear(m)
    print(f"temps de clearing : {time.perf_counter() - t0:.2f} s")
    summarize("A. hivernage, interconnexions en service", r, m)

    m0 = copy.deepcopy(m)
    m0.links = [Link(l.id, l.from_zone, l.to_zone, {h: 0.0 for h in l.atc}, l.loss_factor) for l in m.links]
    summarize("B. hivernage sans interconnexions (ATC = 0)", clear(m0), m0)

    m2 = load_market(HERE / "orders_seche.csv", HERE / "atc_seche.csv", params=params)
    r2 = clear(m2)
    curt = summarize("C. saison sèche : étiage et crise de combustible au Mali", r2, m2)
    h = 21
    print(f"  heure {h} : prix", {z: r2.prices[(z, h)] for z in ZONES},
          "; délestage", {z: round(curt.get((z, h), 0)) for z in ZONES},
          "; flux", [(l.link, round(l.flow), l.congested) for l in r2.links if l.hour == h and l.flow > 0])

    # C500 : sensibilité au plafond de prix (500 au lieu de 1 300) ; les bids au plafond sont ramenés à 500
    m25 = copy.deepcopy(m2)
    m25.params = MarketParams(price_max=500.0)
    m25.hourly = [HourlyOrder(o.id, o.participant, o.zone, o.hour, o.side, o.quantity, min(o.price, 500.0),
                              o.cross_border, o.timestamp) for o in m2.hourly]
    summarize("C500. saison sèche, plafond de prix à 500 USD/MWh", clear(m25), m25, cap=500.0)

    m3 = copy.deepcopy(m2)
    m3.links = m3.links + [Link("GN-ML", "GN", "ML", {h: 200.0 for h in range(1, 25)}, 0.05),
                           Link("ML-GN", "ML", "GN", {h: 200.0 for h in range(1, 25)}, 0.05)]
    summarize("D. saison sèche avec la ligne Guinée-Mali (200 MW)", clear(m3), m3)

    # E : la demande malienne n'est plus preneuse de prix au plafond mais bornée par ce qu'EDM peut recouvrer
    # (prix moyen de vente 106 FCFA/kWh, soit ~180 USD/MWh) : contrainte financière, pas physique.
    m4 = copy.deepcopy(m2)
    m4.hourly = [HourlyOrder(o.id, o.participant, o.zone, o.hour, o.side, o.quantity,
                             180.0 if (o.zone == "ML" and o.side == BUY) else o.price, o.cross_border, o.timestamp)
                 for o in m2.hourly]
    r4 = clear(m4)
    summarize("E. saison sèche, bids maliens bornés à 180 USD/MWh", r4, m4)
    unserved = {o.hour: o.quantity - r4.hourly_mw[o.id] for o in m4.hourly if o.zone == "ML" and o.side == BUY}
    dem = sum(o.quantity for o in m4.hourly if o.zone == "ML" and o.side == BUY)
    tot = sum(unserved.values())
    print(f"  ML : demande non servie {tot:,.0f} MWh sur {dem:,.0f} ({100 * tot / dem:.1f} %), "
          f"heures {sorted(h for h, v in unserved.items() if v > 0.5)}")


if __name__ == "__main__":
    main()
