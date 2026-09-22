---
title: "Types d'ordres du marché day-ahead ouest-africain : catalogue Euphemia 2025 confronté au REMC-WA et proposition d'adaptation"
author: "Djiby SECK, analyste quantitatif, marchés de l'énergie · créateur de Sakkanal · admin@jabra-il.com"
date: "22 septembre 2026, version 0.1, document de travail pour discussion"
lang: fr
---

# 0. Objet et sources

Ce document fait l'inventaire **exhaustif** des types d'ordres et des conditions associées que l'algorithme de couplage européen sait traiter, d'après la *EUPHEMIA Public Description* du 18 décembre 2025 (NEMO Committee, 90 p., ci-après « EPD-2025 »), et confronte chacun d'eux au Code régional du marché de l'électricité de l'Afrique de l'Ouest (REMC-WA, résolution 018/ERERA/25, ci-après « le Code »). Pour chaque objet, il donne : la définition Euphemia, la règle d'acceptation, ce que dit le Code, la pertinence pour le contexte ouest-africain, une **proposition** (retenir en v1, prévoir en v2, écarter) et l'état d'implémentation dans le moteur `wapp_dam`.

Il est rédigé à partir des seuls documents publics cités ; il ne reprend aucun code ni document propriétaire. L'expérience de l'auteur sur des simulateurs de marchés couplés (EDF R&D, TotalEnergies, GEMS-Engie) sert à hiérarchiser, pas à sourcer.

**Ce que le Code fixe déjà (rappel).**

- Produit : énergie à livraison physique dans le WAPPITS ; MTU d'une heure, 24 MTU par jour de livraison, référence UTC+1 ; le MTU peut changer par amendement de la « DAM Procedure » avec approbation de l'ARREC (MC 10.3.3).
- Prix : USD/MWh à deux décimales ; quantités en **MW entiers** (MC 13.1.3.2). Plancher initial 0,00 USD/MWh, plafond initial 50 % du coût de l'énergie non servie attendue, tous deux révisables par l'ARREC (MC 10.3.4) ; écrêtage du prix de clearing avec notification (MC 15.3.5).
- Zones : autant de prix DAM que d'« areas », offres simultanées possibles sur plusieurs zones (MC 10.3.5).
- Types d'ordres (MC 13.1.2.1) : a) horaires ; b) blocs à prix limite, ratio minimal d'acceptation (MAR) identique sur toutes les heures, quantité variable par heure, **heures consécutives** ; c) blocs liés parent-enfant (enfant accepté seulement si le parent est exécuté ; feuilles) ; d) groupes exclusifs (somme des ratios ≤ 1).
- **MC 13.1.2.2** : « The SMO shall accept the Hourly Orders, Block Orders, and Linked Block Orders » : les groupes exclusifs, définis en d), ne figurent pas dans cette liste. Point à clarifier avec le SMO (oubli de rédaction ou option différée).
- **MC 13.1.2.3** : tout nouveau type d'ordre (ou suppression) passe par une proposition du SMO approuvée par l'ARREC. C'est la porte d'entrée de tout ce qui est proposé « v2 » ci-dessous.
- Contenu minimal d'un ordre (MC 13.1.3.1) : code participant, type, offre/demande, quantité et prix, MTU, **localisation** de la production ou de la consommation, informations additionnelles définies par l'ETS.
- Validation (MC 13.1.4) : fenêtre de guichet, plage de prix, limite de trading fixée par la chambre de compensation, restrictions du SMO sur les types d'ordres, quantités d'export/import supérieures à l'ATC.
- Clearing (MC 15.3.4) : maximisation du bien-être régional, courbes d'offre croissante et de demande décroissante, prix d'équilibre par zone interconnectée et par MTU. Allocation implicite des capacités, simultanée au clearing (MC 16.1). Pertes à la charge des vendeurs et acheteurs (MC 13.5.3).

# 1. Catalogue des ordres de période (« horaires »)

