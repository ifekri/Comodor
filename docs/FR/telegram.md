# Depuis votre téléphone

Comodor peut être piloté depuis un bot Telegram : envoyez-lui une tâche,
regardez-le travailler, répondez à ses questions et arrêtez-le — sans ouvrir un
terminal.

**La configuration du premier lancement le propose.** La dernière des six
questions offre de connecter un bot, vérifie le jeton auprès de Telegram sur
place, et associe votre compte avant la fin de l'assistant. Si vous avez répondu
*Pas maintenant*, ou si vous configurez une machine déjà réglée :

```bash
comodor telegram connect <token>   # a bot from @BotFather
comodor telegram pair              # add your account
comodor telegram start             # run it
```

Il fait tourner la même session d'agent que l'interface navigateur. Tout est un
bouton ; la frappe est réservée à la tâche elle-même.

## Obtenir un bot

Écrivez à [@BotFather](https://t.me/botfather) sur Telegram, envoyez `/newbot`,
donnez-lui un nom et un nom d'utilisateur se terminant par `bot`. Il répond avec
un jeton :

```
1234567890:AAF…
```

```bash
comodor telegram connect 1234567890:AAF…
```

## Association

**Le nom d'utilisateur d'un bot est public.** Quiconque le trouve peut lui
écrire, et celui-ci peut lire vos fichiers. Alors il ne répond qu'à une liste
fixe d'identifiants numériques d'utilisateurs Telegram, à personne d'autre.

```bash
comodor telegram pair
```

Cela affiche un code à six chiffres. Envoyez-le à votre bot sur Telegram et
votre compte est ajouté. Le code fonctionne une seule fois et expire au bout de
cinq minutes.

Tout le reste reçoit **le silence** — pas un refus. Un bot qui répond « vous
n'êtes pas autorisé » a dit à un inconnu qu'il existe, que c'est un Comodor, et
qu'il y a une liste qui vaut la peine d'y entrer.

```bash
comodor telegram status         # who may talk to it
comodor telegram forget 12345   # revoke one account
comodor telegram forget all     # revoke everybody
```

## Ce qu'il peut faire, et ce qu'il ne peut pas

**Par défaut, il lit et planifie, et ne change rien.** Une session Telegram est
tenue en mode planification, quel que soit le réglage du terminal.

C'est délibéré. Approuver une commande shell d'un pouce, sur un téléphone, dans
une file d'attente, est une décision prise avec moins d'attention que la même
approbation au clavier — et les conséquences sont identiques.

```bash
comodor telegram writes on      # let it edit files and run commands
comodor telegram writes off
```

Avec les écritures activées, il demande quand même d'abord, et l'approbation est
un bouton dans la discussion :

```
Comodor wants to run
  npm test

  ✓  Yes, once
  ✓✓ Yes, and stop asking this session
  ✗  No
```

L'engagement le plus large n'est jamais le premier bouton sous votre pouce — sur
un téléphone ils sont proches les uns des autres et « toujours » ne se défait
pas.

## Les boutons

`/start` répond avec le modèle, le dossier et ce qui lui est permis, et les
réglages en dessous. Ils sont sur le premier écran plutôt que derrière un bouton
*Settings*, car ce que vise un bot est la première chose que tout le monde
veut connaître et la première chose que l'on veut changer.

| | |
|---|---|
| **New chat** | Oublier la conversation en cours |
| **History** | Rouvrir n'importe quelle conversation antérieure, en entier |
| **Stop** | Interrompre ce qui tourne — remplace *New chat* tant que c'est le cas |
| **Mode** | Agir, planifier ou discuter, chacun énoncé |
| **Status** | Modèle, dossier, contexte, dépenses |
| **Model** | Chaque modèle que le fournisseur propose ; touchez pour basculer |
| **Folder** | Le projet auquel il est confiné |
| **Skills** | Installer ou retirer une compétence de la bibliothèque |
| **Rules** | Ce qu'il a appris de vos corrections, et combien |
| **Settings** | Le reste — le coût, et ce qu'il peut faire |
| **Help** | Ce que fait chaque chose, sans quitter la discussion |

Quand l'agent a besoin d'une décision, il demande aussi avec des boutons — les
mêmes questions qu'il poserait dans le terminal, une par écran, avec **Write my
own** pour tout ce à quoi il n'aurait pas pensé.

Les listes plus longues qu'un écran — modèles, compétences, historique — sont
paginées six par six, avec **Previous** et **Next**. Telegram rendra quatre-vingt
boutons avec plaisir, et personne ne les fera défiler.

## Le faire tourner

Trois façons, selon la durée pendant laquelle vous le voulez.

```bash
comodor telegram start                # here, holding this terminal
comodor telegram start --background   # detached; survives closing the terminal
comodor telegram service install      # starts at every login, survives a reboot
```

**Au premier plan** il tient le terminal et montre ce qu'il fait. C'est celui à
utiliser pendant la configuration, et celui auquel revenir quand quelque chose
ne fonctionne pas.

**En arrière-plan** c'est le même processus, détaché du terminal qui l'a
lancé, écrivant dans un journal plutôt que sur un écran. Fermer le terminal, se
déconnecter, mettre fin à la session — rien de tout cela ne l'emporte.

```bash
comodor telegram stop        # end it
comodor telegram status      # is it running, since when, and as which pid
```

Le journal est `telegram.log` à côté de votre configuration, et il s'y ajoute au
lieu d'être remplacé — la raison pour laquelle un bot s'est arrêté hier soir se
trouve dans les lignes qu'un redémarrage effacerait autrement.

**À la connexion**, c'est le travail du système d'exploitation, pas le nôtre :
rien de ce qu'un programme lance pour lui-même ne survit au redémarrage de la
machine.

```bash
comodor telegram service show        # read the unit before trusting it
comodor telegram service install
comodor telegram service uninstall
```

| | |
|---|---|
| Linux | une unité **utilisateur** systemd dans `~/.config/systemd/user` |
| macOS | un LaunchAgent dans `~/Library/LaunchAgents` |
| Windows | une tâche du Planificateur de tâches qui s'exécute à la connexion |

Un service utilisateur sur les trois, jamais un service système. Un service
système tourne en root ou en SYSTEM, et ceci est un agent qui lit et écrit vos
fichiers avec vos identifiants — plus d'autorité que la personne qui possède ces
fichiers n'achète rien et coûte tout si jamais elle se trompe.

`service show` affiche l'unité avant que `service install` ne l'écrive. On ne
devrait demander à personne de faire confiance à une définition de démon qu'on
ne lui a pas montrée.

Le dossier compte dans les trois cas : l'agent ne lit et n'écrit que dans le
répertoire où il a été lancé, et c'est celui où le bot travaillera.

## Comment c'est construit

Aucune nouvelle dépendance. L'API Bot est une boucle de `getUpdates` et
`sendMessage`, par-dessus le client HTTP que ce projet possède déjà —
`python-telegram-bot` aurait été la plus grosse chose dans la roue, pour cela.

La réponse est modifiée sur un minuteur plutôt qu'à chaque jeton. Telegram
facture un aller-retour par modification et les limite en débit, si bien que
modifier à chaque jeton produit un message étranglé qui arrive d'un coup à la
fin.

Le bot garde un décalage de mises à jour et l'avance au fil de l'eau. Sans lui,
un redémarrage rejoue chaque message que le bot a jamais reçu — ce qui, pour un
agent qui exécute des commandes, n'est pas seulement bruyant.

## Ce qu'il ne fera pas

- Répondre à quiconque n'est pas associé, ni dire pourquoi.
- Prendre un jeton ou un compte autorisé dans le `.comodor/config.json` d'un
  projet. Un dépôt qui pourrait ajouter son auteur à cette liste serait une
  porte dérobée, et contrairement au navigateur ou à l'écran, rien à l'écran ne
  montrerait que cela arrive.
- Écrire quoi que ce soit avant `telegram writes on`.
- Afficher le jeton. Il figure dans chaque URL de l'API Bot, donc chaque erreur
  levée est dépouillée de sa présence.
