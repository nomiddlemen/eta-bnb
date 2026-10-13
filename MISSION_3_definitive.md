# Mission 3 — même passe, côté flamand, dans l'heure de Bruxelles

Reprise exacte de la mission 1, sur une autre population. Le pipeline, la clé et
les rubriques ne changent pas. Ne redécouvre pas les pièges : ils sont dans
`MISSION.md`, et surtout `Accept: application/x.jsonxbrl` sur le contenu d'un
dépôt, la liste nue rendue par `/references`, et l'interdiction de marquer comme
traitée une société dont l'appel n'a pas abouti.

## Le périmètre

Reconstruire l'extrait BCE avec les mêmes filtres que la première fois, sans en
ajouter ni en retirer : société active, personne morale (`TypeOfEnterprise = 2`),
et au moins un code NACE-BEL 2025 des sections B, C, D, E ou H — le test porte
sur **tous** les codes de la société, pas seulement le principal. Seuls les
codes postaux changent :

| Plage | Zone |
| --- | --- |
| 1500-1999 | Hal-Vilvorde |
| 2000-2599 | Anvers, Malines et sud de la province |
| 2800-2999 | Malines, Boom, Willebroek |
| 3000-3499 | Louvain et Brabant flamand est |
| 9000-9499 | Gand, Alost, Termonde, Audenarde |

Sont volontairement exclus Courtrai, Bruges, Ostende, Hasselt, Genk et Turnhout :
plus d'une heure de route de Bruxelles, et les repreneurs dirigeront
l'entreprise eux-mêmes.

Déjà couverts par la passe précédente, à ne pas refaire : 1000-1499 et
4000-7999.

## Ce qui ne change pas

- EBITDA = rubrique **9901 + 630**, recalculé sur le dépôt.
- Retenue si l'EBITDA tombe entre **300 000 et 1 500 000 €**.
- Mêmes colonnes de sortie que `retenues.csv`, y compris `administrateurs` et
  `actionnaires`.
- Même gestion de la reprise, même parallélisme à six appels, même reprise
  exponentielle sur 429.

## En plus, cette fois

Une correction tirée de l'analyse de la première passe. Elle vaut aussi pour la
Flandre.

**Les sociétés sans marge brute.** 423 des 2 282 retenues wallonnes ne
publient pas la rubrique 9900, parce qu'elles déposent en schéma abrégé. Toute
analyse d'intensité capitalistique construite sur la marge brute les élimine
mécaniquement, y compris de très bonnes cibles. Ajoute donc au fichier de sortie
le **total du bilan** et les rubriques **22, 23 et 22/27** pour toutes les
retenues, afin qu'on puisse calculer l'intensité sur le bilan quand la marge
brute manque.

## Livrable

Mêmes fichiers que la mission 1, préfixés `fl_` :
`fl_retenues.csv`, `fl_tout.csv`, `fl_sans_depot.txt`, `fl_journal.txt`.

Et un `fl_rapport.md` court : population de départ, nombre lues, nombre
retenues, répartition par division NACE, taux de sociétés sans dépôt, et
comparaison avec les chiffres wallons — 31 464 dans la population, 24 927 lues,
2 282 retenues. Si le rendement flamand s'écarte nettement, dis pourquoi.
