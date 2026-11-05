# Mission 4 — métiers à ligne de production hors sections industrielles

Même pipeline que les missions 1 et 3 (`bnb.py`, 6 appels parallèles, backoff exponentiel), même filtre
BCE (société active, personne morale), test sur **tous** les codes NACE de la société. Zones : Bruxelles
et Wallonie (1000-1499, 4000-7999) et Flandre à 40 minutes (1500-1999, 2800-2899, 3000-3220, 9000-9190,
9200-9280, 9300-9420). Extraction du 05/11/2026, 09:01 → 17:16 UTC, 4 passes, aucun 429, aucune erreur
restante.

**Plancher EBITDA : 150 000 €** (décision prise avant le lancement). `mx_retenues.csv` garde les
sociétés entre 150 k€ et 1,5 M€ ; la colonne `bande_stricte` vaut `oui` pour celles ≥ 300 k€. La colonne
`classes` donne la ou les classes ciblées de chaque société. Total du bilan, 22, 23 et 22/27 inclus.

Fichiers : `mx_retenues.csv`, `mx_tout.csv`, `mx_sans_depot.txt`, `mx_journal.txt` (+ `mx_resume.md`,
`mx_anomalies.csv`, `mx_depot_ancien.csv`). Population : `data/mx_population.csv.gz`.

## Les codes : MISSION_4.md est en numérotation 2008

La BCE code ses sociétés en **NACE-BEL 2025**. Vérifié dans `code.csv` (`data/nace_classes.csv`), cinq
codes de la mission ont changé, dont un qui désigne désormais tout autre chose :

| Mission (2008) | Retenu (2025) | Libellé officiel 2025 |
| --- | --- | --- |
| 01.63 + 01.64 | 01.63 | Traitement primaire des récoltes et traitement des semences |
| 46.71 | **46.81** | Commerce de gros de combustibles… (46.71 = véhicules automobiles en 2025) |
| 56.29 | **56.22** | Service contractuel de restauration et autres services de restauration |
| 81.23 + 81.29 | 81.23 | Autres activités de nettoyage |
| 82.19 | **82.10** | Activités de service de bureau et de soutien administratif |
| 96.01 | **96.10** | Blanchisserie-teinturerie |

Les 12 sociétés encore codées uniquement en 2008 ont été prises avec les codes 2008 de la mission et
comptées dans la classe 2025 correspondante.

## Chiffres

| | |
| --- | ---: |
| Population | 47 085 (Bruxelles-Wallonie 29 314, Flandre 17 771) |
| Lues (dépôt exploitable) | 36 585 (77,7 %) |
| Sans dépôt | 9 787 (20,8 %) — dernier dépôt avant 2023 : 713 |
| Retenues EBITDA 150 k€ – 1,5 M€ | **6 589** (Bruxelles-Wallonie 3 978, Flandre 2 611) |
| dont EBITDA ≥ 300 k€ (`bande_stricte = oui`) | **3 188** |
| Retenues avec machines (rubrique 23) > 150 k€ | **797** |

Descendre à 150 k€ a doublé le fichier (6 589 contre 3 188), comme le prévoyait la mission.

## Par classe

Une société peut relever de plusieurs classes (3 179 dans la population) : les colonnes ne
s'additionnent pas aux totaux.

