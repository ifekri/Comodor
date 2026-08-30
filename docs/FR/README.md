# Documentation de Comodor

Un agent de codage en terminal qui apprend de la manière dont vous le corrigez.

Nouveau ici ? **[Premiers pas](getting-started.md)** prend environ cinq minutes et
se termine avec l'agent faisant quelque chose d'utile.

---

## Selon ce que vous cherchez à faire

### Se lancer

| | |
|---|---|
| [Premiers pas](getting-started.md) | Installer, choisir un modèle, première tâche |
| [Venir d'un autre agent](migrating.md) | Importer clés et compétences depuis OpenClaw ou Hermes |
| [Choisir un modèle](models.md) | Quel fournisseur, quel modèle, ce que ça coûte |

### L'utiliser

| | |
|---|---|
| [L'interface](interface.md) | Panneaux, touches, modes, et les 29 commandes |
| [Depuis le terminal](cli.md) | Chaque commande et chaque option, avec des exemples |
| [Ce que l'agent peut faire](tools.md) | Les 13 outils dont il dispose, et quand il utilise chacun |
| [Compétences](skills.md) | Des procédures que vous écrivez une fois et qu'il suit |

### Le pousser plus loin

| | |
|---|---|
| [Le vrai navigateur](browser.md) | Un navigateur qui exécute JavaScript et sait se connecter |
| [Utiliser votre écran](computer.md) | Souris et clavier, dans n'importe quelle application |
| [Depuis un navigateur](web.md) | L'interface web, en local ou sur un serveur |
| [Dans votre éditeur](acp.md) | Piloter Comodor depuis Zed ou tout client Agent Client Protocol |
| [Dans Docker](docker.md) | Une commande, dans un conteneur |
| [Serveurs MCP](mcp.md) | Des outils issus du Model Context Protocol |

### Le comprendre

| | |
|---|---|
| [Depuis votre téléphone](telegram.md) | Le bot Telegram : appairage, les boutons, et à qui il répond |
| [Depuis Slack](slack.md) | Socket Mode — cinq minutes, pas d'adresse publique, et il répond dans les fils |
| [Depuis WhatsApp](whatsapp.md) | L'API Cloud — une vingtaine de minutes et technique. Telegram fait la même chose en une |
| [Modèles sur votre machine](local-models.md) | En télécharger un, l'exécuter hors ligne, l'ajouter à la liste |
| [Questions](questions.md) | Le formulaire qu'il affiche quand une demande se lit de deux façons |
| [Comment il apprend](learning.md) | Corrections, leçons, règles, et la preuve |
| [Sécurité et permissions](safety.md) | Ce qu'il peut faire, ce qu'il demande, ce qu'il ne fait jamais |
| [Coût](cost.md) | Cache, budgets, et payer moins pour le même travail |
| [Configuration](configuration.md) | Chaque réglage, où vivent les fichiers, ce qui prime |

### Quand quelque chose va mal

| | |
|---|---|
| [Dépannage](troubleshooting.md) | `doctor`, problèmes courants, et comment en signaler un |

---

## La version la plus courte possible

```bash
curl -fsSL get.comodor.ai | sh      # macOS, Linux
irm get.comodor.ai | iex           # Windows

comodor                  # it asks a few questions, once
```

Tapez ensuite ce que vous voulez. Corrigez-le quand il se trompe — modifiez le
fichier, ou dites-le simplement — et il apprend. `/progress` vous montre si cela
fonctionne réellement.

```bash
comodor run "fix the failing test in tests/test_parser.py"   # one task, no interface
comodor web                                                  # from a browser
comodor doctor                                               # is everything alright?
comodor help                                                 # the written help page
```

## Ce qui le distingue

**Il apprend de vos corrections, pas de vos éloges.** La plupart des agents
oublient dès la fin d'une session. Comodor observe ce que vous modifiez dans ses
résultats et en fait une leçon dont la confiance monte quand elle se vérifie et
baisse quand elle ne se vérifie pas. [Comment il apprend](learning.md) explique
le mécanisme ; `/progress` montre les preuves.

**Il demande avant d'agir, et tout est réversible.** Lire se fait en silence.
Écrire demande. Exécuter une commande demande plus fort. Chaque écriture est
sauvegardée, et `/undo` restaure la précédente. [Sécurité et
permissions](safety.md).

**Une seule dépendance.** Le client HTTP, le lecteur SSE, le WebSocket pour le
navigateur, l'encodeur PNG pour les captures d'écran — tout fait partie du
paquet. Installer Comodor n'ajoute que `rich`, et rien d'autre.

**Il peut utiliser un vrai navigateur et un vrai bureau.** Pas un simple
récupérateur de texte : un navigateur qui exécute JavaScript et conserve les
cookies, et — sous Windows — la souris et le clavier, avec un halo à l'écran
vous montrant où il s'apprête à cliquer. [Navigateur](browser.md),
[écran](computer.md).

---

## Également dans le dépôt

| | |
|---|---|
| [CHANGELOG](../CHANGELOG.md) | Ce qui a changé, et pourquoi |
| [CONTRIBUTING](../CONTRIBUTING.md) | Travailler sur Comodor lui-même |
| [SECURITY](../SECURITY.md) | Signaler quelque chose de sensible |
| [RELEASING](../RELEASING.md) | Comment une version est préparée |
