"""Cas de référence multi-zones : rejeu d'une journée du marché day-ahead italien (GME, MGP) avec wapp_dam.

GME publie, sept jours après chaque journée, le carnet d'ordres complet anonymisé du MGP (« offerte pubbliche »),
ainsi que les limites de transit entre zones, les transits réalisés et les prix zonaux, le tout au quart d'heure
(96 périodes). Les fichiers sont servis par le module de téléchargement du site (API interne, paramètres ci-dessous).

Objets du MGP utiles ici :
  - ordres simples (OFFER_TYPE S) par unité, zone, période, sens (BID achat, OFF vente), granularité PT15/PT30/PT60 ;
  - ordres en bloc (OFFER_TYPE B) : profil par période, prix unique, ratio minimal d'acceptation ;
  - statuts : ACC accepté, REJ rejeté, PREJ rejeté paradoxalement (blocs), REP remplacé, REV révoqué, INC invalide.
Seuls ACC, REJ et PREJ décrivent des ordres soumis au clearing ; REP, REV et INC sont écartés.

Zones : 7 zones géographiques italiennes (NORD, CNOR, CSUD, SUD, CALA, SICI, SARD), des zones virtuelles avec ordres
explicites (SVIZ, MONT, MALT, COAC, CORS, FRAN) et des zones de couplage sans ordres (COUP, XFRA, XAUS, XGRE, BSP, AUST,
SLOV, GREC) dont la position nette vient du couplage européen. Pour ces dernières, la position nette est lue dans
les transits publiés et injectée comme ordre preneur de prix : le couplage est pris comme donnée, l'allocation des
capacités entre zones italiennes est laissée au moteur.

Deux niveaux :
  N2 : blocs remplacés par leurs volumes acceptés (preneurs de prix) ; clearing période par période ; comparaison des
       prix zonaux et des transits internes aux valeurs publiées.
  N3 : blocs libres sur la journée entière (MILP 96 périodes) ; comparaison des décisions de blocs (ACC/REJ/PREJ).

Usage : .venv/bin/python examples/gme/replay_gme.py 20260610 [--level 2|3]
Données dans examples/gme/data/ (ignoré par git, ~600 Mo par journée) ; résultats dans examples/gme/results_<date>_*.csv.
"""
from __future__ import annotations

import argparse
import collections
import csv
import http.cookiejar
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from wapp_dam import BUY, SELL, BlockOrder, HourlyOrder, Link, Market, MarketParams, clear

HERE = Path(__file__).parent
DATA = HERE / "data"
SITE = "https://www.mercatoelettrico.org"
P_MIN, P_MAX = -1000.0, 5000.0          # bornes SDAC 2026 (-500/-600 ; 4 000) avec marge : rien n'est rejeté
ITALY = ["NORD", "CNOR", "CSUD", "SUD", "CALA", "SICI", "SARD"]
KEEP_STATUS = {"ACC", "REJ", "PREJ"}
GRAN = {"PT15": 1, "PT30": 2, "PT60": 4}   # nombre de quarts d'heure par période de l'ordre
PRICE_RULE = "midpoint"                    # levée de l'indétermination comme EUPHEMIA (EPD-2025 annexe C)


# ----------------------------------------------------------------------------- téléchargement
def fetch(settore: str, date: str) -> Path:
    """Télécharge l'archive GME (MGP, secteur, journée) via l'API du module de téléchargement du site."""
    DATA.mkdir(exist_ok=True)
    out = DATA / f"MGP_{settore}_{date}.zip"
    if out.exists() and out.stat().st_size > 1000:
        return out
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", "Mozilla/5.0")]
    page_url = f"{SITE}/en-us/Home/Results/Electricity/MGP/Download/Download?valore={settore}"
    page = op.open(page_url).read().decode("utf-8", "ignore")
    tok = re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"', page).group(1)
    mod = re.search(r'"ModuleId":(\d+),"PortalId"', page).group(1)
    tab = re.search(r'"TabId":(\d+)', page).group(1)
    url = (f"{SITE}/DesktopModules/GmeDownload/API/ExcelDownload/downloadzipfile?DataInizio={date}&DataFine={date}"
           f"&Date={date}&Mercato=MGP&Settore={settore}&FiltroDate=InizioFine")
    req = urllib.request.Request(url, headers={"ModuleId": mod, "TabId": tab, "RequestVerificationToken": tok,
                                               "userid": "-1", "Referer": page_url, "Accept": "application/zip, */*"})
    print(f"  téléchargement {settore} {date} ...", end="", flush=True)
    data = op.open(req, timeout=600).read()
    out.write_bytes(data)
    print(f" {len(data) / 1e6:.1f} Mo")
    return out


