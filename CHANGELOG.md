# Changelog

## Non publié

- Moteur : ordres horaires multi-MTU (`HourlyOrder.hours`, ratio unique, dans la monnaie sur la moyenne des prix,
  EPD-2025 §5.1) ; règle de levée de l'indétermination des prix `price_rule="midpoint"` (milieu de l'intervalle
  admissible, moindres carrés, EPD-2025 annexe C ; programme quadratique résolu par HiGHS, nouvelle dépendance
  `highspy`, secours SLSQP pour les petites tailles) ; format CSV : plage d'heures « 5-8 » pour un ordre multi-MTU.
- Cas de référence multi-zones : rejeu du marché italien GME (`examples/gme/`, `welfare_gme.py`) à partir du carnet d'ordres complet
  publié à J+7, des limites de transit, des transits et des prix zonaux ; niveaux N2 (blocs fixés, prix et flux) et
  N3 (blocs libres, décisions de blocs).
- Working paper v0.6 : filiation du Code, paragraphe MILP vs MIQP, sous-section « rejeu du marché italien ».

## 0.3.0 (2026-09-22)

Archivé sur Zenodo : DOI 10.5281/zenodo.22902965 (concept 10.5281/zenodo.22902401).

- Cas de référence européen : rejeu de trois journées du marché ibérique OMIE (`examples/omie/`), deux niveaux
  (courbes offertes ; décisions complexes données), 250 prix exacts sur 290, résidu dans l'intervalle d'indétermination.
- Working paper v0.5 : sous-section « Cas de référence : rejeu du marché ibérique », résumés et limites mis à jour.

## 0.2.0 (2026-09-22)

Archivé sur Zenodo : DOI 10.5281/zenodo.22902402 (concept 10.5281/zenodo.22902401).

- Instance stylisée à quatre zones SN, ML, CI, GN (`examples/wapp4`, deux saisons, 478 ordres horaires et 42 blocs
  par saison, sources publiques documentées) ; `examples/scenarios.py` reproduit les variantes A à E du working paper.

- Confrontation à EUPHEMIA Public Description 2025 : catalogue exhaustif des types d'ordres vs REMC-WA
  (`docs/proposition_types_ordres_remc.md`) ; sources PDF versionnées avec empreintes.
- Blocs liés : contrainte r_enfant <= r_parent et cohérence au niveau de la famille (parent hors de la monnaie
  accepté si ses enfants compensent ; feuille toujours dans la monnaie). Option `linked_family_rule`.
- Départage : ordres horaires à la monnaie au prorata (partage du délestage) ; blocs identiques par horodatage
  puis hachage. Champ `timestamp` sur les ordres.
- Arrondi half-up des prix (2 déc.) et des volumes publiés (MW entiers) ; ratio publié recalculé.
- Rapport de cohérence de la solution (7 contrôles, niveaux OK/TECHNICAL/DECOUPLING) dans `summary.json`.
- Bien-être de première itération, délestage des preneurs de prix, surplus de famille dans les sorties.
- Itération de cohérence : un seul bloc forcé au rejet par itération, le plus incohérent (`force_one_at_a_time`),
  ce qui réduit la perte de bien-être de la fixation gloutonne.
- 19 tests (dont l'exemple de non-existence de prix de la proposition 2 du working paper).

## 0.1.0 (2026-09-22)

- Modèle d'ordres REMC-WA (horaires, blocs à MAR, blocs liés, groupes exclusifs), liaisons ATC avec pertes.
- Validation à l'import avec motif par article (MC 13.1.4.2 à 13.1.4.5, 13.1.2.1 c).
- MILP de maximisation du bien-être (HiGHS via SciPy), LP de détermination des prix dans l'ensemble des duals
  optimaux, itération de fixation des blocs incohérents, écrêtage et arrondi des prix.
- Sorties CSV/JSON : prix, ordres, blocs, flux et rentes, positions, résumé ; CLI `wapp-dam clear`.
- 14 cas de test issus de la spécification §8 ; exemple synthétique 3 zones × 24 h ; CI GitHub Actions.
