---
title: "Marché day-ahead ouest-africain : sept points que le Code laisse ouverts et qui changent les résultats"
subtitle: "Note de discussion, version 0.1, document de travail"
author: "Djiby SECK, analyste quantitatif spécialisé dans les marchés de l'énergie, créateur de Sakkanal · admin@jabra-il.com · jabra-il.com"
date: "22 septembre 2026"
lang: fr
---

*L'auteur s'exprime à titre personnel. Cette note est écrite à partir des seuls textes publics : le Code régional du marché de l'électricité de l'Afrique de l'Ouest (REMC-WA, résolution 018/ERERA/25) et la description publique de l'algorithme de couplage européen (EUPHEMIA Public Description, NEMO Committee, 18 décembre 2025). Elle accompagne un moteur de clearing ouvert (github.com/jabrai-il/wapp-dam-clearing) qui reproduit les règles du Code et permet de chiffrer chacun des points ci-dessous.*

# Pourquoi cette note

Le Code régional définit un marché day-ahead de la même famille que l'enchère européenne couplée : ordres horaires, ordres en bloc, blocs liés, groupes exclusifs, allocation implicite des interconnexions, un prix par zone et par heure (MC 13.1.2.1, 16.1, 10.3.5). C'est un bon choix : l'algorithme est éprouvé, documenté publiquement, et sa théorie est connue.

Mais un code de marché fixe des objets, pas des procédures. En Europe, quinze ans d'exploitation ont produit une centaine de pages de règles complémentaires (départage, partage du délestage, familles de blocs, arrondis, validation de la solution). Le Code renvoie ces règles à des procédures du SMO encore à publier (« DAM Procedure », « DAM Clearing Procedure », MC 10.3.3.3, 13.1.4.4). Tant qu'elles n'existent pas, deux moteurs conformes au Code peuvent donner des prix différents sur les mêmes ordres. Pour des utilities qui découvrent le marché, pour les régulateurs nationaux qui devront expliquer des factures d'importation en dollars, c'est un risque.

En reconstruisant un moteur à partir du Code, j'ai relevé sept points de ce type. Pour chacun : ce que dit le Code, pourquoi cela compte davantage ici qu'en Europe, ce que je propose, et la question à poser.

# 1. Le partage du délestage entre pays

**Le Code.** Rien d'explicite. Un ordre de demande au plafond de prix (initialement 50 % du coût de l'énergie non servie, MC 10.3.4) est admis. Quand l'offre régionale ne suffit pas, le clearing sert une partie de ces ordres et pas l'autre.

**Pourquoi cela compte ici.** En Europe, ce cas est rare. En Afrique de l'Ouest, le déficit est structurel : la demande des utilities sera largement soumise au plafond, et le marché décidera, heure par heure, quelle part du délestage revient à chaque zone. Sans règle, ce choix est laissé au solveur, c'est-à-dire au hasard numérique.

**Proposition.** Reprendre la hiérarchie européenne : minimiser d'abord le volume total non servi, puis le partager au prorata des ordres preneurs de prix dans chaque ensemble de zones non congestionné, et publier ce volume par zone et par heure. Signaler les heures où le prix atteint le plafond.

**Question.** Le SMO prévoit-il une règle de partage, et l'ARREC a-t-elle fixé la valeur du coût de l'énergie non servie qui définit le plafond ? Cette valeur est, de fait, le prix régional du délestage.

