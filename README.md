# IRIS Prospection cold emailing

Un outil de prospection B2B par email, multi-clients, sans abonnement à un service tiers.
Il cherche des entreprises sur des pages publiques, relève les adresses qui y figurent, écrit une courte
séquence par contact, l'envoie depuis la boîte du client à un rythme prudent, relève les réponses et tient
une page de suivi par client.

Seuls coûts : la clé API Claude (à l'usage) et, si le client n'en a pas, une boîte email.
La recherche de prospects tient dans le compte gratuit de ScrapeGraphAI, ou s'en passe.

## Ce qu'il fait, dans l'ordre

1. **Chercher.** À partir de pages de liste (annuaire, adhérents d'un réseau, exposants d'un salon) ou de
   sites déjà connus, il visite le site de chaque entreprise : accueil, contact, équipe, mentions légales.
2. **Retenir.** Une adresse n'est gardée que si elle est écrite sur la page. Jamais devinée, jamais construite.
   Les adresses grand public (gmail, orange...) sont écartées par défaut : elles peuvent être celles de particuliers.
3. **Écrire.** Trois messages courts par contact, en texte brut. Le modèle ne peut affirmer que ce qui figure
   dans la fiche du client ; tout chiffre absent de la fiche déclenche une relecture humaine.
4. **Faire valider** (mode `validation`) ou partir directement (mode `autonome`).
5. **Envoyer.** Du lundi au vendredi, aux heures de bureau, quelques messages par jour au début puis davantage
   chaque semaine, avec un écart irrégulier entre deux envois. Les relances partent dans le fil du premier message.
6. **Relever.** Une réponse arrête les relances et s'affiche dans la page de suivi. Un « stop » bloque l'adresse
   pour toujours. Une adresse invalide est retirée. Trop d'adresses invalides : tout se met en pause.

Il n'y a ni pixel d'ouverture ni lien tracé. C'est voulu : cela nuit à la délivrabilité et les taux
d'ouverture sont faux depuis des années. On compte les réponses.

## Où il tourne

Le moteur a besoin d'une machine qui peut joindre une boîte email (SMTP et IMAP). Deux façons gratuites :

**A. Un dépôt GitHub privé** (recommandé). Le fichier `.github/workflows/passage.yml` lance un passage toutes
les demi-heures en semaine et enregistre l'état dans le dépôt. Rien à laisser allumé.
- Créer un dépôt **privé** (il contient les coordonnées des prospects), y pousser ce dossier.
- Dans Settings > Secrets and variables > Actions, créer le secret `COLDMAIL_SECRETS` avec le contenu de
  `secrets.exemple.json` rempli.
- Un compte gratuit donne 2 000 minutes par mois sur un dépôt privé ; un passage dure environ une minute,
  soit environ 480 minutes par mois au rythme prévu.
- Limite à connaître : les conditions de GitHub réservent Actions aux usages liés au dépôt. Un petit volume
  passe inaperçu, mais ce n'est pas un hébergeur d'envoi. Si l'activité grossit, basculer sur B ou sur un
  petit serveur (quelques euros par mois).

**B. Votre ordinateur.** Installer Python, puis `pip install -r requirements.txt`, copier
`secrets.exemple.json` en `secrets.json`, et faire lancer `passage.bat` toutes les 30 minutes par le
Planificateur de tâches Windows. Gratuit, mais rien ne part quand l'ordinateur est éteint.

## Ouvrir un client

```
python -m moteur nouveau dupont
```
Remplir `clients/dupont/client.json` (modèle : `clients/exemple/client.json`), ajouter son mot de passe
aux secrets, puis :
```
python -m moteur tester-boite dupont      # la boîte accepte-t-elle la connexion ?
python -m moteur passage dupont --a-blanc # tout le parcours, les messages vont dans clients/dupont/sorties/
```
Quand les messages de `sorties/` conviennent, passer `"actif": true`.

Si l'adresse d'envoi du client n'est pas encore prête (domaine en cours d'achat), mettre `"envoi": false` :
la recherche et la rédaction tournent, le client valide ses messages dans son espace, et rien ne part.
Repasser à `true` le jour où la boîte est branchée : les messages validés partent alors au rythme prévu.

