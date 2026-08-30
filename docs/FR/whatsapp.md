# Depuis WhatsApp

Le même agent, rejoint depuis un numéro WhatsApp business : envoyez-lui une
tâche, regardez-le travailler, répondez à ses questions — sans ouvrir un
terminal.

> **Lisez ceci d'abord.** [Telegram](telegram.md) fait la même chose et prend
> environ une minute : écrire à @BotFather, coller un jeton. WhatsApp prend
> environ vingt minutes, est technique, et l'essentiel se passe dans le tableau
> de bord de Meta — il vous faut une app Meta, un secret d'app et une adresse
> HTTPS publique. **Si ce n'est pas obligatoirement WhatsApp, prenez Telegram.**
>
> [Slack](slack.md) est la voie du milieu : environ cinq minutes, et pas
> d'adresse publique non plus.
>
> Il n'y a pas moyen d'y échapper. WhatsApp n'a pas d'équivalent d'un jeton de
> bot, et Meta livre les messages à une URL plutôt que de laisser qui que ce
> soit les récupérer. La seule véritable version en un clic ferait passer chaque
> message par le serveur de quelqu'un d'autre, ce qui n'est pas un marché que
> cet outil accepte.

```bash
comodor whatsapp connect              # walks you through all of it
comodor whatsapp pair                 # add your number
comodor whatsapp start --background   # run it
```

`connect` sans argument est une configuration guidée : elle lie chaque page,
prend une valeur à la fois, et vérifie chacune à son arrivée — le jeton auprès
de Meta, l'identifiant pour ce qu'est un identifiant, le secret pour ce qu'est
un secret. Elle démarre le tunnel pour vous, et elle attend que le rappel de
vérification de Meta arrive réellement plutôt que de supposer qu'il est arrivé.

Il fait tourner la même session d'agent que le terminal, le navigateur et le bot
Telegram. Une tâche commencée ici apprend les mêmes leçons et apparaît dans le
même historique.

## Pourquoi cela demande plus de réglages que Telegram

Telegram vous donne un jeton et vous laisse récupérer les messages. WhatsApp,
c'est la **Cloud API** de Meta, et deux de ses décisions de conception façonnent
tout ce qui suit.

**Les messages sont livrés, pas récupérés.** Pas de long poll. Meta publie
chaque message entrant vers une URL, ce qui signifie que quelque chose de vous
doit être joignable depuis Internet en HTTPS. C'est le travail supplémentaire,
et il n'y a pas moyen d'y échapper.

**Meta veut une app.** Un compte business, un numéro, un jeton d'accès et un
secret d'app — quatre choses qui vivent dans un navigateur, et voilà pourquoi
l'assistant du premier lancement pointe vers cette page plutôt que de tenter de
les recueillir.

L'alternative que choisit la plupart des projets est une bibliothèque qui pilote
WhatsApp Web au travers d'un navigateur sans interface. Celles-ci ont besoin de
Node, elles cassent dès que WhatsApp change son client web, et elles vont contre
les conditions auxquelles le compte est tenu : le mode d'échec, c'est le numéro
banni. Ce n'est pas quelque chose qu'un outil de programmation a le droit
d'infliger à ses utilisateurs.

## Combien de temps cela prend

Environ vingt minutes la première fois, contre une minute pour Telegram, et
l'essentiel se passe dans le tableau de bord de Meta plutôt qu'ici.

Ce dont vous n'avez **pas** besoin : un vrai numéro de téléphone, un moyen de
paiement, ou la vérification business. L'ajout du produit WhatsApp crée un
**numéro de test** qui écrit gratuitement jusqu'à cinq destinataires, ce qui
fait quatre de plus que ce qu'une personne qui parle à son propre agent exige.

## Configuration

La version courte est `comodor whatsapp connect`, qui guide tout le parcours.
Ce qui suit est ce qu'elle parcourt, pour quiconque préfère le voir d'abord.

### 1. Une app Meta avec WhatsApp dessus

