# Mission 4 — les métiers à ligne de production hors sections industrielles

Même pipeline que les missions 1 et 3, même clé, mêmes rubriques, mêmes pièges —
ils sont dans `MISSION.md`, et surtout `Accept: application/x.jsonxbrl` sur le
contenu d'un dépôt, la liste nue rendue par `/references`, et l'interdiction de
marquer comme traitée une société dont l'appel n'a pas abouti.

Ce qui change : la population.

## Pourquoi

Les passes précédentes ont couvert les sections B, C, D, E et H — extraction,
manufacture, énergie, eau et déchets, transport. Le criblage a donc vu toute
l'industrie au sens de la nomenclature, et rien d'autre.

Or plusieurs métiers ont une vraie ligne de production, un outil au bilan et du
volume facturé à la tonne ou à l'unité, tout en étant classés ailleurs : une
blanchisserie industrielle est une usine, une cuisine centrale aussi, un
conditionneur à façon également. Ils sont restés invisibles.

## Le périmètre

Mêmes filtres que précédemment — société active, personne morale
(`TypeOfEnterprise = 2`) — mais sur une **liste de classes** au lieu des sections
B/C/D/E/H.

La règle de sélection ne change pas : on retient une société dès qu'**au moins un
de ses codes NACE-BEL 2025**, principal ou secondaire, figure dans la liste
ci-dessous. Le test porte sur tous les codes, jamais sur le seul principal — sur
la passe wallonne, 291 des 2 282 retenues étaient entrées par un code secondaire.

Les libellés officiels sont dans `code.csv` du zip de la BCE, il n'y a rien à
deviner.

| Code | Libellé | Ce qu'on y cherche |
| --- | --- | --- |
| 01.63 | Traitement primaire des récoltes | Triage, séchage, conditionnement de pommes de terre et légumes |
| 01.64 | Traitement des semences | Triage, enrobage, sous agrément |
| 03.21 / 03.22 | Aquaculture | Installations d'élevage |
| 46.21 | Commerce de gros de céréales | Silos, séchoirs, manutention |
| 46.71 | Commerce de gros de combustibles | Dépôts, cuves, rétention |
| 56.29 | Autres services de restauration | **Cuisines centrales** — liaison froide ou chaude, agrément AFSCA |
| 68.20 | Location de biens immobiliers | Self-storage et parcs de boxes |
| 71.20 | Essais et analyses techniques | Laboratoires accrédités BELAC |
| 81.22 | Nettoyage industriel et autres bâtiments | Intervention technique sous agrément |
| 81.23 | Autres activités de nettoyage | Cuves, citernes, stérilisation, décontamination |
| 81.29 | Désinfection, dératisation | Contrats récurrents, agréments biocides |
| 82.19 | Façonnage et routage de documents | Lignes inkjet, mise sous pli |
| 82.92 | Conditionnement à façon | Co-packing sous cahier des charges |
| 96.01 | Blanchisserie et nettoyage de textiles | Blanchisserie industrielle, tunnels, calandres |

## Les codes postaux

**Bruxelles et toute la Wallonie** — 1000-1499 et 4000-7999. Périmètre inchangé
par rapport à la mission 1.

**Flandre, dans les quarante minutes de Bruxelles** — le critère s'est resserré
depuis la mission 3, qui prenait une heure :

| Plage | Zone |
| --- | --- |
| 1500-1999 | Hal-Vilvorde |
| 2800-2899 | Malines, Willebroek, Boom, Rumst |
| 3000-3220 | Louvain et Brabant flamand ouest |
| 9000-9190 | Gand et son agglomération |
| 9200-9280 | Termonde, Lebbeke, Zele |
| 9300-9420 | Alost, Ninove, Erpe-Mere, Haaltert |

**Anvers sort entièrement** : les plages 2000-2599 et 2900-2999 ne sont pas
reprises, la province est à plus de quarante minutes. Ne sont pas reprises non
plus Tienen, Diest et Aarschot, au-delà de 3220, ni Audenarde et Zottegem.

## Ce qui ne change pas

- EBITDA = rubrique **9901 + 630**, recalculé sur le dépôt.
- Retenue si l'EBITDA tombe entre **300 000 et 1 500 000 €**.
- Mêmes colonnes de sortie que `retenues.csv`, plus le total du bilan et les
  rubriques 22, 23 et 22/27, comme en mission 3.
- Même reprise, même parallélisme à six appels, même backoff exponentiel.

## Livrable

`mx_retenues.csv`, `mx_tout.csv`, `mx_sans_depot.txt`, `mx_journal.txt`.

Et un `mx_rapport.md` court : population de départ par classe NACE, nombre lues,
nombre retenues, et pour chaque classe le nombre de sociétés qui ont des
machines au-dessus de 150 k€ à la rubrique 23. C'est ce dernier chiffre qui dira
lesquelles de ces quinze classes méritent qu'on y revienne.

## Question ouverte, à trancher avant de lancer

Le plancher de 300 000 € porte sur l'EBITDA **comptable**. Dans une société de
ce gabarit, la rémunération du dirigeant, le loyer versé à une société
patrimoniale liée et les véhicules pèsent souvent 150 à 250 k€ : une société qui
affiche 220 k€ est donc fréquemment une cible à 450 k€ une fois retraitée, et
elle n'est jamais écrite dans le fichier.

Descendre le plancher à **150 000 €** doublerait probablement la population
exploitable, au prix d'un fichier plus bruité. Décision à prendre avant le
lancement, pas après.