**Un cas concret, celui du Mali.** EDM-SA vend en moyenne 106 FCFA/kWh (environ 180 USD/MWh) et produit à 160 FCFA/kWh ; son énergie non distribuée a atteint 402 GWh en 2023. Sur le marché, deux mécanismes vont rationner le Mali avant toute règle de partage : la limite de trading fixée par la chambre de compensation (MC 13.1.4.3), qui borne ce qu'un participant sous-capitalisé peut acheter, et le prix de ses propres bids, qu'une utility en déficit ne peut pas mettre au plafond sans creuser sa perte. Sur une journée stylisée de saison sèche calculée avec le moteur ouvert (quatre zones, 42 blocs, données publiques), un Mali dont les bids sont bornés à 180 USD/MWh perd 15 % de sa demande journalière, en soirée, alors que la liaison ivoirienne est saturée en permanence et que le Sénégal continue de lui livrer : aux heures où le prix régional dépasse 180, ses bids sont simplement hors de la monnaie. À l'inverse, s'il offrait au plafond, sa facture atteindrait 1,7 million USD par jour, l'équivalent de son chiffre d'affaires annuel en dix mois. Le marché ne rationne pas par la physique mais par la solvabilité. C'est un choix politique qui mérite d'être explicite.

# 2. Les blocs liés : deux lectures, 8 500 dollars d'écart

**Le Code.** Un bloc enfant n'est accepté que si son parent est exécuté (MC 13.1.2.1 c). Rien sur le surplus de la famille.

**Pourquoi cela compte ici.** Les blocs liés sont l'outil qu'auront les centrales thermiques (fioul, gaz) pour représenter un coût de démarrage sans ordre complexe : parent aux premières heures à prix élevé, enfants au coût variable. L'enchère européenne accepte un parent hors de la monnaie si ses enfants compensent sa perte ; une lecture littérale du Code l'interdit. Sur un exemple à trois blocs (demande 250 MW à 100 USD/MWh, parent 100 MW à 150, enfant 100 MW à 10, petit-enfant 50 MW à 10), la première lecture accepte la chaîne et crée 8 500 USD de bien-être ; la seconde rejette tout.

**Proposition.** Adopter explicitement les quatre règles de famille de l'enchère européenne, dont la contrainte ratio enfant ≤ ratio parent, dans la DAM Clearing Procedure.

**Question.** Quelle lecture le SMO retient-il ?

# 3. Les groupes exclusifs, définis puis oubliés

**Le Code.** MC 13.1.2.1 d) définit les groupes exclusifs ; MC 13.1.2.2 dit que « le SMO accepte les ordres horaires, les ordres en bloc et les blocs liés » sans les citer.

**Pourquoi cela compte ici.** Le groupe exclusif est le seul objet du Code qui permette à un producteur hydraulique d'offrir plusieurs profils de turbinage alternatifs (6 h, 8 h, 12 h) ou de représenter une contrainte d'énergie journalière. Sans lui, un réservoir doit deviner son profil à l'avance.

**Question.** Oubli de rédaction ou option différée ? Si différée, par quel calendrier ?

# 4. Les prix quand il n'y a presque personne

**Le Code.** Un prix par zone (MC 10.3.5), déterminé par l'équilibre des courbes (MC 15.3.4).

**Pourquoi cela compte ici.** Avec un participant par zone au lancement, les heures où un seul bloc accepté fait face à une demande inélastique seront la règle. Dans ces heures, l'ensemble des prix compatibles avec l'allocation est un intervalle entier, pas un point : le prix retenu dépend du chemin numérique du solveur. Deux moteurs conformes donnent deux prix, et un audit externe devient impossible.

**Proposition.** Définir le prix comme la solution d'un sous-problème explicite : parmi les prix compatibles avec les acceptations (conditions de complémentarité des ordres horaires et des flux), retenir ceux qui minimisent l'incohérence des blocs acceptés, puis une règle de départage publiée. C'est ce que fait l'enchère européenne et ce que fait le moteur ouvert.

**Question.** La DAM Clearing Procedure décrira-t-elle la détermination des prix à ce niveau de précision ?

# 5. Les pertes : sur les flux, sur les offres, ou les deux

**Le Code.** Les pertes sont à la charge des vendeurs et des acheteurs, avec des facteurs approuvés par les régulateurs (MC 13.5.3).

