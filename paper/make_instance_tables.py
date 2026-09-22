"""Génère paper/instance_tables.tex (annexe) à partir de examples/wapp4/orders_hivernage.csv.

Deux tableaux : les ordres horaires de vente (un par palier) et les blocs (un par bloc), avec unité, type,
heures, MW, prix, MAR, lien ou groupe. Lancer après toute modification de examples/wapp4/generate.py :
    .venv/bin/python paper/make_instance_tables.py
"""
from __future__ import annotations

import csv
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "examples" / "wapp4" / "orders_hivernage.csv"
OUT = ROOT / "paper" / "instance_tables.tex"

ZONE_NAME = {"SN": "Sénégal", "ML": "Mali", "CI": "Côte d'Ivoire", "GN": "Guinée"}
GROUP_NAME = {"SN_MAL": "Malicounda", "SN_TAGPK": "TAG Sénégal", "ML_SEL": "Sélingué", "CI_SOU": "Soubré",
              "CI_KOS": "Kossou", "CI_OCGT": "TAG Côte d'Ivoire", "GN_SOUA": "Souapiti"}

HOURLY_DESC = {
    "SN_D": "demande Senelec (preneuse de prix)", "ML_D": "demande EDM-SA (preneuse de prix)",
    "CI_D": "demande CIE (preneuse de prix)", "GN_D": "demande EDG (preneuse de prix)",
    "SN_HYD": "hydraulique OMVS, part sénégalaise (Manantali, Félou, Gouina)",
    "SN_SOL": "solaire (266 MWc, profil diurne)", "SN_WIND": "éolien Taïba Ndiaye (moyenne)",
    "SN_HFO_BA": "diesel lent HFO déjà en marche (Bel-Air, Kahone)", "SN_HFO_IPP": "HFO producteur indépendant",
    "SN_TAG": "turbine à gaz au gasoil, secours",
    "SN_LOC": "location de groupes HFO (360 MW loués en 2024)", "SN_KAH": "Kahone 1, HFO",
    "ML_HYD": "hydraulique : part OMVS et Sotuba (fil de l'eau)", "ML_SOL": "solaire Kita (50 MWc, profil diurne)",
    "ML_HFO_DAR": "HFO Darsalam, groupes en marche", "ML_DSL": "diesel",
    "CI_HYD_ROR": "hydraulique fil de l'eau et base (Taabo, Buyo, Ayamé)",
    "CI_GAS_FLEX": "cycles combinés en marche, tranche flexible", "CI_GAS2": "gaz, tranche supérieure",
    "CI_GAS3": "turbines à gaz de pointe", "CI_HFO": "HFO",
    "GN_HYD_ROR": "hydraulique fil de l'eau (Kaléta, Garafiri)", "GN_HFO_TEP": "HFO Té-Power en marche",
}

BLOCK_DESC = {
    "SN_SENDOU": "Sendou, charbon, bloc de base", "SN_KOUN_PK": "Kounoune, HFO, tranche de pointe (parent)",
    "SN_KOUN_DAY": "Kounoune, tranche de journée (enfant)", "SN_TOB_PK": "Tobène, HFO, pointe (parent)",
    "SN_TOB_DAY": "Tobène, journée (enfant)", "SN_CDB_PK": "Cap des Biches, HFO, pointe (parent)",
    "SN_CDB_DAY": "Cap des Biches, journée (enfant)", "SN_MAL_6H": "Malicounda, HFO, 6 h de pointe",
    "SN_MAL_12H": "Malicounda, 12 h", "SN_MAL_24H": "Malicounda, 24 h", "SN_TAG_2H": "TAG gasoil, 2 h de pointe",
    "SN_TAG_4H": "TAG gasoil, 4 h de pointe", "SN_CIMENT": "cimenterie, achat 24 h",
    "ML_SEL_PK": "Sélingué, réservoir, pointe", "ML_SEL_12H": "Sélingué, 12 h",
    "ML_BAL_PK": "Balingué, HFO, pointe (parent)", "ML_BAL_DAY": "Balingué, journée (enfant)",
    "ML_SIR_PK": "Sirakoro, HFO, pointe (parent)", "ML_SIR_DAY": "Sirakoro, journée (enfant)",
    "ML_AGG_24H": "location diesel, bloc de base", "ML_MINES": "mines d'or, achat 24 h",
    "CI_AZI_BASE": "Azito, CCGT, bloc de base (parent)", "CI_AZI_PK": "Azito, tranche de pointe (enfant)",
    "CI_CIP_BASE": "Ciprel, CCGT, bloc de base (parent)", "CI_CIP_PK": "Ciprel, tranche de pointe (enfant)",
    "CI_ATK_BASE": "Atinkou, CCGT, bloc de base", "CI_SOU_PK": "Soubré, réservoir, pointe",
    "CI_SOU_12H": "Soubré, 14 h", "CI_SOU_FLAT": "Soubré, plat 24 h", "CI_KOS_PK": "Kossou, réservoir, pointe",
    "CI_KOS_12H": "Kossou, 12 h", "CI_OCGT_4H": "TAG cycle ouvert, 4 h", "CI_OCGT_6H": "TAG cycle ouvert, 6 h",
    "CI_INDUS": "zone industrielle, achat 24 h",
    "GN_SOUA_FLAT": "Souapiti, réservoir, plat 24 h", "GN_SOUA_PK": "Souapiti, pointe étendue",
    "GN_SOUA_12H": "Souapiti, 13 h", "GN_KAL_PK": "Kaléta, tranche de pointe", "GN_KPS_24H": "KPS, barge HFO, bloc de base",
    "GN_TEP_PK": "Té-Power, HFO, pointe (parent)", "GN_TEP_DAY": "Té-Power, journée (enfant)",
    "GN_BAUX": "bauxite et alumine, achat 24 h",
}


