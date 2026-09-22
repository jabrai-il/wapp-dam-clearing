---
title: "Moteur de clearing day-ahead conforme au REMC-WA"
subtitle: "Spécification fonctionnelle, version 0.1 (document de travail)"
author:
  - "Djiby SECK"
  - "Analyste quantitatif, marchés de l'énergie · Créateur de Sakkanal"
  - "[admin@jabra-il.com](mailto:admin@jabra-il.com) · [jabra-il.com](https://jabra-il.com)"
date: "10 septembre 2026"
lang: fr
---

# 0. Objet du document

Ce document spécifie un moteur de clearing du marché day-ahead (DAM) du Marché régional de l'électricité de la CEDEAO, conforme au Code régional du marché de l'électricité de l'Afrique de l'Ouest (REMC-WA, approuvé par la résolution 018/ERERA/25). Il constitue la première couche d'une plateforme de simulation du marché régional et du système sénégalais, et sert de base de discussion avec le WAPP, le Centre d'information et de coordination (ICC, futur opérateur système et de marché, SMO), l'ARREC, les gestionnaires nationaux et les participants au marché.

Le moteur n'est pas la plateforme de trading (ETS) du SMO et n'a pas vocation à la remplacer. C'est un outil indépendant de simulation, de vérification et d'aide à la décision, qui reproduit les règles de formation des prix du Code afin de :

- **rejouer** une journée de marché à partir d'un carnet d'ordres et d'ATC (clearing miroir, audit des résultats) ;
- **simuler** des journées de marché à partir de scénarios de parc, de demande et d'interconnexions (prix attendus avant le lancement, valeur des interconnexions) ;
- **optimiser** la stratégie d'offre d'un participant (utility, producteur indépendant, stockage) ;
- **surveiller** le marché (indicateurs de concentration, congestion, rentes, ordres paradoxaux).

Ce document est écrit à partir des seuls textes publics : le REMC-WA et la description publique de l'algorithme de couplage européen (Euphemia), dont le Code reprend la structure d'ordres. Il ne reprend aucun élément propriétaire.

# 1. Contexte

Le REMC-WA organise le Marché régional en deux composantes : un marché de gré à gré (OTC) de contrats bilatéraux transfrontaliers, avec allocation explicite de droits de transport (PTR) par enchères, et un marché centralisé day-ahead (DAM), opéré par le SMO comme contrepartie unique (MC 2.3.3). Le DAM est optionnel pour les participants (MC 13.1.1.1), fonctionne au pas horaire sur 24 unités de temps (MC 10.3.3.2), en dollars américains (MC 2.3.5), avec allocation implicite de la capacité transfrontalière simultanée au clearing (MC 16.1) et autant de prix que de zones (MC 10.3.5). Les types d'ordres (MC 13.1.2.1) sont les ordres horaires, les ordres en bloc à ratio minimal d'acceptation, les blocs liés et les groupes exclusifs : c'est la famille d'objets de l'enchère européenne couplée.

Aucun acteur de la sous-région n'a encore observé un tel marché en fonctionnement. Un moteur de clearing indépendant, disponible avant le lancement de la Phase 2, permet aux utilities de s'y préparer, au régulateur de vérifier, et aux analystes de chiffrer ce que le couplage rapportera à chaque pays.

# 2. Référentiel réglementaire repris