### La boîte d'envoi

| | Adresse du client sur son domaine | Compte Gmail créé pour lui |
|---|---|---|
| Sérieux perçu | celui de son entreprise | faible : une adresse @gmail.com en B2B |
| Délivrabilité | bonne si SPF, DKIM et DMARC sont en place | fragile, compte suspendu sans préavis en cas d'abus |
| Plafond réaliste | 30 à 50 par jour après montée en charge | 20 à 30 par jour |
| Réglage | `smtp`/`imap` de son hébergeur | `smtp.gmail.com` / `imap.gmail.com` |

Dans les deux cas : validation en deux étapes activée, puis un **mot de passe d'application** (jamais le mot
de passe principal). Pour Google Workspace et Gmail : compte Google > Sécurité > Mots de passe des applications,
et IMAP activé dans les réglages Gmail. Le mieux, pour ne pas exposer l'adresse principale du client : une
seconde adresse sur un domaine voisin du sien (`prenom@nom-entreprise.fr` pour `nomentreprise.fr`).


## Ajouter un nouveau client sans modifier le code

L'infrastructure est mutualisée. Pour un nouveau client, il n'y a pas de nouveau moteur à installer.

1. Créer sa fiche avec `python -m moteur nouveau <client-id>`.
2. Renseigner son offre, sa cible, son signataire et sa boîte dans `clients/<client-id>/client.json`.
3. Ajouter le mot de passe de sa boîte dans le secret GitHub Actions `COLDMAIL_MAIL_PASSWORDS`, sous forme de JSON :

```json
{
  "verifamende-flottes": "mot-de-passe-boite",
  "nouveau-client": "mot-de-passe-boite"
}
```

Ce coffre est secret et n'est jamais écrit dans le dépôt. Les anciens secrets individuels `COLDMAIL_PASSWORD_<CLIENT>` restent compatibles.

Avant tout envoi réel, laisser `"envoi": false`, vérifier la boîte, laisser IRIS trouver et rédiger quelques prospects, puis faire valider la qualité par le client.

### Ce que voit le client

Son espace de suivi explique désormais clairement :
- la cible travaillée ;
- le nom du signataire et la boîte utilisée ;
- le mode de validation ;
- la cadence et les créneaux d'envoi ;
- ce qu'IRIS a déjà fait (contacts trouvés, contactés, messages, réponses) ;
- les prochains messages : à qui, dans quelle entreprise, à quelle adresse, quelle étape, quand, et d'où vient le contact ;
- ce qui attend son accord ;
- les réponses reçues et le journal des actions.

L'objectif est qu'un client comprenne seul ce qui a été fait et ce qui va se passer ensuite.

## La page de suivi en direct

Même mécanique que les espaces IRIS : un site Cloudflare Pages gratuit, alimenté par ce dépôt.

- `site/espace.html` : l'espace « IRIS Prospection cold emailing », à la charte des espaces IRIS, commun à tous les clients. Adresse d'un client : `https://<votre-site>/e/<code>`.
  Le code (12 caractères, champ `code` de sa fiche) tient lieu de clé : ne le donner qu'au client.
- `functions/api/espace.js` : sert les données du client (`espaces/<code>.json`, réécrit par le moteur à chaque
  passage) et dépose ses clics dans `clients/<client>/decisions/`. Le moteur les applique au passage suivant.
- `site/console/` : votre console. Elle liste tous les clients, ceux qui attendent un accord en haut.

Depuis sa page, le client peut **valider**, **corriger** un message, écarter un contact, mettre en pause ou
reprendre. Rien d'autre : bloquer un domaine, effacer une personne ou changer la fiche restent au pilote.

Mise en place, une fois :
1. Cloudflare > Workers & Pages > créer un projet Pages relié à ce dépôt. Aucune commande de construction,
   dossier publié `site`.
