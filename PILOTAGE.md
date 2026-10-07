# Piloter depuis une conversation Claude

Principe : une conversation par client, comme pour IRIS. La conversation ne fait pas tourner le moteur
(une session Claude ne peut pas joindre une boîte email) ; elle lit et écrit dans le dépôt, et le moteur,
lancé toutes les demi-heures par GitHub ou par votre ordinateur, exécute.

| Qui | Écrit | Lit |
|---|---|---|
| Claude, dans la conversation | `client.json`, `decisions/*.json`, `imports/*.csv` | `etat.json`, `espace/page.html` |
| Le moteur | `etat.json`, `espace/`, `decisions/appliquees/` | tout le reste |

Chacun écrit dans ses fichiers : pas de conflit entre les deux.

## Phrase d'ouverture d'une conversation client

> Tu pilotes la prospection par email du client `<nom>` dans le dépôt `<compte>/<dépôt>`.
> Lis README.md et PILOTAGE.md, puis `clients/<nom>/client.json` et `etat.json`. Tu n'écris que dans
> `client.json`, `decisions/` et `imports/`. Dis-moi où en est le client et ce qui attend mon accord.

## Ce qu'on demande ensuite, et ce que Claude fait

| Vous dites | Claude fait |
|---|---|
| « Ouvre le client Dupont, voici son site et son offre » | lit le site, remplit `client.json` (cible, offre, preuves tirées du site uniquement), le laisse `"actif": false` et vous le montre |
| « Voici des pages d'annuaire » / « voici un fichier » | ajoute les adresses de pages à `cible.sources`, ou dépose le CSV dans `imports/` |
| « Cherche des transporteurs en Charente-Maritime » | règle `cible.registre` (codes d'activité, départements, effectifs) ou ajoute une requête à `cible.recherches`, en annonçant le coût en crédits |
| « Prends cette liste Apollo » | dépose le CSV dans `imports/` sous un nom commençant par `apollo-` |
| « Montre-moi ce qui attend » | lit `etat.json`, affiche chaque contact `a_valider` avec ses trois messages et les alertes |
| « Je valide tout » / « refuse Untel » / « change cette phrase » | dépose un fichier dans `decisions/` |
| « Où en est-on ? » | compte envoyés, réponses, arrêts, adresses invalides ; cite les réponses mot pour mot |
| « Mets en pause » / « reprends » | décision `pause` / `reprise` |
| « Passe-le en autonome » | `"mode": "autonome"` dans la fiche (les messages comportant une alerte restent soumis à accord) |
| « Publie sa page de suivi » | publie `espace/page.html` et donne le lien à transmettre au client |
| « Untel demande qu'on efface ses données » | décision `effacer` : ses données disparaissent, son adresse reste bloquée |

## Ce que le client fait sans vous

Depuis sa page (`/e/<code>`), il valide, corrige un message, écarte un contact, met en pause ou reprend.
Ses clics arrivent dans `decisions/` comme les vôtres, signés `"par": "espace"`, et sont appliqués au passage
suivant. Votre console (`/console/`) montre d'un coup d'œil qui attend un accord.

## Règles pour Claude dans ces conversations

- Dans la fiche, `offre.preuves` ne contient que des faits donnés par le client ou lus sur son site. Rien d'estimé.
- Ne jamais écrire dans `etat.json` : c'est la mémoire du moteur.
- Ne jamais répondre à un prospect à la place du client. Proposer un brouillon si on le demande ; l'envoi reste humain.
- Une cible faite de particuliers se refuse : l'outil est réservé aux échanges entre professionnels.
- Si `etat.json` indique une pause automatique, le dire en premier, avec le motif.

## Les deux formules

**Pilotée.** Vous tenez la conversation et validez pour le client. Il reçoit le lien de sa page de suivi et
répond lui-même aux réponses reçues dans sa boîte.

**Autonome.** Le client a son propre dépôt (ou son dossier sur votre installation), sa clé API et sa
conversation Claude avec la phrase d'ouverture ci-dessus. Vous livrez l'installation et la fiche remplie ;
il valide et pilote seul. Mode `validation` conseillé les deux premières semaines.