| Règle | Article REMC-WA | Traduction dans le moteur |
|---|---|---|
| DAM centralisé, SMO contrepartie unique, ordres par agrégation de portefeuilles | MC 2.3.3 | Un participant = un portefeuille par zone ; pas de contrepartie bilatérale |
| Unité de temps horaire, 24 MTU, référence UTC+1 | MC 10.3.3.2, 10.3.3 | Index horaire $h \in \{1,\dots,24\}$ ; horodatage UTC+1 |
| Prix en USD/MWh à deux décimales, quantités en MW entiers | MC 13.1.3.2 | Types de données et arrondis |
| Ordres horaires, blocs (prix limite, MAR, quantités par heure), blocs liés parent-enfant, groupes exclusifs | MC 13.1.2.1 a-d | Objets d'ordres, section 4 |
| Contenu minimal d'un ordre (identifiant, type, sens, quantité, prix, MTU, localisation) | MC 13.1.3.1 | Schéma d'import, section 6 |
| Rejet automatique : hors guichet, hors plage de prix, au-delà de la limite de trading, quantité export/import supérieure à l'ATC | MC 13.1.4.1 à 13.1.4.5 | Module de validation, section 6 |
| Plage de prix : minimum 0 USD/MWh, maximum 50 % du coût de l'énergie non servie attendue (paramètres ARREC) | MC 10.3.4 | Bornes de prix paramétrables ; écrêtage du prix de clearing (MC 15.3.5) |
| Prix par zone, offres simultanées sur plusieurs zones | MC 10.3.5 | Prix zonal $\pi_{z,h}$ ; market splitting |
| Clearing : maximisation du bien-être régional par MTU ; courbes d'offre croissante et de demande décroissante ; prix d'équilibre par zone interconnectée | MC 15.2.1, 15.3.4 | Fonction objectif et prix duaux, section 4 |
| Allocation implicite de la capacité, simultanée au clearing, publiée par heure et par direction | MC 16.1.1 à 16.1.5 | Contraintes ATC par direction ; sortie des flux et rentes |
| Pertes à la charge des vendeurs et acheteurs, facteurs de pertes approuvés par les régulateurs | MC 13.5.3 | Coefficients de pertes par interconnexion, appliqués aux quantités |
| Positions nettes par participant, obligations et créances | MC 15.4 | Calcul des positions, section 5 |
| Valorisation des déséquilibres au prix DAM horaire, cycle de sept jours | MC 18.1.1.4 | Module de valorisation ex post (couche 3) |
| Surveillance : pratiques anticoncurrentielles, rétention de capacité | MC 21, MC 22 | Indicateurs, section 7 |

# 3. Périmètre fonctionnel

## 3.1 Objets du modèle

**Zones.** Le Code prévoit « autant de prix DAM que de zones » sans fixer leur découpage. Le moteur traite les zones comme un paramètre : par défaut une zone par zone de réglage (Control Area) nationale, avec possibilité de fusionner (zone synchrone unique) ou de scinder. Chaque zone porte un ensemble d'ordres d'achat et de vente.

**Interconnexions.** Chaque liaison entre deux zones est décrite par une capacité disponible de transfert (ATC) par heure et par direction, telle que calculée selon le Code d'exploitation (ATC = NTC moins capacité déjà allouée). Un coefficient de pertes optionnel s'applique aux transferts.

**Participants.** Identifiant unique, zone(s) de localisation, limite de trading (pour la validation), portefeuille d'ordres.

**Ordres horaires.** Un ordre horaire porte, pour une heure, une quantité en MW et un prix limite. Une courbe d'un participant est un ensemble d'ordres horaires ; le moteur les traite comme des marches (ordres en escalier, acceptés partiellement ou totalement au prorata). L'interpolation linéaire entre points de prix, utilisée dans certains marchés européens, est prévue en option et désactivée par défaut, le Code ne la mentionnant pas.

**Ordres en bloc.** Un bloc porte un prix limite unique, un ratio minimal d'acceptation (MAR) dans $]0,1]$, et un profil de quantités sur des heures consécutives. Il est accepté à un ratio $r \in \{0\} \cup [\text{MAR}, 1]$, identique pour toutes ses heures, et ne peut pas être accepté en dessous de son MAR (MC 13.1.2.1 b).

**Blocs liés.** Un bloc enfant ne peut être accepté que si son bloc parent est exécuté (MC 13.1.2.1 c). Un arbre de blocs est admis, les blocs sans enfant étant des feuilles.

**Groupes exclusifs.** Ensemble de blocs dont la somme des ratios d'acceptation ne dépasse pas 1 ; avec des MAR égaux à 1, au plus un bloc du groupe est accepté (MC 13.1.2.1 d).

## 3.2 Ce que le moteur ne fait pas (version 0.1)

Il ne gère pas le marché OTC ni les enchères explicites de PTR (Phase 1), ni la compensation financière (chambre de compensation, appels de marge), ni le règlement. Ces fonctions relèvent du SMO ; le moteur en fournit seulement les entrées (positions, prix) pour simulation. Il ne calcule pas les ATC : il les reçoit.

