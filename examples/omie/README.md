# Cas de référence européen : rejeu du marché day-ahead ibérique (OMIE)

OMIE, l'opérateur du marché ibérique (Espagne et Portugal, membre du couplage européen SDAC), publie chaque jour
sans compte ni licence :

- `curva_pbc_AAAAMMJJ.1` : les courbes agrégées d'offre et de demande, une ligne par marche, avec le pays
  (« MI » quand les deux pays sont couplés, « ES » ou « PT » en cas de market splitting), le sens (C achat, V vente),
  la puissance, le prix, le statut (« O » offert, « C » casé) et la typologie (« S » simple, « C01 » à « C04 »
  conditions complexes, « Imp/Exp FR/PT » échanges issus du couplage) ;
- `marginalpdbc_AAAAMMJJ.1` : les prix marginaux, Portugal puis Espagne.

Depuis le 1er octobre 2025, le pas de temps est le quart d'heure : 96 MTU par jour.

## Ce que fait le rejeu

`replay_omie.py DATE` télécharge les deux fichiers (dans `data/`, ignoré par git), construit pour chaque MTU et
chaque zone un marché à une période avec les marches comme ordres horaires, le fait clearer par `wapp_dam`, puis
compare prix et volumes aux valeurs officielles. Deux niveaux :

- **N1** : toutes les marches offertes, y compris celles des offres complexes, sans leurs conditions. L'écart
  mesure ce que pèsent les conditions complexes (revenu minimal, indivisibilité, gradient, arrêt programmé) et le
  couplage européen dans la formation du prix.
- **N2** : les marches complexes sont limitées à celles effectivement casées, c'est-à-dire que les décisions
  d'activation sont prises comme données ; il ne reste que le croisement des courbes, que le moteur doit
  reproduire.

Les échanges avec la France et entre l'Espagne et le Portugal sont déjà des ordres dans les courbes (preneurs de
prix), donc aucune liaison n'est modélisée. En N2, les seuls écarts restants sont ceux où le prix officiel est
strictement à l'intérieur de l'intervalle entre la dernière vente casée et le premier achat casé : le prix y est
indéterminé pour l'Ibérie seule et fixé par le couplage avec la France, que les fichiers OMIE ne décrivent pas.

## Résultats

| Journée | N1 : écart moyen / max (EUR/MWh) | N2 : prix exacts | N2 : écart moyen / max | N2 : volume moyen / max (MW) | Écarts N2 dans l'intervalle |
|---|---|---|---|---|---|
| 2026-01-20 (hiver) | 12,75 / 42,38 | 86 / 96 | 0,03 / 0,59 | 1,3 / 55,0 | 10 / 10 |
| 2026-06-10 (été) | 10,12 / 38,34 | 94 / 96 | 0,01 / 0,78 | 7,3 / 104,8 | 2 / 2 |
| 2026-09-15 (avec splitting ES/PT, 2 MTU) | 14,40 / 50,67 | 70 / 98 | 0,20 / 4,00 | 1,7 / 37,6 | 28 / 28 |

Environ 4 000 à 6 000 marches par MTU, 20 s par journée sur un ordinateur portable. Fichiers de résultats :
`results_AAAAMMJJ.csv` (prix moteur et officiel, écart, intervalle d'indétermination, volumes).

```bash
.venv/bin/python examples/omie/replay_omie.py 20260915
```

Source : OMIE, https://www.omie.es (rubrique « Datos de mercado », fichiers `curva_pbc` et `marginalpdbc`).
