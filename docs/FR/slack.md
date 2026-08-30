# Depuis Slack

Le même agent, dans votre espace de travail : envoyez-lui une tâche, regardez-le
travailler, répondez à ses questions — sans ouvrir un terminal.

```bash
comodor slack manifest              # the app definition to paste into Slack
comodor slack connect               # the two tokens, checked as you paste them
comodor slack pair                  # add your account
comodor slack start --background    # run it
```

Environ cinq minutes, et il n'y a **aucune adresse publique à organiser** — ce
qui le sépare de [WhatsApp](whatsapp.md).

Il fait tourner la même session d'agent que le terminal, le navigateur et le bot
Telegram. Une tâche commencée ici apprend les mêmes leçons et aboutit dans le
même historique.

## Pourquoi c'est simple

Slack a deux façons de livrer les événements. L'Events API publie vers une URL,
ce qui signifie une adresse HTTPS publique, un certificat et un tunnel — tout le
travail qui rend WhatsApp difficile.

**Socket Mode** l'inverse : l'app demande à Slack une adresse websocket et se
connecte *vers l'extérieur*. Rien ne doit être joignable depuis Internet, et il
n'y a pas d'adresse à tenir à jour. C'est toute l'astuce, et c'est pourquoi
Slack se place à côté de Telegram plutôt qu'à côté de WhatsApp.

La seconde chose qui aide est le **manifeste d'app**. Slack permet de décrire
une app dans un document YAML, si bien qu'au lieu de chercher onze cases à cocher
réparties sur quatre pages de réglages, toute l'app — nom, périmètres,
événements, Socket Mode déjà activé — tient en un collage.

## Configuration

### 1. Créez l'app

```bash
comodor slack manifest
```

