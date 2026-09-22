"""Génère l'instance stylisée à quatre zones (SN, ML, CI, GN), 24 heures, en MW et USD/MWh.

Ordres de grandeur tirés de sources publiques (voir README.md du dossier) : rapports annuels Senelec 2024,
EDM-SA 2023, EDG 2024, CI-Energies 2024, OMVS, OMVG, WAPP. Les paliers d'offre sont des stylisations
(pas de données réelles de participant). Deux saisons : « hivernage » (septembre, hydraulique pleine) et
« seche » (mars, étiage guinéen et OMVS, crise de combustible au Mali).
Usage : python examples/wapp4/generate.py [hivernage|seche] -> orders_<saison>.csv, atc_<saison>.csv
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

HERE = Path(__file__).parent
CAP = 1300.0     # 50 % d'un coût de l'énergie non servie de 2 600 USD/MWh (référence Ghana, plan directeur WAPP)
FLOOR = 0.0
HOURS = range(1, 25)


def load_profile(peak: float, base_ratio: float, evening: float):
    """Profil journalier : creux nocturne, plateau diurne, pointe 19 h-22 h (climatisation, éclairage)."""
    out = {}
    for h in HOURS:
        day = 0.5 * (1 - math.cos((h - 5) / 24 * 2 * math.pi)) if 5 <= h <= 23 else 0.0
        peak_evening = evening if 19 <= h <= 22 else (evening * 0.5 if h in (18, 23) else 0.0)
        out[h] = round(peak * (base_ratio + (1 - base_ratio - evening) * day + peak_evening))
    return out


def solar(mwc: float, cap_factor_peak: float = 0.75):
    return {h: round(mwc * cap_factor_peak * max(0.0, math.sin((h - 7) / 12 * math.pi))) if 8 <= h <= 18 else 0 for h in HOURS}


def build(season: str):
    wet = season == "hivernage"
    rows = []          # (order_id, participant, zone, type, side, hour, q, price, mar, parent, group)
    blocks = []

    def hourly(prefix, participant, zone, side, q_by_h, price):
        for h in HOURS:
            q = q_by_h[h] if isinstance(q_by_h, dict) else q_by_h
            if q > 0:
                rows.append((f"{prefix}_{h:02d}", participant, zone, "hourly", side, h, int(q), price, "", "", ""))

    # ---------------- Demande (preneuse de prix au plafond) ----------------
    # SN : pointe 1 159 MW (13 août 2024, Senelec) ; ML : pointe RI 475 MW (2023, EDM) ; CI : ~1 800 MW (2024, estimé,
    # 1 545 en 2020) ; GN : 829 MW (nov. 2024, EDG). En saison sèche : SN, ML et CI plus chauds (+5 %).
    # Saisonnalité : la pointe sénégalaise est en août-octobre (hivernage), celles du Mali, de la Côte d'Ivoire et de la
    # Guinée en saison sèche et chaude (février-mai) : SN -8 % en saison sèche, les trois autres +5 %.
    dem = {"SN": load_profile(1160 * (0.92 if not wet else 1.0), 0.55, 0.12),
           "ML": load_profile(475 * (1.05 if not wet else 1.0), 0.55, 0.15),
           "CI": load_profile(1800 * (1.05 if not wet else 1.0), 0.60, 0.10),
           "GN": load_profile(830 * (1.05 if not wet else 1.0), 0.50, 0.15)}
    utility = {"SN": "SENELEC", "ML": "EDM", "CI": "CIE", "GN": "EDG"}
    for z, d in dem.items():
        hourly(f"{z}_D", utility[z], z, "buy", d, CAP)

    # Utilitaires blocs : (id, participant, zone, side, prix, MAR, profil, parent, groupe)
    def blk(bid, part, zone, side, price, mar, hours, mw, parent="", group=""):
        blocks.append((bid, part, zone, side, float(price), mar, {h: mw for h in hours}, parent, group))

    PK6, PK4, DAY, ALL = range(18, 24), range(19, 23), range(7, 18), range(1, 25)
    fuel = 1.0 if wet else 0.5          # saison sèche : combustible malien rationné de moitié
    hyd = 1.0 if wet else 0.45          # étiage : réservoirs à 45 %

    # ---------------- Offre SN (Senelec 2024 : 1 904 MW installés) ----------------
    # Hydro OMVS part sénégalaise : Manantali 33 % de 200, Félou 25 % de 60, Gouina ~33 % de 140 => ~127 MW (hivernage).
    hourly("SN_HYD", "SENELEC", "SN", "sell", 127 if wet else 76, 33)
    hourly("SN_SOL", "SN_IPP_SOL", "SN", "sell", solar(266), 1)               # 266 MW solaire, offert à 1 USD
    hourly("SN_WIND", "SN_IPP_WIND", "SN", "sell", 55, 1)                     # Taïba Ndiaye 159 MW, ~35 % de facteur
    hourly("SN_HFO_BA", "SENELEC", "SN", "sell", 200, 125)                    # Bel-Air, Kahone : diesel lent HFO déjà en marche
    hourly("SN_HFO_IPP", "SN_IPP_HFO", "SN", "sell", 100, 147)
    hourly("SN_TAG", "SENELEC", "SN", "sell", 50, 400)                        # TAG gasoil de secours (240 FCFA/kWh)
    hourly("SN_LOC", "SN_IPP_LOC", "SN", "sell", 200, 135)                    # location de groupes HFO (360 MW loués en 2024)
    hourly("SN_KAH", "SENELEC", "SN", "sell", 100, 150)                       # Kahone 1 (133 FCFA/kWh)
    # Sendou charbon 115 MW : bloc de base 24 h, minimum technique 60 %
    blk("SN_SENDOU", "SN_IPP_COAL", "SN", "sell", 61, 0.6, ALL, 115)
    # Centrales HFO à coût de démarrage : parent de pointe (démarrage amorti) + enfant de journée au coût variable
    blk("SN_KOUN_PK", "SN_IPP_HFO", "SN", "sell", 160, 1.0, PK6, 67)
    blk("SN_KOUN_DAY", "SN_IPP_HFO", "SN", "sell", 125, 1.0, DAY, 67, parent="SN_KOUN_PK")
    blk("SN_TOB_PK", "SN_IPP_HFO", "SN", "sell", 150, 1.0, PK6, 96)
    blk("SN_TOB_DAY", "SN_IPP_HFO", "SN", "sell", 122, 1.0, DAY, 96, parent="SN_TOB_PK")
    blk("SN_CDB_PK", "SN_IPP_HFO", "SN", "sell", 165, 1.0, PK6, 86)
    blk("SN_CDB_DAY", "SN_IPP_HFO", "SN", "sell", 128, 1.0, DAY, 86, parent="SN_CDB_PK")
    # Malicounda 120 MW : trois durées alternatives (groupe exclusif)
    blk("SN_MAL_6H", "SN_IPP_HFO", "SN", "sell", 145, 1.0, PK6, 120, group="SN_MAL")
    blk("SN_MAL_12H", "SN_IPP_HFO", "SN", "sell", 135, 1.0, range(12, 24), 120, group="SN_MAL")
    blk("SN_MAL_24H", "SN_IPP_HFO", "SN", "sell", 128, 0.7, ALL, 120, group="SN_MAL")
    # Turbines à gaz au gasoil : deux durées de pointe alternatives
    blk("SN_TAG_2H", "SENELEC", "SN", "sell", 380, 1.0, range(20, 22), 100, group="SN_TAGPK")
    blk("SN_TAG_4H", "SENELEC", "SN", "sell", 360, 1.0, PK4, 100, group="SN_TAGPK")
    # Demande industrielle élastique : cimenterie (autoproduction possible au-delà de 200 USD/MWh)
    blk("SN_CIMENT", "SN_IND_CIMENT", "SN", "buy", 200, 1.0, ALL, 40)

    # ---------------- Offre ML (EDM 2023 : 756 MW RI, thermique 495) ----------------
    # Hydro fil de l'eau et part OMVS (52 % Manantali, 45 % Félou, ~40 % Gouina) : ~187 MW + Sotuba
    hourly("ML_HYD", "EDM", "ML", "sell", 191 if wet else 100, 33)
    hourly("ML_SOL", "ML_IPP_SOL", "ML", "sell", solar(50), 1)               # Akuo Kita 50 MWc
    hourly("ML_HFO_DAR", "EDM", "ML", "sell", int(60 * fuel), 220)            # Darsalam, groupes déjà en marche
    hourly("ML_DSL", "EDM", "ML", "sell", int(40 * fuel), 320)
    # Sélingué 46 MW (réservoir) : profil de pointe ou demi-journée
    blk("ML_SEL_PK", "EDM", "ML", "sell", 40, 1.0, PK6, int(46 * hyd) or 1, group="ML_SEL")
    blk("ML_SEL_12H", "EDM", "ML", "sell", 38, 1.0, range(12, 24), int(30 * hyd) or 1, group="ML_SEL")
    # Balingué et Sirakoro (HFO, ~90 et ~60 MW) : familles pointe + journée ; coût moyen EDM 266 USD/MWh
    blk("ML_BAL_PK", "EDM", "ML", "sell", 240, 1.0, PK6, int(90 * fuel))
    blk("ML_BAL_DAY", "EDM", "ML", "sell", 215, 1.0, DAY, int(90 * fuel), parent="ML_BAL_PK")
    blk("ML_SIR_PK", "EDM", "ML", "sell", 250, 1.0, PK6, int(60 * fuel))
    blk("ML_SIR_DAY", "EDM", "ML", "sell", 225, 1.0, DAY, int(60 * fuel), parent="ML_SIR_PK")
    # Location diesel (Aggreko) 50 MW : bloc 24 h, MAR 0,5
    blk("ML_AGG_24H", "ML_IPP_LOC", "ML", "sell", 300, 0.5, ALL, int(50 * fuel))
    # Mines d'or : achat 24 h à 250 (au-delà, autoproduction diesel)
    blk("ML_MINES", "ML_IND_MINES", "ML", "buy", 250, 1.0, ALL, 60)

    # ---------------- Offre CI (CI-Energies : 3 119 MW, 66 % gaz, 33 % hydro) ----------------
    hourly("CI_HYD_ROR", "CIE", "CI", "sell", 350 if wet else 180, 33)         # Taabo, Buyo, Ayamé : fil de l'eau et base
    # Tranche flexible réduite de 500 à 300 MW : l'approvisionnement en gaz limite l'énergie exportable (exports CI
    # en baisse de 30 % en 2024 ; Ghana, Burkina et Liberia non modélisés se disputent le même gaz).
    hourly("CI_GAS_FLEX", "CI_IPP_GAS", "CI", "sell", 300, 60)                 # cycles combinés en marche (Azito, Ciprel)
    hourly("CI_GAS2", "CI_IPP_GAS", "CI", "sell", 400, 85)
    hourly("CI_GAS3", "CIE", "CI", "sell", 300, 130)                          # turbines à gaz de pointe
    hourly("CI_HFO", "CIE", "CI", "sell", 200, 200)
    # Cycles combinés : base 24 h à minimum technique + tranche de pointe liée
    blk("CI_AZI_BASE", "CI_IPP_GAS", "CI", "sell", 52, 0.6, ALL, 300)
    blk("CI_AZI_PK", "CI_IPP_GAS", "CI", "sell", 70, 1.0, PK6, 100, parent="CI_AZI_BASE")
    blk("CI_CIP_BASE", "CI_IPP_GAS", "CI", "sell", 55, 0.6, ALL, 250)
    blk("CI_CIP_PK", "CI_IPP_GAS", "CI", "sell", 72, 1.0, PK6, 100, parent="CI_CIP_BASE")
    blk("CI_ATK_BASE", "CI_IPP_GAS", "CI", "sell", 58, 0.5, ALL, 200)         # Atinkou 390 MW (2023)
    # Réservoirs Soubré 275 et Kossou 174 : profils alternatifs
    blk("CI_SOU_PK", "CIE", "CI", "sell", 35, 1.0, PK6, int(275 * hyd), group="CI_SOU")
    blk("CI_SOU_12H", "CIE", "CI", "sell", 34, 1.0, range(10, 24), int(200 * hyd), group="CI_SOU")
    blk("CI_SOU_FLAT", "CIE", "CI", "sell", 33, 0.8, ALL, int(120 * hyd), group="CI_SOU")
    blk("CI_KOS_PK", "CIE", "CI", "sell", 36, 1.0, PK6, int(150 * hyd), group="CI_KOS")
    blk("CI_KOS_12H", "CIE", "CI", "sell", 35, 1.0, range(12, 24), int(100 * hyd), group="CI_KOS")
    # Turbines à gaz cycle ouvert de pointe : deux durées
    blk("CI_OCGT_4H", "CIE", "CI", "sell", 140, 1.0, PK4, 150, group="CI_OCGT")
    blk("CI_OCGT_6H", "CIE", "CI", "sell", 132, 1.0, PK6, 150, group="CI_OCGT")
    # Demande industrielle élastique (zone industrielle d'Abidjan)
    blk("CI_INDUS", "CI_IND", "CI", "buy", 150, 1.0, ALL, 100)

    # ---------------- Offre GN (EDG 2024 : 1 214 MW, Souapiti 450, Kaléta 240) ----------------
    hourly("GN_HYD_ROR", "EDG", "GN", "sell", 300 if wet else 120, 33)         # Kaléta, Garafiri : fil de l'eau
    hourly("GN_HFO_TEP", "EDG", "GN", "sell", 100, 150)                       # Té-Power en marche
    # Souapiti 450 MW (réservoir) : trois profils alternatifs
    blk("GN_SOUA_FLAT", "EDG", "GN", "sell", 33, 0.6, ALL, int(300 * hyd), group="GN_SOUA")
    blk("GN_SOUA_PK", "EDG", "GN", "sell", 36, 1.0, range(17, 24), int(450 * hyd), group="GN_SOUA")
    blk("GN_SOUA_12H", "EDG", "GN", "sell", 34, 1.0, range(11, 24), int(380 * hyd), group="GN_SOUA")
    # Kaléta : tranche de pointe supplémentaire
    blk("GN_KAL_PK", "EDG", "GN", "sell", 38, 1.0, PK6, int(80 * hyd))
    # KPS barge 110 MW : bloc 24 h, MAR 0,5 ; Té-Power famille pointe + journée
    blk("GN_KPS_24H", "GN_IPP_KPS", "GN", "sell", 140, 0.5, ALL, 110)
    blk("GN_TEP_PK", "EDG", "GN", "sell", 170, 1.0, PK6, 100)
    blk("GN_TEP_DAY", "EDG", "GN", "sell", 150, 1.0, DAY, 100, parent="GN_TEP_PK")
    # Bauxite et alumine (CBG, Friguia) : achat 24 h à 160
    blk("GN_BAUX", "GN_IND_BAUX", "GN", "buy", 160, 1.0, ALL, 80)

    for b in blocks:
        bid, part, zone, side, price, mar, prof, parent, group = b
        for h, q in prof.items():
            rows.append((bid, part, zone, "block", side, h, int(q), price, mar, parent, group))

    with open(HERE / f"orders_{season}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["order_id", "participant", "zone", "type", "side", "hour", "quantity_mw", "price", "mar", "parent_id", "exclusive_group", "cross_border"])
        for r in rows:
            w.writerow(list(r) + [""])

    # ---------------- Interconnexions (ATC stylisées, MW) ----------------
    # OMVS Kayes-Tambacounda 225 kV (ML<->SN) ; CI-ML Ferké-Sikasso-Ségou 225 kV, 400 MW (2012) ;
    # OMVG boucle 225 kV (GN<->SN), capacité d'échange Guinée 340 MVA ; GN-ML Linsan-Fomi-Bamako : non en service (2026).
    # CI-ML : ligne de 400 MW ; ATC vue par le day-ahead réduite à 200 MW au titre des contrats bilatéraux avec droits
    # physiques de transport (Phase 1 du Code), alloués avant le clearing.
    links = [("ML-SN", "ML", "SN", 150, 0.04), ("SN-ML", "SN", "ML", 150, 0.04),
             ("CI-ML", "CI", "ML", 200, 0.04), ("ML-CI", "ML", "CI", 150, 0.04),
             ("GN-SN", "GN", "SN", 250, 0.03), ("SN-GN", "SN", "GN", 250, 0.03)]
    with open(HERE / f"atc_{season}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["link_id", "from_zone", "to_zone", "hour", "atc_mw", "loss_factor"])
        for lid, a, b, atc, loss in links:
            for h in HOURS:
                w.writerow([lid, a, b, h, atc, loss])
    print(season, ":", len(rows), "lignes d'ordres,", len(blocks), "blocs")


if __name__ == "__main__":
    for s in (sys.argv[1:] or ["hivernage", "seche"]):
        build(s)
