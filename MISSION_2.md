# Mission 2 — ancienneté réelle des dirigeants et contrôle du capital

Suite de la mission 1. Tu as produit `retenues.csv`. L'analyse qui en a été tirée
bute sur deux trous que la Centrale des bilans ne peut pas combler. Cette
mission les comble.

Entrée : `cibles_moniteur.csv`, 121 sociétés, colonnes
`bce;nom;commune;division;nace;forme;ebitda;etp;barriere;administrateurs_bnb`.

## Trou n° 1 — les dates de mandat de la BNB ne mesurent rien

Le dépôt de comptes donne `MandateDates.StartDate`, mais pour une SA c'est la
date du **dernier renouvellement**, pas de la première nomination : le mandat
d'administrateur de SA est renouvelé tous les six ans. Mesuré sur les 2 282
retenues : 4 % seulement des SA affichent un mandat antérieur à 2013, contre
21 % des SRL et 40 % des SPRL, et 716 SA portent une date de fin explicite.
Autrement dit, une SA dont le patron est en place depuis 1985 apparaît comme
nommée en 2023.

Or le critère qui décide d'approcher une société n'est pas financier, c'est
l'ancienneté du dirigeant et l'absence de relève. Il faut donc la vraie date.

**Ce qu'il faut produire, par société :**

- `premiere_nomination` — l'année de la première publication nommant le
  dirigeant actuel, tous mandats confondus, en remontant aussi loin que le
  Moniteur le permet.
- `anciennete_ans` — écart avec aujourd'hui.
- `releve` — `oui` si une personne portant le même nom de famille, ou une
  personne de moins de 45 ans, a été nommée entre 2018 et aujourd'hui ;
  `non` sinon. C'est le signal « transmission déjà organisée », qui fait passer
  une cible de GARDER à SURVEILLER.
- `derniere_modification_statuts` — date de la dernière publication d'acte
  modifiant les statuts, utile pour repérer une restructuration récente.

**Source** : le Moniteur belge, annexes des personnes morales, sur
`ejustice.just.fgov.be`. La recherche se fait par numéro d'entreprise et rend la
liste des publications avec leur date et un PDF. Les actes utiles portent les
mentions « nomination », « démission », « administrateur », « gérant »,
« représentant permanent ». Trouve toi-même le bon point d'entrée et la bonne
façon d'interroger : c'est un site public, pas d'API documentée, et il faudra
probablement lire les PDF.

**Vérifie ta méthode sur deux cas connus avant de lancer les 121 :**

- `0447639261` Werkhuizen Haemers — la BNB donne Caroline Haemers et AVEM
  CONSULT BV nommées le 10 juin 2024. La question est de savoir depuis quand la
  famille Haemers dirige réellement, et qui dirigeait avant 2024.
- `0408287450` Dupont-Drion — administrateur WINAVI SRL représentée par Hervé
  Dupont. Même question.

Si ta méthode rend 2024 pour Haemers, elle ne sert à rien : recommence.

## Trou n° 2 — l'actionnariat est inconnu pour 86 % des sociétés

Le bloc `Shareholders` du dépôt n'est rempli que par 312 sociétés sur 2 282, la
déclaration étant facultative. Pour toutes les autres on ignore si un fonds, un
groupe étranger ou un invest public régional est au capital — et c'est ce qui a
déjà disqualifié deux cibles : l'une détenue à 51 % par un holding
luxembourgeois, l'autre avec un invest public wallon au conseil jusqu'en 2031.

**Ce qu'il faut produire, par société :**

- `actionnaires` — qui détient, et à quel pourcentage si l'information existe.
- `type_controle` — `personne physique`, `famille`, `holding patrimonial`,
  `groupe industriel`, `fonds`, `invest public`, ou `inconnu`.
- `societe_mere` — s'il y en a une, avec son pays.

**Sources possibles**, dans l'ordre : les actes publiés au Moniteur lors des
constitutions et des cessions de parts ; les mandats croisés, c'est-à-dire les
personnes morales administratrices déjà visibles dans la colonne
`administrateurs_bnb`, qu'on peut remonter par leur propre numéro BCE ; le
registre UBO si tu y as accès ; Pappers Belgique en dernier recours, qui donne
les pourcentages mais consomme des crédits payants — ne l'utilise que sur les
sociétés où les autres voies ont échoué, et dis combien d'appels tu as faits.

## Ce qui disqualifie une cible

À signaler explicitement dans une colonne `verdict` :

- contrôle par un fonds, un industriel étranger ou un invest public → `ECARTER`
- relève familiale ou managériale nommée entre 2018 et aujourd'hui →
  `SURVEILLER`
- dirigeant en place depuis dix à vingt-cinq ans, sans relève identifiée, âgé
  d'environ 58 à 70 ans → `GARDER`
- information introuvable → `A VERIFIER`, en disant ce qui manque

## Livrable

`moniteur.csv`, une ligne par société d'entrée, colonnes :

```
bce;nom;premiere_nomination;anciennete_ans;dirigeant_principal;releve;derniere_modification_statuts;actionnaires;type_controle;societe_mere;verdict;sources
```

`sources` doit contenir, pour chaque information, la référence de la publication
ou l'URL d'où elle vient. Une donnée sans source ne vaut rien ici : deux cibles
ont déjà été perdues parce qu'une fiche d'annuaire disait autre chose que les
actes.

Et un `rapport.md` court : combien de sociétés documentées, combien par verdict,
ce que le Moniteur ne permet pas de savoir, et le temps qu'il a fallu. Si une
partie des 121 est hors de portée, dis laquelle et pourquoi plutôt que de
remplir des colonnes au jugé.