Cela affiche le manifeste et le lien. Sur
[api.slack.com/apps](https://api.slack.com/apps?new_app=1), choisissez **From a
manifest**, sélectionnez votre espace de travail, collez, créez — puis
**Install to Workspace**.

### 2. Les deux jetons

Ils ne sont pas interchangeables, et les confondre est la façon la plus commune
dont cela échoue. Comodor refuse chacun à la place de l'autre, en le nommant,
plutôt que de laisser Slack répondre `invalid_auth` une heure plus tard.

| | | |
|---|---|---|
| `xoxb-…` | **Bot token** | OAuth & Permissions. Fait tout ce que fait le bot |
| `xapp-…` | **App-level token** | Basic Information → App-Level Tokens, périmètre `connections:write`. Ouvre le socket, et rien d'autre |

```bash
comodor slack connect
```

Sans argument, elle vous guide pour les deux et vérifie chacun à son arrivée —
le jeton de bot auprès de `auth.test`, le jeton d'app en ouvrant réellement un
socket avec lui. Un mauvais jeton est une phrase aujourd'hui plutôt qu'un
mystère la semaine prochaine.

### 3. Associez votre compte

```bash
comodor slack pair
```

Cela affiche un code à six chiffres. Envoyez-le à Comodor en message direct et
votre compte est ajouté. Le code fonctionne une seule fois et expire au bout de
cinq minutes.

**Un espace de travail peut compter des centaines de personnes**, et ceci est un
agent qui lit et écrit vos fichiers. Alors il ne répond qu'à une liste fixe
d'identifiants d'utilisateurs Slack et ignore tout le reste.

```bash
comodor slack status
comodor slack forget U01234567
comodor slack forget all
```

## Où il répond

**En message direct**, toujours.

**Dans un canal, seulement quand il est mentionné.** Un bot qui répond à chaque
message d'un canal partagé est un bot que quelqu'un retire dans l'après-midi.

**Dans le fil où on lui a parlé.** Une question posée dans un fil obtient sa
réponse dans ce fil, pas dans le canal devant tout le monde.

Ses propres messages ne sont jamais répondus — un bot qui se répond à lui-même
est une boucle avec une limite de débit.

## Ce qu'il peut faire, et ce qu'il ne peut pas

**Par défaut, il lit et planifie, et ne change rien.** Une session Slack est
tenue en mode planification, quel que soit le réglage du terminal, pour la même
raison que les autres canaux : approuver une commande shell depuis un téléphone,
dans une file d'attente, est une décision prise avec moins d'attention que la
même approbation au clavier.

```bash
comodor slack writes on
comodor slack writes off
```

Une commande de terminal à dessein. Un bot qui pourrait élargir ses propres
autorisations n'aurait besoin que du compte Slack de quelqu'un.

## Les boutons

Slack est le plus spacieux des trois canaux — les messages peuvent être modifiés
et les boutons sont nombreux — si bien qu'une réponse est un message qui grandit
au fil de l'arrivée de la réponse, et que tout le menu tient sur un écran.

| | |
|---|---|
| **New chat** | Oublier la conversation en cours |
| **History** | Rouvrir une conversation antérieure |
| **Mode** | Agir, planifier ou discuter |
| **Status** | Modèle, dossier, contexte, dépenses |
| **Model** | Basculer vers un autre |
| **Folder** | Le projet où il travaille |
| **Skills** | Installer ou retirer une compétence |
| **Rules** | Ce qu'il a appris de vos corrections |
| **What it may do** | S'il peut écrire et exécuter |
| **Help** | Ce que fait chaque chose |

Pendant qu'une tâche tourne, la seule chose offerte est **Stop**.

## Le faire tourner

```bash
comodor slack start                # here, holding this terminal
comodor slack start --background   # detached; survives closing it
comodor slack stop
comodor slack service install      # starts at login, survives a reboot
comodor slack service show         # read the unit before trusting it
```

Le journal est `slack.log` à côté de votre configuration, ajouté plutôt que
remplacé.

Un service **utilisateur** sur chaque plateforme — systemd, launchd,
Planificateur de tâches — jamais un service système. C'est un agent qui lit et
écrit vos fichiers avec vos identifiants, et plus d'autorité que la personne qui
possède ces fichiers n'achète rien.

## Depuis le panneau navigateur

`comodor web` → **Admin** → **From your phone** connecte, associe, démarre et
arrête tout cela sans terminal. Ces contrôles ne répondent qu'aux requêtes
venant de la machine où Comodor tourne : un jeton de bot remet la télécommande à
quiconque détient le jeton.

## Comment c'est construit

Aucune nouvelle dépendance. La Web API est un `POST /api/chat.postMessage`
par-dessus le client HTTP que ce projet possède déjà, et Socket Mode tourne
par-dessus le client websocket écrit pour piloter Chrome — voilà pourquoi
ajouter Slack n'a ajouté aucun paquet.

Trois choses dont la boucle du socket se soucie, chacune étant une façon qu'a un
bot de se taire sans que personne ne le remarque :

- **Chaque enveloppe est acquittée.** Slack relivre ce dont il n'entend pas
  parler, et pour un agent qui exécute des commandes, un message devenant trois
  tours n'est pas seulement bruyant.
- **`disconnect` est de routine.** Slack fait tourner ses connexions selon un
  calendrier. Le traiter comme un échec produit un bot qui meurt toutes les
  quelques heures.
- **Un espace de travail silencieux reçoit quand même des pings.** Le cas qui
  compte le plus — personne ne lui a écrit depuis une heure — est exactement
  celui qu'un socket rompu ruine.

## Ce qu'il ne fera pas

- Répondre à quiconque n'est pas associé.
- Répondre à tout dans un canal où il a été ajouté.
- Prendre un jeton ou un compte autorisé dans le `.comodor/config.json` d'un
  projet. Un dépôt qui pourrait ajouter son auteur à cette liste serait une
  porte dérobée.
- Écrire quoi que ce soit avant `slack writes on`.
- Afficher l'un des deux jetons. Les deux sont rédigés hors de chaque erreur
  levée.