# 4. Formulation mathématique du clearing

## 4.1 Notations

- $Z$ : ensemble des zones ; $H = \{1,\dots,24\}$ : heures ; $L$ : ensemble des interconnexions orientées $(z \to z')$.
- $O_{z,h}$ : ordres horaires de la zone $z$ à l'heure $h$ ; pour un ordre $o$, quantité $q_o \geq 0$ (MW), prix limite $p_o$, sens $s_o = +1$ (achat) ou $-1$ (vente).
- $B_z$ : blocs de la zone $z$ ; pour un bloc $b$, prix limite $p_b$, ratio minimal $m_b$, profil $q_{b,h} \geq 0$ sur $H_b \subseteq H$, sens $s_b$.
- $\mathcal{P}$ : relations parent-enfant $(b_{\text{parent}}, b_{\text{enfant}})$ ; $\mathcal{E}$ : groupes exclusifs.
- $A_{\ell,h}$ : ATC de la liaison $\ell$ à l'heure $h$ ; $\lambda_\ell \in [0,1[$ : facteur de pertes.
- $\underline{p}, \overline{p}$ : bornes de prix fixées par l'ARREC (initialement 0 et 50 % du coût de l'énergie non servie).

## 4.2 Variables

- $x_o \in [0,1]$ : ratio d'acceptation de l'ordre horaire $o$.
- $r_b \in [0,1]$ et $u_b \in \{0,1\}$ : ratio et indicateur d'acceptation du bloc $b$, avec $m_b\,u_b \leq r_b \leq u_b$.
- $f_{\ell,h} \geq 0$ : flux sur la liaison orientée $\ell$ à l'heure $h$.

## 4.3 Contraintes

**Équilibre zonal par heure.** Pour tout $z$ et $h$, l'injection nette de la zone égale ses exportations nettes, pertes déduites :
$$
\sum_{o \in O_{z,h}} (-s_o)\, q_o\, x_o \;+\; \sum_{b \in B_z,\, h \in H_b} (-s_b)\, q_{b,h}\, r_b
\;=\; \sum_{\ell \in \text{out}(z)} f_{\ell,h} \;-\; \sum_{\ell \in \text{in}(z)} (1-\lambda_\ell)\, f_{\ell,h}.
$$

**Capacités.** $0 \leq f_{\ell,h} \leq A_{\ell,h}$ pour toute liaison orientée et toute heure (MC 16.1).

**Blocs liés.** $u_{\text{enfant}} \leq u_{\text{parent}}$ pour tout couple de $\mathcal{P}$.

**Groupes exclusifs.** $\sum_{b \in E} r_b \leq 1$ pour tout $E \in \mathcal{E}$.

## 4.4 Objectif

Maximisation du bien-être régional (MC 15.2.1, 15.3.4) :
$$
\max \;\; \sum_{h}\sum_{z}\sum_{o \in O_{z,h}} s_o\, p_o\, q_o\, x_o \;+\; \sum_{z}\sum_{b \in B_z} s_b\, p_b \sum_{h \in H_b} q_{b,h}\, r_b .
$$

## 4.5 Prix et conditions de cohérence

Les blocs étant fixés à leur valeur optimale ($u_b$ et $r_b$ figés), le problème restant est linéaire ; le prix de la zone $z$ à l'heure $h$, $\pi_{z,h}$, est la variable duale de l'équilibre zonal. Il satisfait :

