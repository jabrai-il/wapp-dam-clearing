"""Cas de référence européen : rejeu d'une journée du marché day-ahead ibérique (OMIE) avec wapp_dam.

OMIE publie chaque jour, sans compte, les courbes agrégées d'offre et de demande du marché diario
(fichier curva_pbc_AAAAMMJJ.1 : un enregistrement par marche, avec statut offert « O » ou casé « C »,
typologie simple « S », complexe « C01 » à « C04 », ou échange « Imp/Exp FR/PT ») et les prix marginaux
(marginalpdbc_AAAAMMJJ.1 : Portugal puis Espagne). Depuis octobre 2025 le pas est le quart d'heure (96 MTU).

Deux niveaux de rejeu, par MTU et par zone (zone « MI » quand les deux pays sont couplés, « ES » et « PT »
sinon ; les échanges ES-PT et avec la France sont déjà des ordres dans les courbes) :
  N1 : croisement de toutes les marches offertes (typologies S et complexes), sans condition complexe ;
  N2 : marches complexes limitées à celles effectivement casées (décisions MIC, indivisibilité, gradient,
       arrêt programmé prises comme données) ; ne reste que le croisement, qui doit reproduire le prix.

Usage : .venv/bin/python examples/omie/replay_omie.py 20260915
Les fichiers OMIE sont téléchargés dans examples/omie/data/ (ignoré par git) ; les résultats dans
examples/omie/results_<date>.csv.
"""
from __future__ import annotations

import csv
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

from wapp_dam import BUY, SELL, HourlyOrder, Market, MarketParams, clear

HERE = Path(__file__).parent
DATA = HERE / "data"
BASE = "https://www.omie.es/es/file-download?parents%5B0%5D={p}&filename={f}"
P_MIN, P_MAX = -1000.0, 5000.0  # bornes harmonisées SDAC (-600 / 4 000 EUR/MWh en 2026) avec marge : rien n'est rejeté


def fetch(name: str) -> Path:
    DATA.mkdir(exist_ok=True)
    out = DATA / name
    if not out.exists() or out.stat().st_size < 1000:
        p = name.rsplit("_", 1)[0]
        urllib.request.urlretrieve(BASE.format(p=p, f=name), out)
    return out


def num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def load_prices(date: str) -> dict[int, tuple[float, float]]:
    """MTU -> (prix PT, prix ES) en EUR/MWh."""
    out = {}
    for line in fetch(f"marginalpdbc_{date}.1").read_text(encoding="latin-1").splitlines():
        f = line.strip().split(";")
        if len(f) >= 6 and f[0].isdigit():
            out[int(f[3])] = (float(f[4]), float(f[5]))
    return out


def load_curves(date: str):
    """Retourne rows[(mtu, zone)] = liste de (side, mw, price, status, typology)."""
    rows = defaultdict(list)
    with open(fetch(f"curva_pbc_{date}.1"), encoding="latin-1") as fh:
        for line in fh:
            f = line.rstrip("\r\n").split(";")
            if len(f) < 9 or not f[0].startswith("H"):
                continue
            h, q = f[0][1:].split("Q")
            mtu = (int(h) - 1) * 4 + int(q)
            zone, side = f[2], (BUY if f[4] == "C" else SELL)
            rows[(mtu, zone)].append((side, num(f[5]), num(f[6]), f[7], f[8]))
    return rows


def build(rows, level: int) -> Market:
    """N1 : toutes les marches offertes ; N2 : marches complexes (C0x) remplacées par leurs volumes casés."""
    m = Market(zones=["MI", "ES", "PT"], params=MarketParams(hours=1, price_min=P_MIN, price_max=P_MAX,
                                                             round_volumes=False, prorata_ties=False))
    i = 0
    for (mtu, zone), lst in rows.items():
        for side, mw, price, status, typ in lst:
            complex_ = typ.startswith("C0")
            if level == 1:
                keep = status == "O" or typ.startswith(("Imp", "Exp"))
            else:
                keep = (status == "O" and not complex_) or (status == "C" and complex_) or typ.startswith(("Imp", "Exp"))
            if not keep or mw <= 0:
                continue
            i += 1
            m.hourly.append(HourlyOrder(f"o{i}", typ, zone, 1, side, mw, price))
    return m