2. Dans `wrangler.toml`, remplacer `compte/depot` par le nom du dépôt.
3. GitHub > Settings > Developer settings > Fine-grained tokens : un jeton limité à ce dépôt, droit
   « Contents » en lecture et écriture. Le poser dans Cloudflare comme secret `GITHUB_TOKEN`.
4. Poser un second secret `CLE_CONSOLE` : la clé de votre console, de votre choix, longue.

Les enregistrements du moteur et des clics portent le préfixe `[CF-Pages-Skip]` : le site n'est pas redéployé
à chaque passage. Il ne l'est que lorsque la page elle-même change (`python -m moteur site`, puis un envoi normal).

Sans Cloudflare, tout fonctionne quand même : `clients/<client>/espace/page.html` est une photographie de la
même page, à publier ou à envoyer, et les décisions se prennent dans la conversation.

## Décider

Les décisions sont des fichiers déposés dans `clients/<client>/decisions/` ; le moteur les applique au
passage suivant puis les range dans `appliquees/`.
```json
{"decisions": [
  {"action": "valider", "prospect": "tous"},
  {"action": "refuser", "prospect": "x@entreprise.fr", "motif": "déjà client"},
  {"action": "modifier", "prospect": "y@entreprise.fr", "etape": 1, "corps": "Bonjour..."},
  {"action": "opposer", "email": "@concurrent.fr"},
  {"action": "effacer", "email": "z@entreprise.fr"},
  {"action": "pause", "motif": "congés"}, {"action": "reprise"}
]}
```
En local, `python -m moteur decider dupont '{"action": "valider", "prospect": "tous"}'` fait la même chose tout de suite.

## Les règles que le moteur impose

- **Professionnels uniquement.** La prospection par email sans accord préalable n'est admise en France qu'entre
  professionnels et pour un objet en rapport avec la fonction du destinataire. Ne jamais l'utiliser vers des particuliers.
- **Identité réelle.** Le signataire est une personne qui existe chez le client, avec le nom de sa société.
- **Origine et arrêt** dans chaque premier message : où l'adresse a été trouvée, et « répondez STOP ».
- **Opposition définitive**, par client, y compris par domaine entier (`@societe.fr`).
- **Effacement** : la décision `effacer` (ou `python -m moteur effacer <client> <email>`) supprime tout sauf le blocage de l'adresse.
- **robots.txt respecté**, une pause entre deux pages d'un même site.

Le client reste responsable de sa prospection (c'est lui l'expéditeur). À prévoir dans vos conditions de vente,
avec une durée de conservation des données : trois ans après le dernier contact est l'usage.

## D'où viennent les prospects

Quatre sources, à combiner dans `cible` de la fiche. Les trois premières ne coûtent rien.

| Source | Réglage | Ce qu'elle apporte | Coût |
|---|---|---|---|
| Pages de liste | `sources` : adresses d'annuaires, d'adhérents, d'exposants | entreprises et leur site | 0 |
| Registre public | `registre` : `{"naf": ["49.41A"], "departements": ["17"], "effectifs": ["11", "12"]}` | nom, commune, dirigeants (pas de site) | 0 |
| Fichier | un CSV déposé dans `imports/` ; un export Apollo est reconnu tel quel | des contacts prêts | 0 |
| Recherche web | `recherches` : `["transporteur frigorifique La Rochelle"]` | 10 sites par requête | 20 crédits |

Sans `departements`, le registre couvre la France entière ; `"exclure_departements": ["17"]` écarte les
entreprises dont le siège est dans ces départements. Le registre est l'API officielle « Recherche d'entreprises » (gratuite, sans clé). Les entreprises en diffusion
partielle, qui ont demandé à ne pas être démarchées, sont écartées. Codes d'effectif : `03` 6 à 9 salariés,
`11` 10 à 19, `12` 20 à 49, `21` 50 à 99, `22` 100 à 199, `31` 200 à 249, `32` 250 à 499.

## ScrapeGraphAI, dans la limite du compte gratuit