- **Cohérence des ordres horaires** : un achat est accepté en totalité si $p_o > \pi_{z,h}$, rejeté si $p_o < \pi_{z,h}$, partiel possible à l'égalité ; symétrique pour les ventes.
- **Cohérence des blocs acceptés** : un bloc de vente accepté vérifie $\sum_h q_{b,h}\,\pi_{z,h} \geq p_b \sum_h q_{b,h}$ (il est « dans la monnaie » en moyenne pondérée), et symétriquement pour un bloc d'achat. Un bloc qui serait dans la monnaie mais rejeté (bloc paradoxalement rejeté) est admis ; un bloc accepté hors de la monnaie n'est pas admis. Ces conditions sont vérifiées après résolution ; si elles sont violées, le bloc fautif est contraint au rejet et le problème résolu à nouveau (itération de type « fixation de blocs »).
- **Congestion** : si $f_{\ell,h} = A_{\ell,h}$, les prix des deux zones peuvent différer ; la rente de congestion vaut $(\pi_{z',h} - \pi_{z,h})\, f_{\ell,h}$ et revient, selon le Code, au dispositif de règlement du SMO. Si la liaison n'est pas saturée et sans pertes, les prix sont égaux.
- **Bornes** : si $\pi_{z,h}$ sort de $[\underline{p}, \overline{p}]$, le prix est écrêté et l'événement signalé (MC 15.3.5).
- **Départage** : à volumes équivalents, priorité aux ordres au prix le plus favorable puis au prorata ; règle paramétrable en attendant la procédure « DAM Clearing Procedure » du SMO.

## 4.6 Algorithme

1. Validation des ordres (section 6) et construction du problème.
2. Résolution du MILP (blocs entiers) avec un solveur de programmation mixte : HiGHS ou SCIP (libres) par défaut, Gurobi ou CPLEX en option.
3. Fixation des décisions de blocs, résolution du LP, extraction des prix duaux.
4. Vérification des conditions de cohérence des blocs ; en cas de violation, ajout d'une contrainte de rejet et retour à l'étape 2 (nombre d'itérations borné, journalisé).
5. Écrêtage éventuel des prix, calcul des flux, rentes, volumes, positions.
6. Production des sorties et du rapport de cohérence.

Le moteur est déterministe : mêmes entrées, mêmes sorties, et journalise chaque itération pour l'audit. Objectif de performance : quinze zones, vingt-quatre heures, plusieurs milliers d'ordres horaires et quelques centaines de blocs en moins d'une minute sur un poste de travail.

# 5. Sorties

Pour chaque exécution, le moteur produit :

- **Prix** : $\pi_{z,h}$ par zone et par heure (MC 15.3.1 a), avec indicateur d'écrêtage.
- **Volumes** : ratio et quantité acceptés par ordre et par heure (MC 15.3.1 b, c), liste des blocs acceptés, rejetés et paradoxalement rejetés.
- **Flux** : $f_{\ell,h}$ par liaison, heure et direction, capacité allouée implicitement (MC 16.1.5), heures de saturation, rentes de congestion.
- **Positions** : quantités et montants nets par participant et par heure, obligations et créances agrégées (MC 15.4.3, 15.4.4).
- **Courbes agrégées** : offre et demande par zone et par heure, avec et sans échanges.
- **Indicateurs** : bien-être total et par zone, gains à l'échange par pays, écarts de prix, taux d'utilisation des interconnexions, indices de concentration par zone et par heure, part des ordres au plafond de prix (base pour MC 21 et MC 22).
- **Valorisation des déséquilibres** (optionnelle) : écart entre quantités validées et quantités programmées, multiplié par le prix DAM horaire (MC 18.1.1.4 b).

# 6. Interfaces et validation

**Import des ordres.** Fichier CSV ou JSON dont les champs reprennent le contenu minimal du Code (MC 13.1.3.1) : identifiant participant, type d'ordre, sens, quantité, prix, heures, zone ; pour les blocs, MAR, identifiant de parent, identifiant de groupe exclusif.

**Import des capacités.** Table ATC par liaison orientée et par heure ; facteurs de pertes par liaison.

**Paramètres.** Bornes de prix, définition des zones, options d'interpolation, règle de départage, solveur et limite de temps.

**Validation à l'import**, reproduisant MC 13.1.4 : rejet des ordres hors plage de prix (13.1.4.2), au-delà de la limite de trading du participant (13.1.4.3), dont la quantité d'export dépasse l'ATC sortant ou la quantité d'import l'ATC entrant (13.1.4.5), et contrôle des types et paramètres d'ordres (13.1.4.4). Chaque rejet produit un motif explicite, comme l'exige le Code. Les contrôles d'horaires de guichet (13.1.4.1) sont simulés par horodatage.

**Export.** Résultats au format tabulaire, rapport de synthèse, API programmatique (Python) pour l'enchaînement avec les couches de simulation fondamentale et de stratégie d'offre.

# 7. Modes d'usage

**Rejeu et audit.** À partir des résultats agrégés publiés par le SMO et des ATC, reconstituer les prix et vérifier la cohérence ; détecter les anomalies de clearing (MC 13.4.1.1 b prévoit le cas de résultats erronés). Utilisateurs : régulateurs, comité de surveillance, participants.

**Simulation fondamentale.** La couche 2 (modèle de parc et de demande de la région) génère des ordres synthétiques par zone : offres au coût variable des centrales par filière, demande inélastique par pays, blocs pour les centrales à coût de démarrage. Le moteur produit les prix attendus, les flux, les gains à l'échange, avec et sans les interconnexions en construction. Utilisateurs : WAPP, bailleurs, ministères.

**Stratégie d'offre.** Pour un participant donné (par exemple Senelec), le moteur évalue des variantes d'ordres (horaires ou blocs, prix, quantités import/export) contre un scénario de marché, et mesure recettes, coûts évités et risque de rejet paradoxal. Couplé à la couche 3 (dispatch, réserves, combustible), il donne la position optimale sur le pool. Utilisateurs : desks des utilities, producteurs indépendants, opérateurs de stockage.

**Surveillance.** Calcul systématique des indicateurs de la section 5 sur une série de journées ; alertes sur concentration, ordres au plafond, rétention de capacité. Utilisateurs : ARREC, régulateurs nationaux.

# 8. Tests et validation

**Cas unitaires.** Une zone sans blocs (équilibre offre-demande) ; deux zones sans congestion (prix unique) ; deux zones avec congestion (market splitting, rente) ; pertes ; bloc dans la monnaie accepté ; bloc paradoxalement rejeté ; bloc à MAR partiel ; blocs liés à trois niveaux ; groupe exclusif ; ordres au plafond et écrêtage ; validation des rejets à l'import.

**Cas de référence.** Reconstitution de journées publiques d'un marché couplé européen à partir de courbes agrégées publiées, pour vérifier que la logique de prix, de blocs et de congestion reproduit les résultats connus.

**Cas régionaux.** Journées de délestage documentées au Sénégal (par exemple la nuit du 6 au 7 septembre 2026, indisponibilité de 240 MW) simulées avec et sans importation par l'OMVG et l'OMVS, pour mesurer la valeur du couplage.

**Performance et robustesse.** Temps de résolution, stabilité des prix aux perturbations d'entrée, reproductibilité.

# 9. Architecture et propriété intellectuelle

Langage Python ; modélisation par une bibliothèque d'optimisation ouverte ; solveurs libres par défaut, commerciaux en option ; base de données relationnelle pour les référentiels (zones, liaisons, participants) et les séries ; interface programmatique et tableau de bord web. Le cœur du moteur est conçu pour être publié en source ouverte, afin d'être vérifiable par le régulateur et les participants ; les couches de simulation fondamentale, de stratégie d'offre et de surveillance constituent les modules à valeur ajoutée.

Le moteur est écrit à partir des spécifications publiques (REMC-WA, description publique de l'algorithme de couplage européen). Il ne réutilise aucun code ni document appartenant à un employeur passé ou présent de l'auteur.

# 10. Feuille de route et points ouverts

**Jalons.** Mois 1 : modèle d'ordres, validation, MILP mono-zone, cas unitaires. Mois 2 : multi-zones, ATC, pertes, prix duaux, cohérence des blocs, cas de référence. Mois 3 : interfaces, indicateurs, documentation, première simulation régionale à partir de données publiques (plan directeur WAPP, parcs nationaux), note de présentation.

**Points à confirmer avec le SMO et l'ARREC**, dès que les procédures opérationnelles (« DAM Procedure », « DAM Clearing Procedure ») seront publiées : découpage des zones de prix ; traitement des ordres horaires (marches ou interpolation) ; règle de départage ; traitement des blocs paradoxalement rejetés ; application des facteurs de pertes (aux offres, aux flux, ou aux deux) ; horaires d'ouverture et de fermeture du guichet ; valeur initiale du plafond de prix (coût de l'énergie non servie retenu) ; format de publication des résultats agrégés.

# Annexe A. Glossaire

- **ATC** : capacité disponible de transfert, part de la NTC restant allouable (Code d'exploitation).
- **Bloc paradoxalement rejeté** : bloc qui serait profitable aux prix de clearing mais que l'optimum global rejette ; admis. Un bloc accepté non profitable n'est pas admis.
- **ETS** : système de trading électronique du SMO.
- **MAR** : ratio minimal d'acceptation d'un bloc.
- **Market splitting** : formation de prix différents entre zones lorsqu'une liaison est saturée.
- **MTU** : unité de temps du marché, une heure.
- **PTR** : droit physique de transport, alloué par enchère explicite sur le marché OTC.
- **SMO** : opérateur système et de marché du Marché régional, rôle de l'ICC.

# Annexe B. Sources

- REMC-WA, Code régional du marché de l'électricité de l'Afrique de l'Ouest, ARREC, résolution 018/ERERA/25 ([ecowapp.org](https://www.ecowapp.org/sites/default/files/regional_electricity_market_code_of_west_africa.pdf)), articles cités : MC 2.3, 10.3, 13.1 à 13.5, 15.1 à 15.5, 16.1, 18.1, 21, 22.
- Description publique de l'algorithme Euphemia (NEMO Committee, Single Day-Ahead Coupling), pour la sémantique des ordres en bloc, liés et exclusifs.
- Banque mondiale, West Africa Regional Electricity Market Program (P505173) ; WAPP, lancement de l'ICC (novembre 2023).

# Addendum v0.2 (22 septembre 2026) : révisions issues de la confrontation à EUPHEMIA Public Description 2025

Voir `proposition_types_ordres_remc.md` pour le détail. Modifications apportées au moteur par rapport à la section 4 :

1. **Blocs liés, règles de famille (EPD-2025 §5.4.1).** Contrainte supplémentaire $r_{\text{enfant}} \le r_{\text{parent}}$ (règle 1). La cohérence d'un bloc accepté ne se juge plus bloc par bloc mais sur son **sous-arbre accepté** : $\sum_{b' \in \text{sous-arbre}(b)} s_{b'}\, r_{b'} \big(p_{b'} V_{b'} - \sum_h q_{b',h}\, \pi_{z,h}\big) \ge 0$. Une feuille doit donc être dans la monnaie (règle 4) ; un parent hors de la monnaie peut être accepté si ses enfants compensent (règle 3). Paramètre `linked_family_rule` (défaut vrai) ; à faux, lecture littérale du Code (cohérence bloc par bloc).
2. **Départage des ordres horaires à la monnaie au prorata** (`prorata_ties`) : ordres de même zone, heure, sens et prix, dont le volume accepté est redistribué au prorata des quantités ; c'est la règle de partage du délestage entre preneurs de prix (EPD-2025 §7.9.2) restreinte à une zone. Le partage entre zones d'un même ensemble non congestionné reste à faire.
3. **Départage des blocs identiques** (EPD-2025 §5.4.4) : horodatage de dernière modification croissant, puis hachage SHA-256 reproductible des paramètres. Champ `timestamp` ajouté aux ordres.
4. **Arrondi** (MC 13.1.3.2, EPD-2025 §8.1) : prix à deux décimales et volumes publiés en MW entiers, arrondi commercial *half-up* ; le ratio publié d'un bloc est recalculé après arrondi. Paramètre `round_volumes`.
5. **Rapport de cohérence** (EPD-2025 §8.2) : écart maximal par famille de contrainte (équilibre, MAR/liens/groupes, bornes, intégralité, ordres horaires paradoxaux, écart de prix sans congestion, blocs acceptés hors de la monnaie) et niveau OK / TECHNICAL / DECOUPLING selon deux seuils (`tol_technical`, `tol_decoupling`).
6. **Sorties** : bien-être de la première itération (avant rejets forcés) pour mesurer le coût de la cohérence ; demande preneuse de prix non servie par zone et heure ; surplus de famille des blocs acceptés.
7. **Fixation un bloc à la fois** (`force_one_at_a_time`, défaut vrai) : à chaque itération, seul le bloc accepté le plus incohérent est forcé au rejet ; les autres peuvent redevenir cohérents une fois celui-ci écarté. La perte de bien-être entre la première itération (optimum sans contrainte de cohérence) et la solution finale est publiée (`welfare_first`) : elle borne la sous-optimalité de la procédure gloutonne par rapport à un branchement complet.