Sur [developers.facebook.com](https://developers.facebook.com), créez une app
et ajoutez le produit **WhatsApp**. Meta vous donne un numéro de test pour
commencer ; un vrai s'ajoute plus tard sous le compte business.

Il vous faut quatre choses de là-bas :

| | |
|---|---|
| **Phone number id** | L'identifiant numérique à côté du numéro — *pas* le numéro |
| **Access token** | Celui du tableau de bord expire au bout de 24 heures. Un jeton **System User** sous Business Settings n'expire pas, et c'est celui qu'il faut utiliser |
| **App secret** | Settings → Basic. Chaque webhook est signé avec lui |
| **Une adresse HTTPS publique** | Là où Meta livre. Voir ci-dessous |

```bash
comodor whatsapp connect \
    --number-id 123456789012345 \
    --token EAAG… \
    --app-secret 0a1b2c…
```

Cela vérifie le jeton auprès de Meta avant d'enregistrer quoi que ce soit, si
bien qu'une faute de frappe est un message aujourd'hui plutôt qu'un mystère la
semaine prochaine.

### 2. Un endroit où Meta peut livrer

Le bot écoute sur `127.0.0.1:8770`. Meta ne livre qu'en **HTTPS** et n'accepte
pas de certificat auto-signé, donc quelque chose doit lui en mettre un vrai
devant. Un tunnel est la réponse habituelle : pas de port ouvert, pas de DNS,
pas de domaine.

**`comodor whatsapp connect` le fait pour vous** si `cloudflared` est installé
— elle démarre le tunnel, en lit l'adresse, et vous montre quoi coller. Pour en
lancer un vous-même :

```bash
cloudflared tunnel --url http://127.0.0.1:8770
comodor whatsapp connect --url https://something.trycloudflare.com/whatsapp
comodor whatsapp webhook
```

**Un tunnel rapide reçoit une nouvelle adresse à chaque démarrage.** C'est très
bien pendant la configuration et faux pour un bot censé tourner sans fin : Meta
continue de livrer à l'adresse que vous lui avez donnée, si bien qu'après un
redémarrage rien n'arrive et rien ne dit pourquoi. `comodor whatsapp start
--tunnel` avertit quand l'adresse a bougé.

Pour une adresse qui reste, créez un tunnel nommé une fois — il faut un compte
Cloudflare gratuit :

```bash
cloudflared tunnel login
cloudflared tunnel create comodor
cloudflared tunnel route dns comodor comodor-hooks.example.com
```

N'importe quoi d'autre qui termine TLS et transfère vers `127.0.0.1:8770`
fonctionne de la même façon.

```
  Callback URL   https://something.trycloudflare.com/whatsapp
  Verify token   Kq3nP…
```

Collez les deux dans **WhatsApp → Configuration** dans le tableau de bord, puis
abonnez l'app au champ **messages**. Meta appelle immédiatement l'URL une fois
pour la vérifier ; le bot répond lui-même à cette poignée de main.

Un reverse proxy que vous faites déjà tourner fonctionne de la même façon —
n'importe quoi qui termine TLS et transfère vers `127.0.0.1:8770`.

### 3. Associez votre numéro

```bash
comodor whatsapp pair
```

Cela affiche un code à six chiffres. Envoyez-le au numéro business depuis
WhatsApp et votre numéro est ajouté. Le code fonctionne une seule fois et expire
au bout de cinq minutes.

**Un numéro business est un numéro de téléphone**, et les inconnus écrivent à
des numéros de téléphone comme de juste. Alors il ne répond qu'à une liste
fixe et tout le reste reçoit **le silence** — pas un refus. Un numéro qui dit
« vous n'êtes pas autorisé » a dit à un inconnu que cela vaut la peine de
réessayer.

```bash
comodor whatsapp status         # who may talk to it
comodor whatsapp forget 15551234567
comodor whatsapp forget all
```

La liste est comparée en chiffres, si bien que `+1 555…`, `001 555…` et
`1555…` sont une même personne plutôt que trois.

## Ce qu'il peut faire, et ce qu'il ne peut pas

**Par défaut, il lit et planifie, et ne change rien.** Une session WhatsApp est
tenue en mode planification, quel que soit le réglage du terminal, pour la même
raison que Telegram : approuver une commande shell d'un pouce, dans une file
d'attente, est une décision prise avec moins d'attention que la même approbation
au clavier.

```bash
comodor whatsapp writes on
comodor whatsapp writes off
```

C'est une commande de terminal à dessein. Un bot qui pourrait élargir ses
propres autorisations n'aurait besoin que du téléphone de quelqu'un.

## Les boutons

WhatsApp autorise **trois** boutons de réponse de vingt caractères, ou un bouton
qui ouvre une liste de **dix** lignes. Ce sont des limites strictes — Meta
rejette le message entier au lieu de le raccourcir — si bien que le menu est une
liste, et qu'il fait exactement dix lignes :

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

Pendant qu'une tâche tourne, la seule chose offerte est **Stop** : il n'y a pas
de place sur un écran aussi étroit pour garder un contrôle grisée.

Les listes plus longues — modèles, compétences, historique — sont paginées huit
par huit, car les deux lignes de navigation comptent dans les dix.

## Deux choses qui vous surprendront

**Il ne peut pas modifier un message.** Telegram diffuse une réponse en
réécrivant un même message au fil de son arrivée. WhatsApp n'a pas de
modification, et un message par jeton ferait cent notifications pour une seule
question. Alors un tour annonce une ligne au démarrage, parle de temps en temps
pendant qu'il travaille, et envoie la réponse quand il y en a une.

**Il y a une fenêtre d'une journée.** Meta n'autorise les messages libres que
dans les vingt-quatre heures qui suivent *votre* dernier message. Si une longue
tâche se termine après, le bot ne peut pas vous le dire — il l'écrit dans son
journal, et lui écrire de nouveau rouvre la fenêtre.

## Le faire tourner

Exactement comme Telegram :

```bash
comodor whatsapp start                # here, holding this terminal
comodor whatsapp start --tunnel       # and bring a tunnel up with it
comodor whatsapp start --background   # detached; survives closing it
comodor whatsapp stop
comodor whatsapp service install      # starts at login, survives a reboot
comodor whatsapp service show         # read the unit before trusting it
```

Le journal est `whatsapp.log` à côté de votre configuration, ajouté plutôt que
remplacé.

Un service **utilisateur** sur chaque plateforme — systemd, launchd,
Planificateur de tâches — jamais un service système. C'est un agent qui lit et
écrit vos fichiers avec vos identifiants, et plus d'autorité que la personne qui
possède ces fichiers n'achète rien.

## Comment c'est construit

Aucune nouvelle dépendance. La Cloud API est un `POST /messages` par-dessus le
client HTTP que ce projet possède déjà, et le webhook est le `http.server` de la
bibliothèque standard.

Le point de terminaison répond à Meta **avant** de faire le travail. Meta
réessaie tout ce pour quoi il n'obtient pas de 200 dans les secondes qui suivent,
et un tour d'agent prend des minutes — un webhook qui attend se voit livrer le
même message cinq fois.

Les identifiants de messages sont mémorisés, si bien qu'une relivraison qui
arrive quand même ne devient pas un second tour.

## Ce qu'il ne fera pas

- Répondre à quiconque n'est pas associé, ni dire pourquoi.
- Accepter un webhook qu'il ne peut pas vérifier. Sans secret d'app rien n'est
  vérifié, et `comodor whatsapp status` le dit en jaune.
- Prendre un jeton, un numéro ou un compte autorisé dans le
  `.comodor/config.json` d'un projet. Un dépôt qui pourrait ajouter son auteur à
  cette liste serait une porte dérobée.
- Écrire quoi que ce soit avant `whatsapp writes on`.
- Afficher le jeton. Il est rédigé hors de chaque erreur levée.