def tex(s: str) -> str:
    return s.replace("_", "\\_").replace("%", "\\%").replace("&", "\\&")


def hours_str(hs: list[int]) -> str:
    hs = sorted(hs)
    if hs == list(range(hs[0], hs[0] + len(hs))):
        return f"{hs[0]}--{hs[-1]}~h" if len(hs) > 1 else f"{hs[0]}~h"
    return ", ".join(str(h) for h in hs)


def fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", "\\,") if float(x).is_integer() else f"{x:.2f}"


def main():
    hourly: "OrderedDict[str, dict]" = OrderedDict()
    blocks: "OrderedDict[str, dict]" = OrderedDict()
    with open(CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["type"] == "hourly":
                prefix = r["order_id"].rsplit("_", 1)[0]
                d = hourly.setdefault(prefix, {"zone": r["zone"], "side": r["side"], "price": float(r["price"]),
                                               "q": {}, "participant": r["participant"]})
                d["q"][int(r["hour"])] = float(r["quantity_mw"])
            else:
                d = blocks.setdefault(r["order_id"], {"zone": r["zone"], "side": r["side"], "price": float(r["price"]),
                                                      "mar": float(r["mar"] or 1), "q": {}, "parent": r["parent_id"],
                                                      "group": r["exclusive_group"], "participant": r["participant"]})
                d["q"][int(r["hour"])] = float(r["quantity_mw"])

    out = []
    out.append("% Fichier généré par paper/make_instance_tables.py : ne pas éditer à la main.\n")
    # ---- ordres horaires
    out.append(r"\begin{longtable}{p{1.2cm}p{7.9cm}p{2.3cm}p{2.1cm}p{1.5cm}}")
    out.append(r"\caption{Ordres horaires de l'instance (hivernage). Quantités en MW par heure ; les demandes et le solaire suivent un profil, dont on donne le minimum et le maximum.}\label{tab:annexe-horaires}\\")
    out.append(r"\toprule Zone & Ordre & MW\newline (min--max) & Prix\newline (USD/MWh) & Sens \\ \midrule \endfirsthead")
    out.append(r"\toprule Zone & Ordre & MW\newline (min--max) & Prix\newline (USD/MWh) & Sens \\ \midrule \endhead")
    out.append(r"\bottomrule \endfoot")
    for z in ("SN", "ML", "CI", "GN"):
        first = True
        for pid, d in hourly.items():
            if d["zone"] != z:
                continue
            qs = [q for q in d["q"].values() if q > 0]
            mw = fmt(min(qs)) if min(qs) == max(qs) else f"{fmt(min(qs))}--{fmt(max(qs))}"
            side = "achat" if d["side"] == "buy" else "vente"
            price = "plafond (1\\,300)" if d["price"] >= 1300 else fmt(d["price"])
            out.append(f"{tex(z) if first else ''} & {HOURLY_DESC.get(pid, tex(pid))} & {mw} & {price} & {side} \\\\ \\rowsep")
            first = False
    out[-1] = out[-1].replace(" \\rowsep", "")
    out.append(r"\end{longtable}")
    out.append("")
    # ---- blocs
    out.append(r"\begin{longtable}{p{1.0cm}p{5.4cm}p{1.6cm}p{1.5cm}p{1.7cm}p{0.9cm}p{2.7cm}}")
    out.append(r"\caption{Blocs de l'instance (hivernage). MAR = ratio minimal d'acceptation ; « enfant de » désigne le bloc parent (bloc lié) ; « groupe » désigne un groupe exclusif dont un seul bloc au plus est accepté.}\label{tab:annexe-blocs}\\")
    out.append(r"\toprule Zone & Bloc & Heures & MW\newline par heure & Prix\newline (USD/MWh) & MAR & Lien \\ \midrule \endfirsthead")
    out.append(r"\toprule Zone & Bloc & Heures & MW\newline par heure & Prix\newline (USD/MWh) & MAR & Lien \\ \midrule \endhead")
    out.append(r"\bottomrule \endfoot")
    for z in ("SN", "ML", "CI", "GN"):
        first = True
        for bid, d in blocks.items():
            if d["zone"] != z:
                continue
            side = "achat : " if d["side"] == "buy" else ""
            link = ""
            if d["parent"]:
                link = "enfant de " + BLOCK_DESC.get(d["parent"], d["parent"]).split(",")[0]
            elif d["group"]:
                link = "groupe " + GROUP_NAME.get(d["group"], tex(d["group"]))
            mw = fmt(list(d["q"].values())[0])
            out.append(f"{tex(z) if first else ''} & {side}{BLOCK_DESC.get(bid, tex(bid))} & {hours_str(list(d['q']))} & {mw} & {fmt(d['price'])} & {d['mar']:.1f}" + f" & {link} \\\\ \\rowsep")
            first = False
    out[-1] = out[-1].replace(" \\rowsep", "")
    out.append(r"\end{longtable}")
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{OUT.name} : {len(hourly)} ordres horaires, {len(blocks)} blocs")


if __name__ == "__main__":
    main()