Euphemia agrège les ordres de tous les participants d'une zone en une courbe de demande (prix décroissants) et une courbe d'offre (prix croissants) par période de 15, 30 ou 60 minutes (EPD-2025 §5.1). Trois formes de courbes existent.

## 1.1 Ordres en marches (*step orders*, courbes en escalier)

- **Euphemia** : deux points consécutifs ont soit le même prix, soit la même quantité. Règles : ordre dans la monnaie accepté en totalité, hors de la monnaie rejeté, à la monnaie accepté totalement, partiellement ou rejeté.
- **Code** : MC 13.1.2.1 a) « quantité horaire et son prix », c'est exactement une marche. MC 15.3.4 décrit le classement par prix et le point d'équilibre.
- **Contexte ouest-africain** : forme naturelle pour des utilities intégrées qui offrent des paliers de centrales (coût variable par groupe) et une demande par paliers de délestage.
- **Proposition : retenir en v1** comme forme unique des ordres horaires.
- **Moteur** : implémenté (`HourlyOrder`, ratio $x_o\in[0,1]$).

## 1.2 Ordres interpolés (courbes linéaires par morceaux)

- **Euphemia** : deux points consécutifs ne peuvent avoir le même prix (sauf aux bornes) ; la quantité acceptée est interpolée linéairement entre les prix $p_0$ et $p_1$ ; « dans la monnaie » s'apprécie sur $p_0$. Courbes hybrides (segments linéaires et marches) admises.
- **Code** : non mentionné. « Quantité horaire et son prix » suggère une marche.
- **Contexte** : les ordres interpolés produisent des prix intermédiaires et des acceptations fractionnaires fines ; peu utiles quand les quantités sont en MW entiers (MC 13.1.3.2) et que les participants sont peu nombreux. Ils compliquent l'explication des résultats à des participants qui découvrent le marché.
- **Proposition : écarter en v1 ; prévoir la structure de données** (option `interpolate` désactivée) pour ne pas fermer la porte si le SMO l'introduit via MC 13.1.2.3.
- **Moteur** : non implémenté (prévu dans la spec §3.1 comme option).

## 1.3 Ordres preneurs de prix (*price-taking orders*)

