# Mission 2 — rapport

Livrable : `moniteur/moniteur.csv` (121 lignes, 12 colonnes). Données brutes et traçabilité :
`moniteur/data/<bce>/` (liste des actes, fiche BCE, OCR de chaque acte), dossier détaillé par
société : `moniteur/dossiers.md`. Code : `moniteur/fetch.py`, `analyse.py`, `finalise.py`.

## Méthode

1. **Moniteur belge** (`ejustice.just.fgov.be/cgi_tsv/list.pl?btw=<n°>`) : liste paginée de toutes
   les publications de la société ; chaque acte hors dépôt de comptes est téléchargé et passé à
   l'OCR (tesseract fra/nld/deu — les PDF sont des scans). 1 239 actes lus.
2. **Fiche BCE publique** (`kbopub`) : fonctions actuelles avec leur date de début, y compris les
   représentants permanents des administrateurs personnes morales. Chaque administrateur personne
   morale est remonté d'un niveau (sa fiche BCE, sa liste d'actes, l'OCR de sa constitution).
3. Pour chaque dirigeant actuel : premier acte qui le nomme (nom **et** prénom), en écartant sur
   les pages d'avant 2003 — qui regroupent plusieurs sociétés — les mentions rattachées à un
   autre numéro d'entreprise. Un acte de **renouvellement** ou un premier PDF précédé d'actes
   sans image donne une borne (« ≤2004 ») et non une date.
4. **Âge** : numéro de registre national (AA.MM.JJ-xxx-xx) ou « né le … » cité à côté du nom dans
   un acte, y compris dans la constitution de la société de management du dirigeant.
5. **Relève** : personne nommée depuis 2018 portant le nom d'un administrateur déjà en place, ou née
   il y a moins de 45 ans. Nouveau venu d'âge inconnu → « incertain ».

### Vérification sur les deux cas connus

- **Werkhuizen Haemers (0447639261)** — la BNB donne 2024 ; les actes montrent que c'est un
  *herbenoeming*. Caroline Haemers est administratrice au moins depuis 2004 (acte de
  renouvellement du 06/07/2004), avec Erna Verstraete, administratrice déléguée et présidente
  jusqu'en 2020 (à titre personnel, puis via la SCA Roland à partir de 2018). En 2003 Katrien
  Haemers est révoquée. Relève organisée en 2020 : Caroline Haemers devient administratrice
  déléguée et présidente, AVEM Consult (David Mulnard, même adresse que la famille) entre au
  conseil. Avant 2003 les seules pages disponibles (1998) concernent la société sœur
  *Vastgoed Haemers* : la méthode les écarte. Résultat : « ≤2004 », pas 2024.
- **Dupont-Drion (0408287450)** — Hervé Dupont (né le 10/10/1966, n° de registre national dans
  l'acte de 2009) est administrateur au moins depuis 1997, administrateur délégué depuis juin
  2000 (succède à Annie Coling ; avant : Pierre Dupont, démissionnaire en 1999, puis Olivier
  Dupont). Depuis 2012 il exerce via sa holding WINAVI. Ancienneté réelle ≥ 29 ans.

## Résultats

| Verdict | Sociétés |
| --- | ---: |
| GARDER | 8 |
| SURVEILLER | 21 |
| ECARTER | 6 |
| A VERIFIER | 86 |

**GARDER** (dirigeant en place 17 à 25 ans, 58-70 ans, pas de relève depuis 2018) :
EURECayphas, Delmar, IMM HM, Exelio, Centribel Recyclage, Seynave et Fils, Voyages et Autocars
Sambre et Meuse, Transport Lecaillié.

**ECARTER** : Eifeler Fleischvertrieb et Conserverie et Moutarderie Belge (Ostbelgieninvest,
invest public, au conseil), Micromega-Dynamics (administrateur allemand Wölfel Engineering),
deux intercommunales des eaux, Recymex (Tibi, Hygea et Veolia au conseil).

**A VERIFIER — ce qui manque** (une société peut cumuler plusieurs motifs) :

- âge du dirigeant introuvable dans les actes : 56 ;
- âge des nouveaux administrateurs nommés depuis 2018 : 27 (relève possible, non prouvée) ;
- ancienneté hors de la fourchette 10-25 ans : 31 (13 au-delà de 25 ans — souvent de bonnes
  cibles mais hors du critère tel qu'il est écrit — et 18 en dessous de 10 ans) ;
- actionnariat sans aucun indice : 25 ;
- Boulangerie Kempinaire : **administrateur provisoire désigné par le tribunal** depuis 2022.

Ancienneté : 61 dates sont des bornes (« ≤ année ») parce que la première nomination précède les
PDF en ligne ou que l'acte trouvé est un renouvellement. L'âge du dirigeant principal est connu
pour 47 sociétés sur 121.

## Ce que le Moniteur ne permet pas de savoir

- **Avant 1997** : les actes sont listés mais sans image en ligne ; on ne peut pas remonter plus
  loin (ex. constitution de Haemers en 1992).
- **L'actionnariat** : les cessions de parts et d'actions ne sont pas publiées. Seules la
  constitution et les augmentations de capital nomment des souscripteurs, à une date souvent
  ancienne. Le `type_controle` est donc **présumé** à partir des mandats (holding de management
  du dirigeant, mêmes noms de famille, invest public ou groupe au conseil) — sauf pour les
  écartées, où la présence au conseil suffit à la règle. Aucun pourcentage n'est publié.
- **L'âge** n'apparaît que si un acte cite le registre national ou la date de naissance — surtout
  dans les actes notariés récents.
- **Pappers Belgique** : non utilisé. Un seul appel a été tenté (Haemers) ; le compte n'avait plus
  de crédits, l'appel a été refusé et rien n'a été consommé. Avec des crédits, c'est la voie pour
  les 86 « A VERIFIER » (âge, UBO, pourcentages).
- **Registre UBO** : pas d'accès.

## Limites de l'automatisation

L'OCR des pages anciennes est imparfait et les pages d'avant 2003 mêlent plusieurs sociétés ; les
dates de ces pages sont signalées « à confirmer » dans `sources`. Les verdicts appliquent les
règles du MD à la lettre : un dirigeant en place depuis 27 ans à 66 ans tombe en « A VERIFIER
(ancienneté hors 10-25) » et non en GARDER.

## Temps

Collecte et OCR : environ 1 h de calcul sur GitHub Actions (4 machines en parallèle) ; méthode,
vérification des deux cas, analyse et relecture : environ 2 h, le 10 octobre 2026.
