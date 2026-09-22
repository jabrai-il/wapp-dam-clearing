# Cas de référence multi-zones : rejeu du marché day-ahead italien (GME, MGP)

GME, l'opérateur du marché italien (membre du couplage européen SDAC), publie sept jours après chaque journée le
**carnet d'ordres complet anonymisé** du marché du jour pour le lendemain (MGP), en plus des limites de transit, des
transits réalisés et des prix zonaux. C'est, à notre connaissance, la seule publication européenne au niveau de
l'ordre ; elle permet de rejouer non seulement le croisement des courbes (comme avec OMIE) mais l'allocation implicite
des capacités entre zones et les décisions sur les ordres en bloc.

## Données

Quatre archives par journée, servies par le module de téléchargement du site (`replay_gme.py` reconstitue l'appel
de l'API interne ; aucun compte n'est nécessaire) :

| Archive | Contenu | Champs utilisés |
|---|---|---|
| `OffertePubbliche` | toutes les offres, une ligne par (ordre, période) ; ~590 Mo de XML par journée | sens (BID/OFF), zone, période, granularité (PT15/PT30/PT60), prix, quantité ajustée, quantité attribuée, statut, type (S simple / B bloc), identifiant de bloc, ratio minimal d'acceptation |
| `LimitiTransito` | limite de transit par arc orienté et période (96) | 42 arcs entre 21 zones |
| `Transiti` | transit réalisé par arc et période | position nette des zones de couplage |
| `Prezzi` | prix zonaux par période (fichier `Prezzi15`) | référence |

Statuts : ACC accepté, REJ rejeté, PREJ rejeté paradoxalement (blocs), REP remplacé, REV révoqué, INC invalide.
Seuls ACC, REJ et PREJ décrivent des ordres soumis au clearing.

Zones : sept zones italiennes (NORD, CNOR, CSUD, SUD, CALA, SICI, SARD), des zones virtuelles avec ordres explicites
(SVIZ, MONT, MALT, COAC, CORS, FRAN) et des zones de couplage sans ordres (COUP, XFRA, XAUS, XGRE, BSP, AUST, SLOV,
GREC). Pour ces dernières, la position nette lue dans les transits est injectée comme ordre preneur de prix : le
couplage avec le reste de l'Europe est pris comme donnée, l'allocation des capacités entre zones italiennes est
laissée au moteur.

## Ce que le rejeu a imposé au moteur

Deux règles d'EUPHEMIA, absentes du Code régional ouest-africain (pas horaire, MC 10.3.3), ont dû être ajoutées
au moteur pour reproduire les prix :

- **Ordres multi-MTU** (EPD-2025 §5.1) : un ordre de 60 min sur un marché au quart d'heure porte un ratio unique
  sur ses quatre MTU et est dans la monnaie sur la moyenne arithmétique de leurs prix. Champ `hours` de
  `HourlyOrder` ; sans lui, des ordres de vente rejetés apparaissent « dans la monnaie » sur un quart d'heure isolé.
- **Levée de l'indétermination des prix** (EPD-2025 annexe C) : quand plusieurs prix sont compatibles avec
  l'allocation, EUPHEMIA retient celui qui minimise la distance au milieu de l'intervalle admissible de chaque
  (zone, MTU), au sens des moindres carrés (programme quadratique convexe résolu par HiGHS via `highspy`, quelques secondes pour
  2 016 couples (zone, MTU)). Paramètre `price_rule="midpoint"` de `MarketParams` ; la règle par
  défaut du moteur (« dual », au plus près du dual du solveur) laisse un écart moyen de 0,48 EUR/MWh sur la même
  journée.

La quantité effective d'un ordre est la quantité ajustée par le système (`ADJ_QUANTITY_NO`), qui borne le volume
attribué.

## Niveaux

- **N2** : blocs remplacés par leurs volumes acceptés (preneurs de prix) ; clearing heure par heure (quatre MTU,
  pour respecter les ordres 60 min) ; comparaison des prix zonaux et des transits internes aux valeurs publiées.
- **N3** : blocs libres sur la journée entière (MILP à 96 MTU, marches agrégées par prix) ; comparaison des décisions
  de blocs (accepté, rejeté, rejeté paradoxalement) et des prix.

## Résultats

| Journée | Ordres | Blocs | N2 : prix exacts | N2 : écart moyen / max (EUR/MWh) | N2 : transits internes, écart moyen (MW) | Arcs saturés reproduits |
|---|---|---|---|---|---|---|
| 2026-01-20 | 289 248 | 79 | 628 / 672 | 0,06 / 5,40 | 27,1 | 160 / 209 |
| 2026-06-10 | 300 110 | 128 | 619 / 672 | 0,03 / 0,65 | 5,9 | 110 / 120 |
| 2026-09-15 | 291 551 | 173 | 589 / 672 | 0,15 / 15,25 | 1,3 | 128 / 131 |

N3 (blocs libres, journée entière, 9 à 11 s et trois itérations de cohérence par journée) :

| Journée | Blocs (soumis) | Même décision GME / moteur | dont paradoxalement rejetés (MILP + cohérence) | Décision différente | Prix exacts |
|---|---|---|---|---|---|
| 2026-01-20 | 76 (79) | 76 | 3 + 2 | 0 | 628 / 672 |
| 2026-06-10 | 121 (128) | 120 | 4 + 2 | 1 | 518 / 672 |
| 2026-09-15 | 168 (173) | 168 | 9 + 2 | 0 | 583 / 672 |

Les blocs soumis mais absents du MILP ont un profil non contigu, admis par GME mais exclu par le Code (heures
consécutives). Les 22 blocs publiés comme paradoxalement rejetés le sont aussi par le moteur. Le seul écart (10 juin)
est un bloc à ratio minimal 0,7 accepté à 96 % par EUPHEMIA et paradoxalement rejeté par le moteur ; ce bloc explique
l'essentiel des écarts de prix N3 de cette journée (quarts d'heure 41 à 64).

Surplus à ordres identiques (`welfare_gme.py`), hors positions de couplage :

| Journée | Surplus publié (EUR) | N2, blocs fixés : surplus (écart) | N3, blocs libres : surplus (écart) | Écart N3 (par million) |
|---|---|---|---|---|
| 2026-01-20 | 2 717 628 663 | 2 717 628 648 (−15) | 2 717 629 712 (+1 049) | 0,39 |
| 2026-06-10 | 2 389 313 090 | 2 389 313 060 (−31) | 2 389 315 664 (+2 573) | 1,08 |
| 2026-09-15 | 2 431 986 004 | 2 431 986 042 (+38) | 2 431 986 042 (+38) | 0,02 |

La solution publiée est admissible et à distance négligeable de l'optimum : c'est la mesure qu'un moteur
indépendant doit pouvoir produire pour le SMO.

Fichiers : `results_<date>_prices.csv`, `results_<date>_flows.csv`, `results_<date>_blocks.csv`.

```bash
.venv/bin/python examples/gme/replay_gme.py 20260610 --level 2
.venv/bin/python examples/gme/replay_gme.py 20260610 --level 3
```

Sources : GME, https://www.mercatoelettrico.org (Esiti > Elettricità > MGP > Download : Offerte Pubbliche, Limiti di
transito, Transiti, Prezzi) ; NEMO Committee, https://www.nemo-committee.eu/aggregated_curves ; EUPHEMIA Public
Description, 18 décembre 2025.