- **Euphemia** : ordres soumis au prix maximal (demande) ou minimal (offre) de la zone ; ils portent des exigences supplémentaires (EPD-2025 §6.5.1, renvoi vers le traitement de la pénurie : minimisation puis partage du *curtailment*, §7.9.1–7.9.2).
- **Code** : rien d'explicite ; un ordre au plafond de MC 10.3.4 est admis puisque dans la plage.
- **Contexte** : **c'est le cas le plus important pour l'Afrique de l'Ouest.** Les utilities sont en déficit structurel (délestages documentés au Sénégal, au Nigeria, au Ghana) ; leur demande sera largement soumise au plafond. Deux questions en découlent : (i) quand l'offre régionale ne couvre pas la demande preneuse de prix, *qui* est délesté et selon quelle règle ; (ii) le prix vaut alors le plafond (50 % du coût de l'énergie non servie), ce qui définit de facto la valeur régionale de l'énergie non servie.
- **Proposition : retenir en v1** avec une **règle de partage du délestage** explicite, calquée sur Euphemia : d'abord minimiser le volume total non servi, puis le répartir au prorata des ordres preneurs de prix de chaque zone dans le même ensemble non congestionné, en signalant les zones où le prix atteint le plafond. Ce point mérite d'être proposé au SMO comme contenu de la « DAM Clearing Procedure ».
- **Moteur** : ordres au plafond acceptés ; **partage du délestage non implémenté** (le solveur choisit arbitrairement entre ordres au même prix). À faire.

## 1.4 Résolutions temporelles multiples et appariement croisé (*cross-product matching*)

- **Euphemia** : MTU de 15, 30 ou 60 minutes, différents selon les zones ou coexistants dans une zone ; un ordre 60' peut être servi par quatre ordres 15' ; « règle de la moyenne » : le prix 60' est la moyenne des prix 15' sous-jacents ; les ordres plus grossiers que le MTU de leur zone peuvent être paradoxalement rejetés (EPD-2025 §6).
- **Code** : MTU horaire initialement, modifiable (MC 10.3.3.2–3).
- **Contexte** : sans objet au lancement ; les réseaux de la région n'ont ni la mesure ni la programmation infra-horaire. Mais l'expérience européenne montre que le passage au 15' arrive, et qu'il est coûteux s'il n'a pas été anticipé dans les structures de données.
- **Proposition : écarter en v1, concevoir le modèle de données avec un MTU paramétrable** (déjà le cas : `MarketParams.hours`) et documenter la règle de la moyenne comme voie d'évolution.
- **Moteur** : nombre d'heures paramétrable ; pas de résolutions mixtes.

## 1.5 Ordres de mérite (*merit orders*)

- **Euphemia** : ordre en marche portant un numéro de mérite unique par période et par type ; à prix égal au prix de clearing dans un ensemble de zones non congestionné, le numéro le plus bas est servi d'abord (EPD-2025 §5.5.1, exemples fig. 13 ; « merit order enforcement » §7.9.4).
- **Code** : non prévu comme type d'ordre ; mais la règle de départage entre ordres à la monnaie relève des « restrictions et paramètres de soumission spécifiés par le SMO » (MC 13.1.4.4) et de la DAM Clearing Procedure.
- **Contexte** : utile pour donner une priorité réglementaire, par exemple aux offres d'énergie renouvelable ou hydraulique de fil de l'eau (obligation de priorité qu'on retrouve dans plusieurs codes nationaux) ou aux contrats d'achat garantis. Attention : c'est aussi un moyen de discrimination ; l'ARREC devra encadrer.
- **Proposition : v2**, à soumettre au SMO comme règle de départage (d'abord prix, puis numéro de mérite, puis prorata).
- **Moteur** : non implémenté ; le départage à la monnaie est laissé au solveur (à remplacer par une règle explicite en v1, voir §5).

## 1.6 Ordres PUN

- **Euphemia** : ordres de demande italiens réglés au prix unique national plutôt qu'au prix zonal ; **retirés des entrées d'Euphemia depuis le 1er janvier 2025** (EPD-2025 §5.5.2).
- **Proposition : écarter.** Mentionné pour exhaustivité et parce que la question « prix zonal ou prix unique pour la demande d'un pays » pourrait ressurgir politiquement en Afrique de l'Ouest : l'exemple italien montre que c'est un dispositif de règlement, pas un type d'ordre, et qu'il a été abandonné.

# 2. Catalogue des ordres en bloc

Un bloc porte un sens, un prix limite, des périodes, un volume par période, un MAR (EPD-2025 §5.4). Un bloc hors de la monnaie ne peut jamais être accepté ; un bloc dans ou à la monnaie peut être accepté, accepté partiellement (≥ MAR, ratio unique sur toutes ses périodes) ou paradoxalement rejeté (PRB / PPRB).

## 2.1 Bloc régulier *fill-or-kill* (MAR = 1, volume constant, heures consécutives)

- **Code** : MC 13.1.2.1 b). **Retenir v1. Implémenté.**

## 2.2 Bloc profilé (volume variable par heure)

- **Euphemia** : oui. **Code** : « the energy quantity may vary in different Market Time Units ». **Retenir v1. Implémenté** (`profile`).
- **Contexte** : indispensable pour l'hydraulique à réservoir (Manantali, Kaléta-Souapiti, Akosombo) qui offre une énergie journalière avec un profil de turbinage.

## 2.3 Bloc écrêtable (*curtailable*, MAR < 1)

- **Euphemia** : acceptation partielle à ratio unique ≥ MAR, quantités par période arrondies au tick de volume. **Code** : MAR prévu, identique sur toutes les heures. **Retenir v1. Implémenté** ($m_b u_b \le r_b \le u_b$).
- **Contexte** : permet aux groupes thermiques de déclarer un minimum technique (MAR = Pmin/Pmax).
- **Point d'arrondi** : le Code impose des MW entiers ; un ratio de 0,808 sur 200 MW donne 161,6 MW. Proposer : quantités acceptées arrondies au MW le plus proche (*round-half-up*, EPD-2025 §8.1), le ratio publié étant recalculé après arrondi. **À faire dans le moteur.**

## 2.4 Bloc à périodes non consécutives

- **Euphemia** : admis (exemple §5.4 : périodes 3-7, 8-19, 22-24). **Code** : « consecutive Market Time Units » : **incompatible tel quel**.
- **Contexte** : utile pour une centrale qui offre la pointe du matin et celle du soir en une seule décision (groupes fioul sénégalais), ou pour un stockage. Contournable en v1 par deux blocs liés ou un groupe exclusif.
- **Proposition : écarter en v1 ; candidat v2** via MC 13.1.2.3 si les participants le demandent. Le moteur rejette aujourd'hui les blocs non consécutifs à la validation (MC 13.1.4.4), conformément au Code.

## 2.5 Blocs liés (*linked blocks*, familles parent-enfant)

- **Euphemia** (EPD-2025 §5.4.1), quatre règles : (1) ratio du parent ≥ plus grand ratio de ses enfants ; (2) l'acceptation (éventuellement partielle) des enfants peut permettre celle du parent si le surplus de la famille est non négatif et si les feuilles ne créent pas de perte de surplus ; (3) **un parent hors de la monnaie peut être accepté si ses enfants acceptés compensent sa perte** ; (4) un enfant hors de la monnaie ne peut pas être accepté même si son parent le compenserait, sauf s'il est lui-même parent d'autres blocs (règle 3).
- **Code** : MC 13.1.2.1 c) ne fixe que « l'enfant n'est accepté que si le parent est exécuté ». Il ne dit rien du surplus de famille.
- **Contexte** : c'est l'outil v1 pour représenter un coût de démarrage sans ordre complexe : parent = premières heures à prix élevé (amortissement du démarrage), enfants = heures suivantes au coût variable. La règle 3 d'Euphemia est ce qui rend cette représentation efficace.
- **Proposition : retenir v1 avec les quatre règles d'Euphemia**, en les proposant au SMO comme interprétation de MC 13.1.2.1 c) dans la DAM Clearing Procedure. Deux variantes à trancher : ratio enfant ≤ ratio parent (Euphemia) ou simple implication binaire (lecture littérale du Code).
- **Moteur, écart identifié** : la version 0.1 impose $u_{\text{enfant}} \le u_{\text{parent}}$ (implication binaire) et la cohérence **bloc par bloc**, ce qui force au rejet un parent hors de la monnaie même si sa famille est profitable. C'est plus restrictif qu'Euphemia. À adapter : cohérence au niveau de la famille (surplus de famille ≥ 0, feuilles dans la monnaie) et contrainte $r_{\text{enfant}} \le r_{\text{parent}}$. L'exemple des blocs liés sur trois niveaux du brouillon de working paper (proposition 2) doit être remplacé par un exemple de non-existence qui ne dépende pas de cette règle (bloc simple contre ordre horaire partiel).

## 2.6 Groupes exclusifs

- **Euphemia** : somme des ratios ≤ 1 ; avec MAR = 1, au plus un bloc accepté ; l'algorithme choisit la combinaison qui maximise le surplus (EPD-2025 §5.4.2). **Code** : MC 13.1.2.1 d), même définition, mais absent de MC 13.1.2.2 (voir §0).
- **Contexte** : permet à une centrale de proposer plusieurs plages de fonctionnement alternatives (6 h, 8 h, 12 h) ou à un importateur de choisir entre deux profils.
- **Proposition : retenir v1**, en demandant au SMO de confirmer l'admission effective (MC 13.1.2.2). **Implémenté.**

## 2.7 Ordres flexibles (*flexible orders*)

- **Euphemia** : bloc d'une période, prix et volume fixes, MAR = 1, dont la **période est choisie par l'algorithme** (EPD-2025 §5.4.3).
- **Code** : non prévu.
- **Contexte** : pertinent pour un stockage ou un groupe de pointe qui veut vendre une heure quelconque au meilleur prix, ou pour une charge pilotable (dessalement, pompage). Faible complexité.
- **Proposition : v2** via MC 13.1.2.3. Modélisable en v1 par un groupe exclusif de 24 blocs d'une heure (équivalent exact) : à proposer comme **recette de contournement** documentée.
- **Moteur** : non implémenté en tant que tel ; contournement disponible.

## 2.8 Règles de départage entre blocs identiques

- **Euphemia** (EPD-2025 §5.4.4) : deux blocs sont identiques s'ils ont même zone, MAR, prix, sens, périodes et quantités, même groupe exclusif, sans liens ; départage par horodatage de dernière modification, puis par un **hachage reproductible** des paramètres (pour ne pas favoriser un hub de soumission).
- **Code** : rien. **Proposition : retenir v1** (horodatage puis hachage), à inscrire dans la DAM Clearing Procedure ; c'est une exigence de reproductibilité et d'équité entre participants. **Moteur : à faire** (aujourd'hui départage laissé au solveur).

# 3. Catalogue des ordres complexes

## 3.1 Ordre complexe à condition de revenu minimal (MIC) / paiement maximal (MP)

- **Euphemia** (EPD-2025 §5.2, 5.2.1) : ensemble de sous-ordres en marches d'un même participant sur plusieurs périodes, activé ou désactivé **en bloc** par une condition économique : revenu total ≥ terme fixe (coût de démarrage, en monnaie) + terme variable × énergie acceptée. Si la condition n'est pas remplie, tous les sous-ordres sont rejetés, même dans la monnaie ; si elle est remplie mais l'ordre rejeté : paradoxalement rejeté ; la solution finale ne contient jamais de MIC actif ne vérifiant pas sa condition.
- **Code** : non prévu.
- **Contexte** : **c'est l'objet le plus adapté au parc thermique ouest-africain** (fioul lourd, gaz, diesel) : coût de démarrage élevé, coût variable indexé sur le combustible, contrainte de recette. Il évite au participant de deviner à l'avance combien d'heures son groupe tournera (ce que les blocs liés obligent à faire).
- **Proposition : v2 prioritaire**, à proposer au SMO après une première période d'exploitation avec blocs liés. Prérequis : la condition MIC rend le problème plus dur (contrainte non linéaire prix × volume, traitée par itération dans Euphemia, §7.7 « PRMIC reinsertion ») ; à chiffrer sur des instances de la taille du WAPP (15 zones, quelques centaines d'unités) avant de s'engager.
- **Moteur** : non implémenté.

## 3.2 Arrêt programmé (*scheduled stop*)

- **Euphemia** (§5.2.2) : si le MIC est désactivé, le premier (moins cher) sous-ordre des périodes d'arrêt programmé (au plus les 3 premières heures, consécutives, depuis la première période) reste traité comme un ordre horaire, pour éviter un arrêt brutal d'un groupe qui tournait la veille. Pas pour les MP.
- **Contexte** : pertinent pour les groupes lents (vapeur, cycle combiné). **v2, avec le MIC.**

## 3.3 Gradient de charge (*load gradient*)

- **Euphemia** (§5.2.3) : l'énergie acceptée en une période est bornée par celle de la période précédente ± un incrément/décrément maximal (même valeur toutes les périodes ; période 1 non contrainte par la veille).
- **Code** : non prévu.
- **Contexte** : traduit les rampes techniques des groupes vapeur et des cycles combinés ; utile aussi pour lisser les échanges (le Code prévoit par ailleurs des limites de rampe côté exploitation).
- **Proposition : v2**, éventuellement avant le MIC car linéaire et simple à implémenter (contrainte $|e_h - e_{h-1}| \le g$).

## 3.4 Ordres complexes échelonnables (*scalable complex orders*, SCO)

- **Euphemia** (§5.3) : comme un MIC/MP mais sans terme variable (la condition porte sur le terme fixe et les marches des sous-ordres), avec une **puissance minimale d'acceptation par période** (0 par défaut) ; gradient et arrêt programmé possibles.
- **Contexte** : plus proche encore de la réalité d'un groupe (Pmin par heure). **v2, alternative au MIC** ; à choisir l'un ou l'autre selon ce que les participants savent renseigner.

## 3.5 Règles de départage des ordres complexes

- **Euphemia** (§5.2.4, 5.3.4) : identité sur tous les paramètres ; départage par horodatage puis hachage. Même proposition que §2.8.

# 4. Contraintes réseau associées aux ordres (EPD-2025 §4)

Elles ne sont pas des types d'ordres mais conditionnent leur acceptation ; l'exhaustivité impose de les lister.

| Objet Euphemia | Description | Code | Proposition | Moteur |
|---|---|---|---|---|
| Capacités déjà allouées (§4.1) | ATC = NTC moins droits long terme nominés | MC 16.1 renvoie au Code d'exploitation ; PTR du marché OTC (MC 7) | v1 : ATC reçus en entrée, calculés hors moteur | reçu en entrée |
| Zones d'enchères, zones de programmation, hubs (§4.2, 4.5, 4.6) | Topologie à trois niveaux | « areas » (MC 10.3.5) | v1 : un niveau (zone = area) ; zones fusionnables | implémenté |
| Rampes de position nette (§4.2.1) | Variation max de la position nette d'une zone entre périodes, et journalière | non prévu (rampes côté exploitation) | v2 | non |
| ATC par direction et heure (§4.3.1) | Borne sur le flux | MC 16.1 | v1 | implémenté |
| Pertes (§4.3.2) | Fraction perdue en transit, à la charge des échanges | MC 13.5.3 | v1, appliquées aux flux à l'arrivée ; **application aux offres ou aux deux à confirmer avec le SMO** | implémenté |
| Tarifs de flux (§4.3.3) | Coût par MWh transité (câbles marchands) : seuil de prix entre zones | non prévu comme tel ; méthodologie tarifaire de transit WAPP existante | v2 : représenter un éventuel tarif de transit régional | non |
| Rampes de flux par ligne et par ensembles de lignes (§4.3.4–4.3.6) | Variation max du flux entre périodes | non prévu | v2 | non |
| Contraintes sur ensembles de lignes, ATC parallèles (§4.3.5, 4.3.7, 4.3.8) | Capacité commune à plusieurs liaisons | non prévu ; utile si OMVS et OMVG partagent une limite | v2 | non |
| Contrainte externe (§4.3.9) | Borne sur la position nette | non prévu | v2 | non |
| Modèle *flow-based* et inclusion des droits long terme (§4.4) | PTDF au lieu d'ATC | non prévu (ATC explicite) | écarter tant que le Code est en ATC | non |

# 5. Règles de solution (EPD-2025 §7–8) à transposer

- **Précision et arrondi** (§8.1) : résultats non arrondis satisfaisant les contraintes à une tolérance près, puis arrondi commercial (*round-half-up*) des prix et volumes avant publication. **Proposition v1** : prix à 2 décimales, volumes en MW entiers, arrondi *half-up* (Python arrondit *half-even* par défaut : à corriger dans le moteur).
- **Validation de la solution** (§8.2) : vérification explicite des contraintes, bornes, intégralité, et **conditions de complémentarité** (pas d'écart de prix sans congestion, pas d'ordre horaire paradoxalement accepté ou rejeté), avec niveaux de tolérance (STRICT / OK / TECHNICAL / DECOUPLING). **Proposition v1** : produire le même rapport de cohérence ; le moteur calcule déjà les prix dans l'ensemble des duals compatibles (`prices.py`), il reste à émettre le rapport.
- **Indétermination des volumes** (§7.9) : à prix et surplus égaux, choisir les volumes par une hiérarchie : minimiser le délestage, le partager, maximiser les volumes acceptés, appliquer les numéros de mérite, lever l'indétermination des flux (répartition uniforme entre lignes parallèles). **Proposition v1** : au minimum les deux premiers (délestage) et le troisième.
- **Sous-problème de détermination des prix** (§7.5) : Euphemia sépare l'optimisation des blocs (problème maître, *branch-and-cut*) et la détermination des prix (LP) ; les blocs paradoxalement acceptés sont exclus par coupes puis le maître est relancé. Le moteur fait la version gloutonne (fixation, sans branchement) : suffisant pour un audit, à améliorer pour un usage opérationnel.
- **Réinsertion des blocs paradoxalement rejetés** (§7.8) : après convergence, tenter de réinsérer les PRB pour améliorer le surplus. **v2.**
- **Critères d'arrêt et reproductibilité** (§7.10–7.11) : limite de temps, horloge déterministe, mêmes entrées → mêmes sorties. **v1** : le moteur est déterministe (HiGHS mono-thread) ; limite de temps paramétrable.
- **Transparence** (§8.3) : publication de la solution de plus grand surplus respectant toutes les règles. Le Code prévoit la publication des résultats agrégés (MC 15.3.3) ; **proposer** au SMO un format de publication (courbes agrégées par zone et heure, flux, prix) qui permette la vérification externe.

# 6. Tableau de synthèse

| # | Objet | Euphemia 2025 | REMC-WA | Proposition | Moteur v0.1 |
|---|---|---|---|---|---|
| 1.1 | Ordre horaire en marche | oui | oui (13.1.2.1 a) | **v1** | fait |
| 1.2 | Ordre interpolé / hybride | oui | non | écarter v1, structure prête | non |
| 1.3 | Ordre preneur de prix + partage du délestage | oui | implicite | **v1, règle à proposer au SMO** | partiel |
| 1.4 | MTU 15'/30', appariement croisé | oui | MTU modifiable | écarter v1, MTU paramétrable | partiel |
| 1.5 | Ordre de mérite | oui | non | v2 (départage) | non |
| 1.6 | PUN | retiré 2025 | non | écarter | non |
| 2.1 | Bloc régulier | oui | oui | **v1** | fait |
| 2.2 | Bloc profilé | oui | oui | **v1** | fait |
| 2.3 | Bloc écrêtable (MAR < 1) | oui | oui | **v1** + arrondi MW | fait, arrondi à faire |
| 2.4 | Bloc à périodes non consécutives | oui | non (consécutives) | v2 | rejeté à la validation |
| 2.5 | Blocs liés, règles de famille | oui (4 règles) | oui (règle minimale) | **v1 avec les 4 règles** | à adapter |
| 2.6 | Groupe exclusif | oui | oui (13.1.2.1 d, absent de 13.1.2.2) | **v1**, à confirmer | fait |
| 2.7 | Ordre flexible | oui | non | v2 ; contournement = groupe exclusif de 24 blocs | contournement |
| 2.8 | Départage blocs (horodatage, hachage) | oui | non | **v1** | à faire |
| 3.1 | MIC / MP | oui | non | v2 prioritaire | non |
| 3.2 | Arrêt programmé | oui | non | v2 | non |
| 3.3 | Gradient de charge | oui | non | v2 (simple) | non |
| 3.4 | Ordre complexe échelonnable | oui | non | v2, alternative au MIC | non |
| 4 | Rampes, tarifs, ensembles de lignes, flow-based | oui | non | v2 / écarter | non |
| 5 | Arrondi half-up, rapport de cohérence, indétermination des volumes | oui | partiel (13.1.3.2, 15.3.5) | **v1** | partiel |

# 7. Adaptation au contexte ouest-africain : ce qui change par rapport à l'Europe

1. **La pénurie est l'état normal, pas l'exception.** En Europe, le partage du délestage est un cas limite ; ici, il sera fréquent. La règle de partage (§1.3) et la valeur du plafond (50 % du coût de l'énergie non servie) sont des choix politiques autant que techniques : ils décident qui, du Sénégal ou du Mali, est délesté quand l'hydraulique guinéenne manque. À mettre en tête des discussions avec le SMO et l'ARREC.
2. **Un participant par zone au départ.** Les utilities intégrées seront à la fois l'acheteur et le vendeur dominant de leur zone. Les règles de départage, la détection des ordres au plafond et les indicateurs de concentration (MC 21, 22) comptent plus que la finesse des types d'ordres. Les ordres de mérite (§1.5) sont à manier avec prudence.
3. **Hydraulique à réservoir et thermique à démarrage coûteux.** Les blocs profilés et liés (v1) couvrent l'essentiel ; le MIC (v2) est la vraie réponse pour le thermique. Les contraintes d'énergie journalière des réservoirs n'existent dans aucun type d'ordre Euphemia : elles se représentent par des groupes exclusifs de profils alternatifs.
4. **Quantités en MW entiers, prix en USD.** Simplifie l'arrondi mais interdit les ordres interpolés fins ; le change USD/FCFA/GHS/NGN est hors marché (règlement, MC 15.4) mais pèsera sur les stratégies d'offre.
5. **Contrats bilatéraux et PTR (Phase 1) avant le DAM (Phase 2).** Les capacités déjà allouées réduisent l'ATC ; le moteur doit recevoir des ATC nets. La cohérence entre nominations PTR et clearing DAM (MC 7.2 sur l'écrêtement des PTR) est un sujet d'exploitation à part.
6. **Faible liquidité initiale → prix dégénérés.** Avec peu d'ordres, les heures où un seul bloc fait face à une demande inélastique seront courantes ; le choix des prix dans l'ensemble des duals compatibles (§5) n'est pas un raffinement mais une nécessité de reproductibilité et d'auditabilité.

# 8. Séquencement proposé et questions ouvertes pour la discussion

**v1 (conforme au Code, prête à l'audit)** : ordres horaires en marches, blocs réguliers/profilés/écrêtables, blocs liés avec règles de famille, groupes exclusifs, ATC et pertes, partage du délestage, départage horodatage-hachage, arrondi half-up, rapport de cohérence, publication vérifiable.

**v2 (extensions via MC 13.1.2.3)** : gradient de charge, ordres flexibles, ordres de mérite, MIC/MP ou SCO avec arrêt programmé, blocs non consécutifs, rampes de position nette et de flux, tarif de transit.

**v3 (au-delà)** : MTU infra-horaire et appariement croisé, contraintes sur ensembles de lignes, réinsertion des PRB, branchement sur les blocs.

**Questions publiques à poser au SMO / à l'ARREC (ou à un praticien)** : découpage des zones de prix ; admission effective des groupes exclusifs (MC 13.1.2.2) ; règle de partage du délestage et valeur retenue du coût de l'énergie non servie ; application des pertes (flux, offres, ou les deux) ; règle de départage ; interprétation des blocs liés (famille ou implication simple) ; calendrier des jeux d'essai de l'ETS et format de publication des résultats.

# Annexe. Écarts à corriger dans `wapp_dam` (issus de cette confrontation)

1. Blocs liés : passer à la cohérence de famille et à $r_{\text{enfant}} \le r_{\text{parent}}$ (§2.5) ; remplacer l'exemple de la proposition 2 du working paper.
2. Partage du délestage entre ordres preneurs de prix (§1.3) et hiérarchie d'indétermination des volumes (§5).
3. Départage horodatage puis hachage (§2.8) : ajouter un horodatage et un hachage aux ordres.
4. Arrondi des volumes au MW entier en *half-up* et recalcul du ratio publié (§2.3, §5).
5. Rapport de cohérence de la solution avec niveaux de tolérance (§5).
6. Structure de données : option d'interpolation, période non consécutive (refusée en v1 mais représentable), MTU générique.

*Sources : EUPHEMIA Public Description, 18 décembre 2025, NEMO Committee (§4–8) ; REMC-WA, résolution 018/ERERA/25, MC 7, 10.3, 13.1, 13.5, 15.3, 15.4, 16.1, 21, 22. Les deux documents sont versionnés dans `docs/` avec leur empreinte SHA-256.*