def xml_path(settore: str, date: str, name: str) -> Path:
    z = fetch(settore, date)
    p = DATA / name
    if not p.exists():
        with zipfile.ZipFile(z) as zf:
            zf.extract(name, DATA)
    return p


def num(s: str) -> float:
    return float(s.replace(",", "."))


# ----------------------------------------------------------------------------- lecture
def load_limits(date: str) -> dict[tuple[str, str], dict[int, float]]:
    """(de, vers) -> {période: limite MW}."""
    root = ET.parse(xml_path("LimitiTransito", date, f"{date}MGPLimitiTransito.xml")).getroot()
    out: dict = collections.defaultdict(dict)
    for e in root.iter("LimitiTransito"):
        d = {c.tag: c.text for c in e}
        out[(d["Da"], d["A"])][int(d["Periodo"])] = num(d["Limite"])
    return out


def load_transits(date: str) -> dict[tuple[str, str, int], float]:
    """(de, vers, période) -> MW ; une valeur négative signifie un flux de « vers » à « de »."""
    root = ET.parse(xml_path("Transiti", date, f"{date}MGPTransiti.xml")).getroot()
    out = {}
    for e in root.iter("MgpTransiti"):
        d = {c.tag: c.text for c in e}
        out[(d["Da"], d["A"], int(d["Periodo"]))] = num(d["TransitoMWh"])
    return out


def load_prices(date: str) -> dict[tuple[str, int], float]:
    """(zone, période) -> EUR/MWh (fichier Prezzi15)."""
    root = ET.parse(xml_path("Prezzi", date, f"{date}MGPPrezzi15.xml")).getroot()
    out = {}
    for e in root.iter("Prezzi15"):
        d = {c.tag: c.text for c in e}
        per = int(d["Periodo"])
        for k, v in d.items():
            if k not in ("Data", "Mercato", "Periodo", "Granularity", "PUN", "NAT") and v:
                out[(k, per)] = num(v)
    return out


def load_orders(date: str):
    """Ordres simples par (période, zone) et blocs. Les périodes sont ramenées au quart d'heure (1..96)."""
    path = xml_path("OffertePubbliche", date, f"{date}MGPOffertePubbliche.xml")
    hourly: dict = collections.defaultdict(list)     # (per, zone) -> [(side, mw, price, awarded, status, id)]
    blocks: dict = {}
    t0 = time.time()
    for ev, el in ET.iterparse(path, events=("end",)):
        if el.tag != "OfferteOperatori":
            continue
        d = {c.tag: (c.text or "") for c in el}
        el.clear()
        if d["STATUS_CD"] not in KEEP_STATUS:
            continue
        side = BUY if d["PURPOSE_CD"] == "BID" else SELL
        # quantité effective = quantité ajustée par le système (ADJ_QUANTITY_NO), qui borne le volume attribué
        mw, aw, price = float(d["ADJ_QUANTITY_NO"] or d["QUANTITY_NO"] or 0), float(d["AWARDED_QUANTITY_NO"] or 0), float(d["ENERGY_PRICE_NO"] or 0)
        k = GRAN[d["GRANULARITY"]]
        periods = range((int(d["PERIOD"]) - 1) * k + 1, int(d["PERIOD"]) * k + 1)
        if d["OFFER_TYPE"] == "B":
            b = blocks.setdefault(d["BLOCK_ID"], dict(zone=d["ZONE_CD"], side=side, price=price, status=d["STATUS_CD"],
                                                    mar=float(d["MINIMUM_ACCEPTANCE_RATIO"] or 1), profile={}, awarded={},
                                                    participant=d["OPERATORE"], ts=d["SUBMITTED_DT"]))
            for per in periods:
                b["profile"][per] = mw
                b["awarded"][per] = aw
        else:
            # un ordre 30 ou 60 min est un ordre multi-MTU : rattaché à son premier quart d'heure, avec la liste des MTU
            hourly[(periods[0], d["ZONE_CD"])].append((side, mw, price, aw, d["STATUS_CD"], d["TRANSACTION_REFERENCE_NO"], tuple(periods)))
    print(f"  ordres lus en {time.time() - t0:.0f} s : {sum(len(v) for v in hourly.values())} marches, {len(blocks)} blocs", flush=True)
    return hourly, blocks


