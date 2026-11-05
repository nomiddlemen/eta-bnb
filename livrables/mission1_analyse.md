# Analyse finale — extraction BNB (9 octobre 2026)

## Résultat

| | Sociétés | Part |
| --- | ---: | ---: |
| Population (BCE, extrait du 11/09/2026) | 31 464 | 100 % |
| Lues (dépôt exploitable) | 24 927 | 79,2 % |
| Sans dépôt (3 passes) | 5 546 | 17,6 % |
| Ne déposent plus (dernier exercice ≤ 2022) | 991 | 3,1 % |
| **Retenues (EBITDA 300 k€ – 1,5 M€)** | **2 282** | |
| dont bande stricte 400 k€ – 1,2 M€ | 1 460 | |
| dont « propres » : ≥ 5 ETP, exercice récent, 630 présent | 1 541 | |
| dont propres **et** bande stricte | 1 031 | |

Fichiers : `retenues.csv` (22 colonnes du MD), `tout.csv`, `sans_depot.txt`, `depot_ancien.csv`,
`anomalies.csv`, `journal.txt`, `resume.md` (répartition NACE complète, top 10).

## 1. La question des « sans dépôt »

**Ce n'est pas du bridage.** Les 5 546 sociétés sans dépôt ont été interrogées dans trois passes
distinctes, dont deux à ~450 appels/min : **zéro récupérée, zéro HTTP 429**, aucune réponse vide
corrigée par relance, 17 erreurs 5xx sur ~65 000 appels, toutes reprises. 5 492 sur 5 546 répondent
404 sur `/references` : la BNB ne connaît aucun dépôt pour ces numéros. Les 95 % du premier essai
venaient des pièges 1 et 2 (415 sur `Accept`, `value` déballé), pas de l'API.

**Ce qui n'est pas couvert, et pourquoi :**

- **Sociétés trop jeunes** — 2 558 sans dépôt créées en 2025-2026 (taux sans dépôt : 62 % en 2025,
  100 % en 2026). Elles n'ont pas encore clôturé ou déposé un premier exercice.
- **Formes qui ne déposent pas à la BNB** — taux sans dépôt ≈ 95-100 % pour les SNC (011), SCS (012),
  entités étrangères (030), et les codes 612, 721, 003, 070, 411, 006 ; 79 % pour les ASBL (017),
  dont seules les grandes déposent à la Centrale.
- **Sociétés de capitaux établies** : SA (014) 2 %, SPRL (015) 1 %, SRL (610) 12 % — ce dernier
  chiffre est tiré par les créations récentes (la SRL est la forme par défaut depuis 2019).

Sur la cible des repreneurs (SA/SRL établies), la couverture est donc quasi complète.

## 2. Ce qui cloche dans les données

- **Micro-schéma sans 630** : 2 947 sociétés lues (37 retenues). L'EBITDA y vaut 9901 seul, donc
  sous-estimé ; 21 sociétés entre 200 et 300 k€ sans 630 pourraient en réalité être dans la bande
  (voir `anomalies.csv`).
- **9901 absent** : 110 sociétés, EBITDA non calculable.
- **EBITDA dans la bande sans personnel déclaré** : 334 retenues — holdings, sociétés patrimoniales,
  parcs solaires (ex. Macbeth 3, Green4You dans le top 10). À écarter pour une reprise industrielle.
- **Exercices anciens** : 631 lues ont un dernier exercice clos en 2023 ou avant (19 retenues).
- **Exercices ≠ 12 mois** : 1 551 (42 retenues) — EBITDA non annualisé.
- **Variation N/N-1 extrême (×5)** : 1 968 (134 retenues) — souvent un exercice N-1 quasi nul.
- **EBITDA > total du bilan** : 261 (16 retenues).
- **« Aberrants » > 1 Md€** : 3, mais réels (Electrabel, GSK Biologicals, UCB Biopharma).
- **ASBL dans la bande** : 25 retenues ont la forme 017 — non cessibles.
- **Actionnaires** : bloc rempli pour 312 retenues sur 2 282 seulement (déclaration facultative).
  Administrateurs : 2 239 sur 2 282. 57 retenues ont un administrateur en place depuis avant 2005.
- **Incident technique** : le journal de reprise de la passe principale a été tronqué puis
  reconstruit depuis les CSV complets. Les retenues sont complètes (22 colonnes) ; pour ~22 600
  sociétés hors bande, seules les colonnes de `tout.csv` sont disponibles (le schéma comptable
  n'est connu que pour ~10 000 sociétés).

## 3. Résumé

**24 927 sociétés lues, 2 282 retenues**, dont 1 031 « propres » dans la bande stricte.

Retenues par division (top 10, détail dans `resume.md`) :

| Div. | Activité | Retenues |
| --- | --- | ---: |
| 49 | Transport terrestre | 435 |
| 25 | Produits métalliques | 251 |
| 10 | Industries alimentaires | 231 |
| 52 | Entreposage, services auxiliaires des transports | 203 |
| 33 | Réparation et installation de machines | 147 |
| 35 | Électricité, gaz | 107 |
| 23 | Produits minéraux non métalliques | 96 |
| 28 | Machines et équipements | 92 |
| 38 | Collecte et traitement des déchets | 77 |
| 16 | Travail du bois | 75 |

Dix plus gros EBITDA parmi les retenues (tous proches du plafond de 1,5 M€) :

| BCE | Nom | Div. | Commune | EBITDA | ETP |
| --- | --- | --- | --- | ---: | ---: |
| 0719788795 | Macbeth 3 | 52 | Bruxelles | 1 499 551 | — |
| 0429996941 | COENE | 16 | Couvin | 1 498 165 | 18,1 |
| 0778652157 | Green4You | 35 | Saint-Josse-ten-Noode | 1 496 060 | — |
| 0822658186 | Société Royale de Philanthropie | 35 | Bruxelles | 1 495 219 | 87,9 |
| 0478994809 | Rail Europe | 16 | Couvin | 1 494 562 | 22,9 |
| 0440492341 | Société Tournaisienne de Transport | 49 | La Louvière | 1 492 925 | 49,7 |
| 0477324330 | ALDO | 25 | Ath | 1 492 896 | 39,6 |
| 0447090618 | Brasserie St-Feuillien | 11 | Le Rœulx | 1 492 131 | 34,3 |
| 0419149074 | Terminal Athus | 52 | Aubange | 1 491 877 | 50,8 |
| 0401496856 | Pullman Bus | 49 | Chaumont-Gistoux | 1 491 562 | 46,3 |

Taille des retenues : ETP médian 12,6 ; 389 sous 5 ETP, 918 entre 5 et 20, 455 entre 20 et 50,
186 au-delà.

**Côté API** : aucun 429 sur toute la durée, débit jusqu'à ~450 appels/min avec 6 appels
parallèles ; aucun en-tête de quota renvoyé par la BNB.