def replay(date: str, level: int, official, rows):
    """Clearing MTU par MTU (aucun lien entre MTU ni entre zones : les échanges sont dans les courbes)."""
    out = []
    by_mtu = defaultdict(list)
    for (mtu, zone), lst in rows.items():
        by_mtu[mtu].append((zone, lst))
    for mtu in sorted(by_mtu):
        sub = {(mtu, z): lst for z, lst in by_mtu[mtu]}
        m = build(sub, level)
        r = clear(m)
        for zone in {z for z, _ in by_mtu[mtu]}:
            price = r.prices[(zone, 1)]
            matched = sum(mw for side, mw, p, st, typ in sub[(mtu, zone)] if st == "C" and side == SELL and not typ.startswith(("Imp", "Exp")))
            ours = sum(r.hourly_mw[o.id] for o in r.validation.accepted_hourly
                       if o.zone == zone and o.side == SELL and not o.participant.startswith(("Imp", "Exp")))
            if r.validation.rejections:
                print(f"  MTU {mtu} : {len(r.validation.rejections)} ordre(s) rejeté(s) à la validation, ex. {r.validation.rejections[0].reason}")
            pt, es = official[mtu]
            ref = es if zone in ("ES", "MI") else pt
            # Intervalle d'indétermination du prix d'après les marches casées (hors échanges) : [vente max, achat min]
            sells = [p for side, mw, p, st, typ in sub[(mtu, zone)] if st == "C" and side == SELL and not typ.startswith(("Imp", "Exp"))]
            buys = [p for side, mw, p, st, typ in sub[(mtu, zone)] if st == "C" and side == BUY and not typ.startswith(("Imp", "Exp"))]
            lo, hi = (max(sells) if sells else None), (min(buys) if buys else None)
            inside = lo is not None and hi is not None and lo - 0.005 <= ref <= hi + 0.005
            out.append(dict(mtu=mtu, zone=zone, level=level, price_engine=round(price, 2), price_official=ref,
                            diff=round(price - ref, 2), interval_low=lo, interval_high=hi, official_in_interval=int(inside),
                            volume_engine=round(ours, 1), volume_official=round(matched, 1),
                            n_orders=len(m.hourly), coherence=r.coherence.level))
    return out


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "20260915"
    official = load_prices(date)
    rows = load_curves(date)
    results = replay(date, 1, official, rows) + replay(date, 2, official, rows)
    out = HERE / f"results_{date}.csv"
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        w.writeheader(); w.writerows(results)
    for level in (1, 2):
        rs = [r for r in results if r["level"] == level]
        diffs = [abs(r["diff"]) for r in rs]
        exact = sum(d <= 0.01 for d in diffs)
        vol = [abs(r["volume_engine"] - r["volume_official"]) for r in rs]
        print(f"N{level} : {len(rs)} (MTU, zone) ; prix exact (±0,01) {exact} ; écart absolu moyen {sum(diffs)/len(diffs):.2f} EUR/MWh ; "
              f"max {max(diffs):.2f} ; écart de volume moyen {sum(vol)/len(vol):.1f} MW, max {max(vol):.1f} MW")
        gaps = [r for r in rs if abs(r["diff"]) > 0.01]
        if level == 2:
            print(f"     écarts {len(gaps)}, dont {sum(r['official_in_interval'] for r in gaps)} avec le prix officiel à l'intérieur "
                  f"de l'intervalle d'indétermination des marches casées")
        worst = sorted(rs, key=lambda r: -abs(r["diff"]))[:5]
        for r in worst:
            print(f"   MTU {r['mtu']:3d} {r['zone']} : moteur {r['price_engine']:8.2f} officiel {r['price_official']:8.2f} "
                  f"(vol {r['volume_engine']:.0f} vs {r['volume_official']:.0f})")
    print("résultats :", out)


if __name__ == "__main__":
    main()
