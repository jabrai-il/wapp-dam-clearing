# Instance stylisée à quatre zones : Sénégal, Mali, Côte d'Ivoire, Guinée

Jeu **synthétique** : les paliers d'offre, les profils de demande et les ATC sont des stylisations construites à
partir d'ordres de grandeur publics. Aucune donnée réelle de participant, aucune donnée interne. Deux saisons :
`hivernage` (septembre, hydraulique pleine) et `seche` (mars, étiage guinéen et OMVS, crise de combustible au Mali).

```bash
.venv/bin/python examples/wapp4/generate.py          # régénère orders_*.csv et atc_*.csv
.venv/bin/python examples/scenarios.py               # variantes A à E du working paper
```

## Ordres de grandeur retenus et sources

| Zone | Pointe (MW) | Parc stylisé (MW, USD/MWh) | Source |
|---|---|---|---|
| SN | 1 159 (13 août 2024) | horaires : hydro OMVS 127 à 33, solaire 266 MWc et éolien 55 à 1, HFO en marche 200 à 125 et 100 à 147, location de groupes 200 à 135, Kahone 100 à 150, TAG 50 à 400. Blocs : Sendou 115 à 61 (24 h, MAR 0,6) ; familles HFO Kounoune 67, Tobène 96, Cap des Biches 86 (pointe 150 à 165, journée 122 à 128) ; Malicounda 120 en trois durées exclusives ; TAG 100 en deux durées ; achat cimenterie 40 à 200 | Senelec, rapport annuel 2024 (puissance installée 1 904 MW ; coûts variables p. 33 : hydro 19,7, Sendou 36,8, HFO 75 à 88, TAG 240 FCFA/kWh) |
| ML | 475 (RI, avr. 2023) | horaires : hydro OMVS et Sotuba 191 à 33, solaire Kita 50 MWc, HFO en marche 60 à 220, diesel 40 à 320. Blocs : Sélingué 46 en deux profils exclusifs ; familles HFO Balingué 90 et Sirakoro 60 (pointe 240 à 250, journée 215 à 225) ; location diesel 50 à 300 (MAR 0,5) ; achat mines 60 à 250. Saison sèche : combustible divisé par deux | EDM-SA, rapport annuel 2023 (thermique 494,5 MW, coût de production moyen 159,6 FCFA/kWh, END 401,8 GWh, imports CI 255 GWh) |
| CI | ~1 800 (estimé ; 1 545 en 2020) | horaires : hydro fil de l'eau 350 à 33, gaz en marche 300 à 60 et 400 à 85 (tranche flexible réduite de 500 à 300 MW pour refléter la contrainte d'approvisionnement en gaz), TAG 300 à 130, HFO 200 à 200. Blocs : CCGT Azito 300 à 52 et Ciprel 250 à 55 (24 h, MAR 0,6) avec tranches de pointe liées ; Atinkou 200 à 58 ; réservoirs Soubré 275 et Kossou 150 en profils exclusifs ; TAG 150 en deux durées ; achat industrie 100 à 150 | CI-Energies (3 119 MW installés fin 2024, 66 % gaz, 33 % hydro ; coût de revient 89 FCFA/kWh) |
| GN | 829 (nov. 2024) | horaires : hydro fil de l'eau 300 à 33, HFO en marche 100 à 150. Blocs : Souapiti 450 en trois profils exclusifs (plat 300 MAR 0,6, pointe 450, 13 h 380) ; Kaléta pointe 80 à 38 ; KPS barge 110 à 140 (MAR 0,5) ; famille Té-Power 100 (pointe 170, journée 150) ; achat bauxite 80 à 160. Étiage : réservoirs à 45 % | EDG, rapport annuel 2024 (1 214 MW installés ; Souapiti 1 455 GWh, Kaléta 998 GWh ; étiage : environ 400 MW disponibles, sept. 2026) |

| Liaison | ATC stylisée (MW) | Pertes | Source |
|---|---|---|---|
| ML–SN (OMVS, Kayes–Tambacounda 225 kV) | 150 par sens | 4 % | OMVS, Manantali II (lignes biternes 400 MVA en cours) |
| CI–ML (Ferké–Sikasso–Ségou 225 kV, 2012) | 200 vers ML, 150 vers CI | 4 % | WAPP PIPES (400 MW) ; ATC vue par le day-ahead réduite au titre des contrats bilatéraux avec droits de transport (Phase 1 du Code) ; contrat garanti EDM 30 MW en 2023 |
| GN–SN (OMVG, boucle 225 kV) | 250 par sens | 3 % | OMVG (transit 800 MW) ; Banque mondiale (échange Guinée 340 MVA) ; Senelec 2024 (SN→GN 241,9 GWh, GN→SN 97,3 GWh) |
| GN–ML (Linsan–Fomi–Bamako 225 kV) | 200 par sens, variante D seulement | 5 % | BAD, rapport juin 2026 : clôture repoussée à fin 2026, pas en service |

Clés OMVS : Manantali 200 MW (Mali 52 %, Sénégal 33 %, Mauritanie 15 %), Félou 60 MW (45 / 25 / 30), Gouina 140 MW
(clé non trouvée, 33 % retenu pour SN et 40 % pour ML). Plafond de prix : 1 300 USD/MWh, soit 50 % d'un coût de
l'énergie non servie de 2 600 USD/MWh (valeur citée pour le Ghana dans le plan directeur WAPP 2018, volume 4 ;
aucune valeur ARREC publiée). Variante E : bids maliens à 180 USD/MWh, soit le prix moyen de vente d'EDM
(106,2 FCFA/kWh) converti à 600 FCFA/USD.

Saisonnalité : la pointe sénégalaise est en hivernage (août-octobre), celles du Mali, de la Côte d'Ivoire et de la Guinée en
saison sèche et chaude ; en saison sèche la demande est prise à −8 % au Sénégal et +5 % ailleurs. Variante C500 : plafond
de prix à 500 USD/MWh au lieu de 1 300, bids au plafond ramenés à 500.

Instance : 526 ordres horaires et 42 blocs par saison (8 familles liées, 7 groupes exclusifs, 4 blocs d'achat industriels).

## Incertitudes signalées

Puissance installée CI fin 2024 (2 909 à 3 119 MW selon les sources) ; pointe CI 2024 non publiée ; clé Manantali
Mali 52 ou 53 % ; capacité MW de la ligne Guinée–Mali non trouvée ; aucun chiffre officiel EDM-SA pour 2024 et 2025 ;
pas de prix de gros publié pour les échanges CI→ML et SN→ML ; coût variable par filière non publié en Côte d'Ivoire.
