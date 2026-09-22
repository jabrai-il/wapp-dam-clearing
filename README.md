# wapp-dam-clearing

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22902401.svg)](https://doi.org/10.5281/zenodo.22902401)

Moteur de clearing **day-ahead** conforme au Code régional du marché de l'électricité de l'Afrique de l'Ouest
(**REMC-WA**, ARREC, résolution 018/ERERA/25), en Python. Il reproduit la formation des prix du marché du jour
pour le lendemain du Marché régional de la CEDEAO opéré par le WAPP/ICC : ordres horaires, ordres en bloc à
ratio minimal d'acceptation, blocs liés, groupes exclusifs (MC 13.1.2.1), allocation implicite des capacités
d'interconnexion (MC 16.1), un prix par zone et par heure (MC 10.3.5), maximisation du bien-être régional
(MC 15.2.1, 15.3.4), écrêtage aux bornes ARREC (MC 15.3.5), validation motivée des ordres (MC 13.1.4).

Écrit à partir des seuls textes publics (REMC-WA ; EUPHEMIA Public Description du 18 décembre 2025, dont le Code
reprend la famille d'ordres ; les deux sont versionnés dans `docs/`). Aucun code ni document propriétaire. Licence MIT.

Périmètre : un code de recherche qui accompagne le working paper. Il ne contient aucune donnée réelle du marché
ouest-africain (l'instance `wapp4` est stylisée, construite sur des sources publiques citées) et ne constitue ni un
outil opérationnel ni une prestation de conseil ; les rejeux OMIE et GME utilisent des données publiées par ces
opérateurs.

Ce dépôt accompagne le working paper en préparation (`paper/`) :

> Seck, D. (2026). *Un moteur de clearing indépendant pour le marché day-ahead ouest-africain : formulation,
> propriétés et reproduction ouverte des règles du REMC-WA.* Working paper, version 0.6 (brouillon).

Code archivé sur Zenodo : version 0.4.0, DOI [10.5281/zenodo.22904811](https://doi.org/10.5281/zenodo.22904811) ; toutes versions, DOI [10.5281/zenodo.22902401](https://doi.org/10.5281/zenodo.22902401).

*English summary below.*

## Ce que fait le moteur

1. **Validation** des ordres à l'import avec motif de rejet par article du Code (MC 13.1.4.2 à 13.1.4.5).
2. **Clearing** : programme linéaire mixte (blocs entiers) résolu par HiGHS via SciPy (solveur interchangeable par le protocole `Solver`) ; maximisation du surplus.
3. **Prix** : blocs figés, l'ensemble des prix duaux compatibles avec l'allocation est caractérisé par les
   conditions de complémentarité des ordres horaires et des flux ; on y choisit les prix qui minimisent
   l'incohérence des blocs acceptés, puis l'écart au dual du solveur.
4. **Cohérence des blocs** avec les règles de famille des blocs liés (Euphemia 2025 §5.4.1) : une feuille
   acceptée doit être dans la monnaie ; un parent hors de la monnaie n'est accepté que si ses enfants compensent ;
   sinon le bloc est forcé au rejet et le problème résolu à nouveau. Les blocs paradoxalement rejetés sont listés.
5. **Départage** : ordres horaires à la monnaie au prorata (partage du délestage entre preneurs de prix) ;
   blocs identiques par horodatage puis hachage reproductible.
6. **Arrondi et rapport** : prix à 2 décimales et volumes en MW entiers (half-up) ; rapport de cohérence de la
   solution (niveau OK / TECHNICAL / DECOUPLING) sur le modèle d'Euphemia §8.2.
7. **Sorties** : prix, ratios et volumes par ordre, statut et surplus de famille des blocs, flux et rentes de
   congestion, positions nettes, bien-être total, par zone et avant rejets forcés, délestage des preneurs de prix, HHI.

## Installation et usage

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/wapp-dam clear examples/wapp4/orders_hivernage.csv examples/wapp4/atc_hivernage.csv --price-max 1300 --out results/demo
.venv/bin/python examples/scenarios.py   # variantes A à E du working paper
```

Utilisation programmatique :

```python
from wapp_dam import Market, MarketParams, HourlyOrder, BlockOrder, Link, BUY, SELL, clear

m = Market(zones=["ML", "SN"], params=MarketParams(hours=1, price_max=300))
m.hourly = [HourlyOrder("d", "SENELEC", "SN", 1, BUY, 100, 300),
            HourlyOrder("g", "EDM", "ML", 1, SELL, 200, 20)]
m.links = [Link("ML-SN", "ML", "SN", {1: 150}, loss_factor=0.03)]
r = clear(m)
print(r.prices, r.links[0].flow, r.congestion_rent())
```

## Formats d'entrée (MC 13.1.3.1)

`orders.csv` : `order_id,participant,zone,type,side,hour,quantity_mw,price,mar,parent_id,exclusive_group,cross_border`
(type `hourly` ou `block` ; un bloc occupe une ligne par heure de son profil).
`atc.csv` : `link_id,from_zone,to_zone,hour,atc_mw,loss_factor`.
`participants.csv` (optionnel) : `participant,trading_limit_mw`.

## Structure

```
src/wapp_dam/   orders.py (objets), validation.py (MC 13.1.4), model.py (MILP), solvers.py (protocole Solver, HighsSolver), prices.py (PriceDeterminer : prix, familles), clearing.py (Clearing : algorithme, départage, rapport), io.py, cli.py
tests/          21 cas : équilibre, solveur par protocole, ordre multi-MTU, market splitting, pertes, blocs, MAR, familles de blocs liés, exclusifs, non-existence de prix, délestage au prorata, départage, arrondi, écrêtage, validation
examples/       wapp4/ : instance stylisée 4 zones × 24 h, deux saisons (sources dans son README) ; scenarios.py ; omie/ : rejeu du marché ibérique ; gme/ : rejeu du marché italien au niveau de l'ordre (cas de référence)
docs/           spécification v0.1 + addendums v0.2 à v0.5, catalogue des types d'ordres Euphemia vs REMC-WA, note de concerns, sources PDF versionnées
paper/          working paper (LaTeX) ; make_instance_tables.py régénère l'annexe (instance_tables.tex) depuis le CSV
```

## Cas de référence

`examples/omie/replay_omie.py DATE` rejoue une journée du marché day-ahead ibérique (OMIE) à partir de ses courbes
agrégées publiées. Décisions sur les offres complexes prises comme données, le moteur retrouve le prix officiel au centime
sur 250 des 290 quarts d'heure de trois journées de 2026 ; les écarts restants sont tous dans l'intervalle
d'indétermination levé par le couplage avec la France. Détail dans `examples/omie/README.md`.

`examples/gme/replay_gme.py DATE --level 2|3` rejoue une journée du marché italien (GME) à partir du carnet d'ordres
complet publié à J+7, des limites de transit et des transits : 21 zones, 42 arcs, ordres 15/30/60 min et blocs avec
ratio minimal. Le moteur retrouve le prix zonal au centime sur 92 % des (quart d'heure, zone) et les transits
internes à quelques MW près. Détail dans `examples/gme/README.md`.

## Points à confirmer avec le SMO et l'ARREC

Découpage des zones de prix ; ordres horaires en marches (défaut) ou interpolés ; règle de départage ;
traitement des blocs paradoxalement rejetés ; application des facteurs de pertes ; plafond de prix initial
(coût de l'énergie non servie retenu) ; format de publication des résultats. Voir `docs/spec_moteur_clearing_wapp.md` §10.

## English summary

Open-source day-ahead market clearing engine implementing the public rules of the ECOWAS Regional Electricity
Market Code (REMC-WA): hourly, block (minimum acceptance ratio), linked and exclusive orders; implicit
allocation of cross-border capacity (ATC per direction and hour, optional loss factors); one price per zone
and hour from welfare maximisation (MILP, HiGHS through SciPy); price determination within the set of optimal
duals to minimise block incoherence; block-fixing iteration so that no accepted block is out of the money;
paradoxically rejected blocks allowed and reported; order validation with explicit reasons per Code article.
Written from public texts only, independent of any proprietary code. MIT licence.

## Auteur

Djiby Seck, analyste quantitatif spécialisé dans les marchés de l'énergie, créateur de Sakkanal.
Contact : admin@jabra-il.com · https://jabra-il.com. S'exprime et publie à titre personnel.