# ----------------------------------------------------------------------------- construction
def net_positions(transits, zones_without_orders, periods):
    """Position nette (export > 0) des zones sans ordres, lue dans les transits publiés."""
    zs, ps = set(zones_without_orders), set(periods)
    net = {(z, p): 0.0 for z in zs for p in ps}
    for (a, b, p), v in transits.items():
        if p not in ps:
            continue
        if a in zs:
            net[(a, p)] += v
        if b in zs:
            net[(b, p)] -= v
    return net


def build(hourly, blocks, limits, transits, zones, periods, level: int) -> Market:
    m = Market(zones=list(zones), params=MarketParams(hours=len(periods), price_min=P_MIN, price_max=P_MAX,
                                                       round_volumes=False, prorata_ties=False, block_fix_max_iter=60,
                                                       price_rule=PRICE_RULE))
    first = periods[0]
    h = (lambda p: p) if level == 3 else (lambda p: p - first + 1)
    pset = set(periods)
    i = 0
    if level == 3:
        # agrégation des marches identiques (zone, MTU, sens, prix) : sans effet sur prix, flux et décisions de blocs
        agg: dict = collections.defaultdict(float)
        for (per, zone), lst in hourly.items():
            if per not in pset:
                continue
            for side, mw, price, aw, status, oid, mtus in lst:
                if mw > 0 and all(q in pset for q in mtus):
                    agg[(zone, tuple(h(q) for q in mtus), side, price)] += mw
        for (zone, hs, side, price), mw in agg.items():
            i += 1
            m.hourly.append(HourlyOrder(f"s{i}", "agg", zone, hs[0], side, mw, price, hours=hs if len(hs) > 1 else None))
    for (per, zone), lst in hourly.items():
        if level == 3 or per not in pset:
            continue
        for side, mw, price, aw, status, oid, mtus in lst:
            if mw > 0 and all(q in pset for q in mtus):
                i += 1
                hs = tuple(h(q) for q in mtus)
                m.hourly.append(HourlyOrder(f"s{i}", status, zone, hs[0], side, mw, price, hours=hs if len(hs) > 1 else None))
    with_orders = {z for (_, z) in hourly} | {b["zone"] for b in blocks.values()}
    for (z, per), v in net_positions(transits, [z for z in zones if z not in with_orders], periods).items():
        if abs(v) > 1e-6:
            i += 1
            m.hourly.append(HourlyOrder(f"x{i}", "couplage", z, h(per), SELL if v > 0 else BUY, abs(v), P_MIN if v > 0 else P_MAX))
    for bid, b in blocks.items():
        prof = {p: q for p, q in b["profile"].items() if p in periods}
        if not prof:
            continue
        if level == 3:
            m.blocks.append(BlockOrder(bid, b["participant"], b["zone"], b["side"], b["price"], max(b["mar"], 0.01), prof, timestamp=b["ts"]))
        else:
            for p, q in b["awarded"].items():
                if p in periods and q > 0:
                    i += 1
                    m.hourly.append(HourlyOrder(f"b{i}", "bloc", b["zone"], h(p), b["side"], q, P_MIN if b["side"] == SELL else P_MAX))
    for (a, b), lim in limits.items():
        atc = {h(p): lim[p] for p in periods if p in lim}
        m.links.append(Link(f"{a}-{b}", a, b, atc))
    return m


# ----------------------------------------------------------------------------- rejeu
def replay_n2(date, hourly, blocks, limits, transits, prices, zones):
    rows, flows = [], []
    for hour in range(24):
        periods = list(range(4 * hour + 1, 4 * hour + 5))
        m = build(hourly, blocks, limits, transits, zones, periods, level=2)
        r = clear(m)
        if r.validation.rejections:
            print(f"  heure {hour + 1} : {len(r.validation.rejections)} rejet(s) à la validation, ex. {r.validation.rejections[0].reason}")
        fl = {(l.link, l.hour): l for l in r.links}
        for k, per in enumerate(periods, start=1):
            for z in ITALY:
                ref = prices.get((z, per))
                eng = r.prices[(z, k)]
                rows.append(dict(period=per, zone=z, price_engine=round(eng, 2), price_official=ref,
                                 diff=round(eng - ref, 2) if ref is not None else None, coherence=r.coherence.level))
            for (a, b), lim in limits.items():
                if a in ITALY and b in ITALY and a < b and (a, b, per) in transits:
                    key = f"{a}-{b}"
                    if (key, k) not in fl or (f"{b}-{a}", k) not in fl:
                        continue
                    f_ab, f_ba = fl[(key, k)].flow, fl[(f"{b}-{a}", k)].flow
                    official = transits[(a, b, per)] - transits.get((b, a, per), 0.0)
                    flows.append(dict(period=per, arc=key, flow_engine=round(f_ab - f_ba, 1), flow_official=round(official, 1),
                                      limit=lim.get(per), limit_reverse=limits.get((b, a), {}).get(per)))
        if (hour + 1) % 6 == 0:
            print(f"  heure {hour + 1}/24")
    return rows, flows


