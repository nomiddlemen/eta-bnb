# Mission — extraction des comptes annuels belges (Centrale des bilans)

Tu reprends un travail en cours. Lis tout avant de lancer quoi que ce soit : les
pièges décrits plus bas ont déjà coûté une journée.

## Le contexte

Deux repreneurs cherchent à racheter une PME industrielle belge pour la diriger
eux-mêmes. Bande cible : EBITDA de 400 k€ à 1,2 M€, pas de critère d'effectif.
Il faut passer au crible les 32 290 sociétés industrielles actives de Wallonie
et de Bruxelles et en sortir celles qui tombent dans la bande, avec de quoi
juger leur outil de production et leur cédabilité.

## L'objectif

Produire `state/retenues.csv` : une ligne par société dont l'EBITDA réel se situe
entre 300 000 € et 1 500 000 € (fourchette large volontaire, pour ne pas perdre
les cas limites), avec les colonnes listées plus bas.

## La source

API de la Centrale des bilans de la Banque nationale de Belgique.

- Base : `https://ws.cbso.nbb.be`
- Liste des dépôts d'une société : `GET /authentic/legalEntity/{numeroBCE}/references`
  Le numéro BCE s'écrit en dix chiffres sans points : `0447639261`.
- Contenu d'un dépôt : `GET /authentic/deposit/{reference}/accountingData`
  ou directement l'URL `AccountingDataURL` rendue par l'appel précédent.

En-têtes obligatoires sur chaque appel :

```
NBB-CBSO-Subscription-Key: 76f1d56a54eb4d2c8538893b66fb1f10
X-Request-Id: <un UUID différent à chaque appel>
Accept: <voir ci-dessous>
```

La clé est celle du produit « NBB CBSO Web Services - Authentic Data », gratuit.
Elle peut être régénérée sur developer.cbso.nbb.be si besoin.

### Pièges déjà rencontrés, à ne pas redécouvrir

1. **`Accept` sur le contenu d'un dépôt** : `application/json` renvoie **415
   Unsupported Media Type**. Le seul format structuré qui fonctionne est
   `application/x.jsonxbrl`. `application/pdf` marche aussi mais ne sert à rien
   ici. Sur `/references`, en revanche, `application/json` est correct.
2. **La réponse de `/references` est une liste nue**, pas un objet avec un champ
   `value`. Certains clients HTTP déballent le `value` automatiquement et on
   croit à tort que la liste est vide. Gérer les deux formes.
3. **Bridage silencieux.** Sous charge, l'API a renvoyé « aucun dépôt » pour des
   sociétés anonymes en pleine activité — c'est impossible, elles déposent
   chaque année. Prévoir une reprise exponentielle sur 429 et 5xx, limiter le
   parallélisme à six appels, et **ne jamais marquer comme traitée une société
   dont l'appel n'a pas abouti** : elle doit revenir au passage suivant.
4. **Reprise.** Le travail dure plusieurs heures. L'état doit être écrit au fur
   et à mesure sur disque et le programme doit pouvoir être tué et relancé sans
   rien reperdre.

## La population à traiter

`data/bce_industrie.csv.gz`, séparateur `;`, colonnes :

```
numero_bce;nom;code_postal;commune;nace_principal;tous_les_nace;division;forme;creation
```

32 290 lignes. Elle a été construite à partir de l'open data de la Banque-
Carrefour des Entreprises (`KboOpenData_*_Full.zip`, gratuit sur inscription) en
gardant : siège dans les codes postaux 1000-1499 et 4000-7999, société active,
personne morale (`TypeOfEnterprise = 2`), et au moins un code NACE-BEL 2025 des
sections B, C, D, E ou H — soit les divisions 05 à 09, 10 à 33, 35, 36 à 39 et
49 à 53. Si le fichier manque, il se régénère ainsi à partir de `address.csv`,
`activity.csv`, `enterprise.csv` et `denomination.csv` du zip de la BCE.

## Les calculs

Les rubriques sont celles du schéma comptable belge. Chaque rubrique du dépôt
existe en `Period = "N"` (exercice courant) et `"NM1"` (précédent).

| Grandeur | Calcul |
| --- | --- |
| **EBITDA** | rubrique **9901** (bénéfice d'exploitation) **+ 630** (amortissements) |
| Marge brute | 9900 |
| Total du bilan | 20/58 |
| Capitaux propres | 10/15 |
| Immobilisations corporelles | 22/27 |
| Terrains et constructions | 22 |
| Installations, machines, outillage | 23 |
| Dette financière | 170/174 + 43 |
| Trésorerie | 54/58 + 50/53 |
| Rémunérations | 62 |
| Effectif en ETP | 9087 |

Ne jamais reprendre un EBITDA calculé par un tiers : sur une société du panel,
un revendeur de données annonçait 685 k€ là où les comptes déposés donnent
334 k€.

Le dépôt contient aussi `Administrators` — personnes physiques et morales, avec
`MandateDates.StartDate` — et `Shareholders`. Ces deux blocs sont aussi
importants que les chiffres : ils disent si une succession est déjà organisée.

## Ce qu'il faut produire

`state/tout.csv` — une ligne par société lue :
`bce;nom;division;commune;exercice;ebitda;bilan`

`state/retenues.csv` — les sociétés dans la bande, colonnes :
`bce;nom;division;commune;nace;exercice;schema;ebitda;ebitda_n1;marge_brute;amortissements;bilan;immo_corp;terrains;machines;fonds_propres;dettes_fin;tresorerie;remunerations;etp;administrateurs;actionnaires`

`state/sans_depot.txt` — les numéros pour lesquels la BNB n'a rendu aucun dépôt
exploitable, à retenter au passage suivant.

`state/journal.txt` — une ligne par passage : nombre lues, retenues, sans dépôt,
erreurs, bridages.

## Comment le faire tourner

Le dépôt contient déjà `bnb.py` et un déclencheur GitHub Actions
(`.github/workflows/bnb.yml`) qui part toutes les six heures, travaille cinq
heures, commite l'état et laisse le passage suivant reprendre. Trois ou quatre
passages suffisent.

Variables : `NBB_KEY` (la clé ci-dessus), `TIME_BUDGET` en minutes,
`WORKERS` pour le parallélisme.

Si tu juges que `bnb.py` est perfectible, réécris-le — ce qui compte ce sont les
fichiers de sortie, pas le code.

## Ce qu'on attend de toi en plus de l'exécution

1. **Trancher la question des « sans dépôt ».** Au premier essai, 95 % des
   sociétés revenaient sans dépôt exploitable, dont des SA en activité. Après
   quelques passages avec reprise, dis si le taux redescend à quelque chose de
   crédible, ou si une part de la population n'est réellement pas couverte par
   le produit « Authentic Data » — et dans ce cas, laquelle et pourquoi.
2. **Signaler ce qui cloche dans les données** : exercices anciens, sociétés en
   schéma micro où 9901 ou 630 manquent, valeurs aberrantes.
3. **Un résumé en fin de course** : combien de sociétés lues, combien retenues,
   la répartition des retenues par division NACE, et les dix plus gros EBITDA.

Ne commente pas le code en français approximatif, écris-le comme tu veux. Le
livrable, ce sont les CSV et ton résumé.