**Pourquoi cela compte ici.** Sur des interconnexions longues (OMVS, OMVG, dorsale côtière), les facteurs de pertes créent un écart de prix entre zones même sans congestion. Appliqués aux flux à l'arrivée, ils donnent un prix importateur égal au prix exportateur divisé par (1 − λ) ; appliqués aux offres, ils modifient les courbes elles-mêmes ; les deux à la fois comptent les pertes deux fois. Le moteur ouvert applique la première convention ; le résultat change avec la seconde.

**Question.** Quelle convention, et les facteurs seront-ils publiés par liaison et par heure ?

# 6. Le découpage des zones de prix

**Le Code.** « Autant de prix que d'areas » (MC 10.3.5), sans fixer le découpage.

**Pourquoi cela compte ici.** Une zone par pays est la lecture naturelle, mais certains réseaux nationaux sont eux-mêmes fragmentés (Mali, Nigeria) et certaines interconnexions sont partagées entre plusieurs pays. Fusionner deux zones supprime une rente de congestion et un signal d'investissement ; les scinder crée des prix différents à l'intérieur d'un pays, politiquement sensible.

**Question.** Le découpage initial est-il arrêté, et par qui est-il révisable ?

# 7. Ce qui sera publié, et donc vérifiable

**Le Code.** Publication des résultats agrégés sur le site du SMO (MC 15.3.3) ; le cas de « résultats erronés » est prévu (MC 13.4.1.1 b).

**Pourquoi cela compte ici.** La confiance dans un marché naissant se construit par la vérifiabilité. Si le SMO publie, pour chaque zone et chaque heure, les courbes agrégées d'offre et de demande, les flux et les prix, n'importe quel régulateur ou participant peut recalculer les résultats avec un second moteur et expliquer les écarts. Sinon, les résultats sont un acte de foi.

**Proposition.** Un format de publication ouvert (courbes agrégées, flux par liaison et direction, ATC, prix, volumes par statut de bloc) et l'existence d'au moins un moteur indépendant capable de les rejouer.

**Question.** Ce format est-il défini, et le WAPP accepterait-il un exercice de rejeu sur ses jeux d'essai ?

# Ce que je propose concrètement

Un moteur de clearing ouvert, écrit à partir du seul Code, existe (Python, solveur libre, licence MIT). Il implémente les sept points ci-dessus dans la lecture proposée, chacun désactivable pour mesurer l'écart avec la lecture alternative. Il peut servir :

- aux utilities, pour tester des stratégies d'ordres avant le lancement ;
- aux régulateurs nationaux et à l'ARREC, pour recalculer les résultats publiés ;
- au SMO, comme second regard sur ses jeux d'essai.

Un working paper en préparation formalise la formulation et démontre trois propriétés (existence des prix à blocs figés, non-existence en général pour les blocs, terminaison de la procédure de cohérence). Je cherche des praticiens pour confronter ces choix à la réalité de l'exploitation.

---

# Annexe : angle pour une publication

*Tribune (Le Quotidien, rubrique Opinions & débats, 900 mots) ou article LinkedIn.* Titre de travail : « Marché régional de l'électricité : les règles du jeu ne sont pas encore écrites ». Fil : (1) le Sénégal va acheter de l'électricité en dollars sur un marché dont personne n'a vu tourner l'algorithme ; (2) le Code fixe les objets, pas les procédures ; sept points ouverts, dont deux changent directement qui est délesté et à quel prix (§1, §2) ; (3) l'expérience européenne montre que ces règles se sont écrites en quinze ans, souvent après des incidents ; (4) proposition : un moteur ouvert, des résultats publiés dans un format rejouable, un exercice de rejeu des jeux d'essai avant le lancement ; (5) c'est une question de confiance entre pays, pas de technique.

*Signature* : Djiby Seck, analyste quantitatif spécialisé dans les marchés de l'énergie, créateur de Sakkanal. Il s'exprime ici à titre personnel.

*Ne pas y faire figurer* : toute information d'origine interne (Senelec, WAPP) ; toute référence à des outils propriétaires d'employeurs passés ou présents ; le nom de relecteurs.
