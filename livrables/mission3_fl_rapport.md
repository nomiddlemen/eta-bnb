# Mission 3 — Flandre (rayon d'une heure de Bruxelles)

Même pipeline que la mission 1 (`bnb.py`, 6 appels parallèles, backoff exponentiel sur 429/5xx), même
filtre BCE, codes postaux 1500-1999, 2000-2599, 2800-2999, 3000-3499 et 9000-9499. Extraction du
13/10/2026, 08:33 → 14:57 UTC, 4 passes. Aucun 429 ni 5xx, aucune erreur restante.

Fichiers : `fl_retenues.csv`, `fl_tout.csv`, `fl_sans_depot.txt`, `fl_journal.txt` (+ `fl_resume.md`,
`fl_anomalies.csv`, `fl_depot_ancien.csv`). `fl_retenues.csv` contient en plus le total du bilan et les
rubriques 22/27 (`immo_corp`), 22 (`terrains`) et 23 (`machines`).

## Chiffres

| | Flandre | Wallonie + Bruxelles |
| --- | ---: | ---: |
| Population (B, C, D, E, H, actives, personnes morales) | 36 100 | 31 464 |
| Lues (dépôt exploitable) | 27 437 (76,0 %) | 24 927 (79,2 %) |
| Sans dépôt exploitable | 7 960 (22,0 %) | 5 546 (17,6 %) |
| Dernier dépôt avant 2023 | 703 | 991 |
| Retenues (EBITDA 300 k€ – 1,5 M€) | **3 007** | **2 282** |
| Rendement retenues / lues | 11,0 % | 9,2 % |
| dont sans marge brute (rubrique 9900 absente, schéma abrégé) | 610 | 423 |

## Retenues par division NACE (principales)

| Division | Retenues | Lues | Population |
| --- | ---: | ---: | ---: |
| 49 Transport terrestre | 516 | 5 273 | 7 151 |
| 52 Entreposage, services de transport | 370 | 2 297 | 2 903 |
| 25 Produits métalliques | 271 | 2 012 | 2 553 |
| 10 Alimentaire | 238 | 1 995 | 2 614 |
| 46 Commerce de gros* | 201 | 1 339 | 1 669 |
| 33 Réparation, installation de machines | 133 | 1 748 | 2 392 |
| 35 Énergie | 129 | 495 | 622 |
| 43 Travaux de construction* | 124 | 2 446 | 3 167 |
| 28 Machines | 108 | 617 | 712 |
| 38 Déchets, récupération | 98 | 365 | 449 |
| autres (26 divisions) | 819 | 8 850 | 11 868 |

\* Division du code **principal** ; ces sociétés ont toutes au moins un code secondaire en B, C, D, E
ou H (le filtre porte sur tous les codes, comme en mission 1). Tableau complet : `fl_resume.md`.

## Sans dépôt : 22 % contre 17,6 %

Même cause qu'en Wallonie — absence réelle de dépôt, pas de limitation (0 429 ; les passes de
re-tentative n'en ont récupéré qu'un) :

- **Créations récentes** : 3 194 des 7 960 créées en 2025-2026, premier exercice pas encore clos
  (l'essentiel des 3 109 SRL sans dépôt).
- **Formes qui ne déposent pas à la BNB** : 2 155 en forme 612, 1 001 en SNC (011), 564 en 003,
  223 ASBL. La forme 612 pèse beaucoup plus en Flandre (2 155 contre 626) : c'est la principale
  raison de l'écart de couverture. Le transport (49) concentre 1 673 des sans-dépôt.

## Pourquoi le rendement flamand est plus élevé

3 007 retenues pour 27 437 lues (11,0 %) contre 9,2 % en Wallonie. Ce n'est **pas** un effet de
composition sectorielle : en appliquant aux sociétés flamandes lues les taux wallons division par
division, on attendrait ≈ 2 100 retenues. L'écart vient de la taille : en Flandre, moins de sociétés
lues sous 300 k€ d'EBITDA (84,3 % contre 87,2 %) et plus au-dessus de 1,5 M€ (4,7 % contre 3,6 %) —
le tissu industriel flamand de cette zone (Anvers, Gand, Malines, Louvain, périphérie bruxelloise) est
plus dense en PME moyennes, notamment en logistique portuaire (52) et en transport (49).

## Dix plus gros EBITDA retenus

| BCE | Nom | Div. | Commune | EBITDA | ETP |
| --- | --- | --- | --- | ---: | ---: |
| 0462747804 | INOVIM BELGIUM | 38 | Aalst | 1 498 985 | 106,3 |
| 0553802001 | Avanos Medical Belgium | 46 | Zaventem | 1 498 508 | 57,1 |
| 0474862510 | P.W.T. | 49 | Laakdal | 1 493 438 | 47,6 |
| 0463430960 | EURO TAP RENT | 28 | Sint-Niklaas | 1 492 551 | 9,9 |
| 0464434515 | Trans JP Martens | 49 | Ternat | 1 492 339 | 41 |
| 0422394319 | Paul Cool en Kinderen | 10 | Dendermonde | 1 489 771 | 15,6 |
| 0865566038 | RAIL SERVICE NET | 33 | Antwerpen | 1 486 516 | 45,2 |
| 0465720853 | WESTFALEN | 46 | Aalst | 1 484 833 | 20,3 |
| 0443804001 | MOKAFINA | 10 | Wijnegem | 1 484 227 | 14,8 |
| 0412801613 | POLYPANE GLASINDUSTRIE | 23 | Sint-Niklaas | 1 480 306 | 143,7 |