| Classe | Population | Lues | Retenues ≥ 150 k | dont ≥ 300 k | **Retenues, machines > 150 k€** | Part | Lues, machines > 150 k€ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 01.63 Traitement des récoltes / semences | 200 | 129 | 38 | 20 | **20** | 53 % | 34 |
| 03.21 Aquaculture en mer | 19 | 13 | 0 | 0 | 0 | – | 2 |
| 03.22 Aquaculture en eau douce | 82 | 66 | 8 | 5 | 1 | 12 % | 4 |
| 46.21 Gros céréales, semences, aliments animaux | 843 | 717 | 243 | 137 | **79** | 33 % | 135 |
| 46.81 Gros combustibles | 550 | 470 | 145 | 92 | **27** | 19 % | 63 |
| 56.22 Restauration contractuelle (cuisines centrales) | 1 989 | 1 343 | 120 | 48 | **28** | 23 % | 67 |
| 68.20 Location immobilière | 22 195 | 18 225 | 4 297 | 2 174 | **434** | 10 % | 876 |
| 71.20 Contrôle et analyses techniques | 2 597 | 2 034 | 287 | 149 | **59** | 21 % | 118 |
| 81.22 Nettoyage industriel | 7 049 | 5 237 | 434 | 163 | **47** | 11 % | 82 |
| 81.23 Autres nettoyages (cuves, désinfection, dératisation) | 2 420 | 1 693 | 167 | 73 | **40** | 24 % | 64 |
| 82.10 Services de bureau (façonnage, routage) | 11 254 | 8 205 | 1 020 | 406 | **68** | 7 % | 145 |
| 82.92 Conditionnement à façon | 373 | 281 | 90 | 56 | **30** | 33 % | 50 |
| 96.10 Blanchisserie-teinturerie | 834 | 678 | 71 | 24 | **22** | 31 % | 49 |

## Ce que dit la colonne machines

- **Classes qui méritent qu'on y revienne** — un tiers ou plus des retenues ont un vrai outil au bilan :
  **01.63** (53 %), **46.21** (33 %, 79 sociétés), **82.92** (33 %), **96.10** (31 %). Viennent
  ensuite 81.23, 56.22 et 71.20 (21-24 %), petites en nombre mais réelles.
- **46.81** : 27 sociétés outillées (dépôts de stockage, lubrifiants, distribution de combustibles).
- **Aquaculture** : quasi vide (1 retenue outillée).

## Le bruit : 68.20 et 82.10

- **68.20** fait 47 % de la population et 65 % des retenues (4 297), dont **4 086 n'ont que ce code** :
  le libellé couvre toute location d'immeubles, et seules 15 ont un nom évoquant le stockage (storage,
  box, garde-meubles, opslag). Seules 10 % ont des machines > 150 k€. À filtrer par mots-clés ou à écarter.
- **82.10** a absorbé en 2025 tout le « soutien de bureau » : 849 retenues n'ont que ce code, et
  seules 7 % sont outillées. Les façonniers et routeurs y sont minoritaires.

Hors sociétés relevant seulement de 68.20 et/ou 82.10, il reste **1 493 retenues**, dont **327** avec machines > 150 k€.

## Les plus outillées hors 68.20 / 82.10 seuls

| BCE | Nom | Classes | Commune | EBITDA | Machines (23) |
| --- | --- | --- | --- | ---: | ---: |
| 1011734051 | MAINVAULT | 71.20 | Verviers | 1 460 517 | 13 556 264 |
| 0421493902 | FUCHS LUBRICANTS BENELUX | 46.81 | Beersel | 608 391 | 12 626 709 |
| 0807530245 | ALIA 2 | 46.21 | Floreffe | 1 073 016 | 5 092 847 |
| 0895688496 | LEVAN OBAIX | 01.63, 46.21, 68.20, 71.20 | Pont-à-Celles | 859 541 | 3 490 347 |
| 0680607131 | HPP BELGIUM | 82.92 | Binche | 1 291 845 | 3 318 892 |
| 0631910755 | LIEGE TANK STORAGE | 46.81 | Liège | 1 432 691 | 3 280 231 |
| 0452688706 | BELGOMALT | 46.21 | Gembloux | 639 623 | 3 279 666 |
| 0407713665 | Le Saupont | 82.92, 96.10 | Bertrix | 1 191 790 | 3 272 635 |
| 0639953144 | Associated Beverage Solutions | 82.92 | Courcelles | 1 421 778 | 3 268 676 |
| 0474739477 | C.E.T.T. P. MONSEU | 82.92 | Rochefort | 305 664 | 2 894 157 |

## Incident

Le passage de la passe 2 à la passe 3 a échoué sur une erreur HTTP 500 de l'API GitHub. L'état était
commité, rien n'a été perdu ; la passe a été relancée à la main et l'enchaînement retente désormais
cinq fois (PR #22).