def summarize(rows, flows, label):
    diffs = [abs(r["diff"]) for r in rows if r["diff"] is not None]
    exact = sum(d <= 0.01 for d in diffs)
    print(f"{label} : {len(diffs)} (période, zone) ; prix exact (±0,01) {exact} ; écart absolu moyen {sum(diffs)/len(diffs):.2f} EUR/MWh ; max {max(diffs):.2f}")
    worst = sorted(rows, key=lambda r: -abs(r["diff"] or 0))[:6]
    for r in worst:
        print(f"   période {r['period']:3d} {r['zone']} : moteur {r['price_engine']:8.2f} officiel {r['price_official']:8.2f}")
    if flows:
        fd = [abs(f["flow_engine"] - f["flow_official"]) for f in flows]
        seen = {}
        for f in flows:
            seen.setdefault(f["arc"], []).append(abs(f["flow_engine"] - f["flow_official"]))
        print(f"   transits internes : {len(fd)} (période, arc) ; écart moyen {sum(fd)/len(fd):.1f} MW ; max {max(fd):.1f} MW")
        for arc, v in sorted(seen.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))[:5]:
            print(f"     {arc} : écart moyen {sum(v)/len(v):.1f} MW")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default="20260610")
    ap.add_argument("--level", type=int, default=2)
    a = ap.parse_args()
    date = a.date
    limits, transits, prices = load_limits(date), load_transits(date), load_prices(date)
    hourly, blocks = load_orders(date)
    zones = sorted({z for (_, z) in hourly} | {b["zone"] for b in blocks.values()} | {a for a, _ in limits} | {b for _, b in limits})
    print(f"  zones : {len(zones)} ; arcs : {len(limits)} ; blocs soumis : {len(blocks)}")
    t0 = time.time()
    if a.level == 2:
        rows, flows = replay_n2(date, hourly, blocks, limits, transits, prices, zones)
        summarize(rows, flows, "N2")
        for name, data in (("prices", rows), ("flows", flows)):
            out = HERE / f"results_{date}_{name}.csv"
            with open(out, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(data[0].keys())); w.writeheader(); w.writerows(data)
            print("résultats :", out)
    else:
        periods = list(range(1, 97))
        m = build(hourly, blocks, limits, transits, zones, periods, level=3)
        print(f"  MILP journée : {len(m.hourly)} ordres horaires, {len(m.blocks)} blocs, {len(m.links)} liaisons")
        m.params = MarketParams(hours=96, price_min=P_MIN, price_max=P_MAX, round_volumes=False, prorata_ties=False,
                                block_fix_max_iter=60, price_rule=PRICE_RULE, time_limit_s=300.0)
        print("  clearing journée entière (limite 300 s par MILP)...", flush=True)
        r = clear(m)
        print(f"  itérations {r.iterations}, cohérence {r.coherence.level}, bien-être {r.welfare:,.0f}")
        for line in r.log[-8:]:
            print("   ", line)
        rows = []
        agree = 0
        for br in r.blocks:
            b = blocks[br.id]
            official = b["status"]
            eng = "ACC" if br.ratio > 1e-6 else ("PREJ" if br.status.lower().startswith("para") or "parad" in br.status.lower() else "REJ")
            rows.append(dict(block=br.id, zone=br.zone, side=br.side, price=br.price, mar=b["mar"], volume=sum(b["profile"].values()),
                             status_official=official, status_engine=br.status, ratio_engine=round(br.ratio, 3),
                             ratio_official=round(sum(b["awarded"].values()) / max(sum(b["profile"].values()), 1e-9), 3),
                             weighted_price=br.weighted_price))
            agree += (official == "ACC") == (br.ratio > 1e-6)
        print(f"N3 : {len(rows)} blocs ; décision identique (accepté / non accepté) pour {agree}")
        diffs = [abs(r.prices[(z, p)] - prices[(z, p)]) for z in ITALY for p in periods if (z, p) in prices]
        print(f"   prix : exact {sum(d <= 0.01 for d in diffs)} / {len(diffs)} ; écart moyen {sum(diffs)/len(diffs):.2f} ; max {max(diffs):.2f}")
        out = HERE / f"results_{date}_blocks.csv"
        with open(out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        print("résultats :", out)
    print(f"  durée {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