Le compte gratuit donne 500 crédits par mois. Le moteur s'arrête de lui-même à 480 (`reglages.json` pour
changer), et à 160 par client quand la clé est commune. Il ne s'en sert que pour ce qu'il ne sait pas faire seul :

| Usage | Quand | Coût |
|---|---|---|
| Trouver le site d'une entreprise du registre | toujours, le registre ne le donne pas | 6 crédits |
| Recherche web libre | pour chaque requête de `recherches`, une seule fois | 20 crédits |
| Relire une page | seulement si la lecture directe revient vide (site fait en JavaScript) | 1 crédit |

L'extraction reste confiée à la clé Claude : l'extraction de ScrapeGraphAI coûte 5 crédits la page, cinq fois
la simple lecture. Ordre de grandeur pour un mois : 60 entreprises du registre (360 crédits), 4 recherches
libres (80), 40 pages en JavaScript (40). Soit de quoi alimenter un client, deux au plus, sur le compte gratuit ;
au-delà, une clé par client (formule autonome) ou le forfait à 10 000 crédits.

La clé va dans les secrets (`scrapegraph`). Sans clé, le moteur tourne quand même avec les sources gratuites.
`python -m moteur etat <client>` affiche les crédits consommés ; `credits.json` tient le compteur.
Un site qui interdit les robots n'est jamais relu par ce biais.

La bibliothèque libre ScrapeGraphAI reste disponible en variante (`"ia": {"scrapegraph": true}`, à installer sur
la machine du moteur) : elle ne consomme aucun crédit mais demande Chromium, donc pas le dépôt GitHub seul.

## Apollo

Le compte gratuit d'Apollo ne donne qu'une dizaine de crédits d'export par mois, API comprise : trop peu pour
en faire une source automatique. Deux usages restent utiles :
- exporter une liste depuis Apollo en CSV et la déposer dans `imports/` (nommer le fichier `apollo-….csv` :
  l'origine est alors indiquée au destinataire, comme la loi le demande) ;
- depuis la conversation de pilotage, demander à Claude de constituer la liste avec un connecteur de données
  (Apollo une fois autorisé dans vos connecteurs, ou un autre), puis de la déposer dans `imports/`.

## Ce qui a été vérifié, et ce qui ne l'a pas été

- `python tests/essai_a_blanc.py` rejoue trois semaines de prospection avec un faux web, une fausse IA et une
  fausse boîte : 48 vérifications (garde-fous de recherche, validation, cadence, plafonds, relances dans le fil,
  réponses, stop, rebond, absence, clôture, import, effacement, coupe-circuit, page de suivi).
- `python tests/essai_sources.py` : registre public, recherche de sites, relecture d'une page en JavaScript,
  budget ScrapeGraphAI (plafond par client, plafond du mois, compte épuisé, remise à zéro), export Apollo,
  fonctionnement sans clé, préparation sans envoi. 26 vérifications. La forme des réponses du registre a été contrôlée sur un appel réel.
- `python tests/essai_espace.py` ouvre la page en direct dans un vrai navigateur : le client corrige, valide,
  écarte, met en pause ; les fonctions du site déposent les décisions ; le moteur les applique et la page se
  met à jour. 16 vérifications, dont le refus des codes inconnus et des décisions réservées au pilote.

Non vérifié, faute d'accès réseau au moment de la construction :
- un envoi et une relève sur une vraie boîte (`tester-boite` puis un message à soi-même) ;
- un appel réel à l'API Claude, donc la qualité des messages écrits ;
- la lecture de vrais sites et la vérification DNS des domaines (`python -m moteur diagnostic <adresse de page>`
  le montre en une commande) ;
- l'API ScrapeGraphAI réelle : branchée d'après sa documentation, jamais appelée avec une vraie clé ;
- la bibliothèque ScrapeGraphAI (branchée d'après l'interface de la version 2.3.1, jamais exécutée sur un site) ;
- le site sur le vrai Cloudflare avec le vrai GitHub : l'essai remplace les deux par un serveur local.

Premier essai conseillé : votre propre offre, cinq adresses à vous ou à des proches, mode `validation`.
