# Depuis le terminal

Chaque commande et chaque option, avec quelque chose à coller.

```bash
comodor help              # the written help page
comodor help computer     # one topic in more detail
```

---

## Installer et mettre à jour

```bash
curl -fsSL get.comodor.ai | sh     # macOS, Linux, BSD
```

```powershell
irm get.comodor.ai | iex          # Windows
```

`get.comodor.ai` ne nomme aucun fichier : il lit quel client demande et répond
avec l'installateur que ce client peut exécuter. La même ligne unique met à
jour une installation existante. Ou, une fois qu'il est sur votre machine :

```bash
comodor update --check    # what is out there
comodor update            # move to it
```

[Premiers pas](getting-started.md#1-install) contient le reste — les
gestionnaires de paquets, et ce que les installateurs acceptent.

---

## Le démarrer

```bash
comodor                              # the interface
comodor --demo                       # the interface, offline, no key needed
comodor --resume                     # reopen the last session
comodor --resume 2026-08-22-a4f1     # reopen one by id
comodor --cwd ~/projects/api         # work somewhere other than here
comodor --model claude-sonnet-5      # a different model, this run only
comodor --mode plan                  # start read-only
```

### Options

| | |
|---|---|
| `--provider NAME` | `openrouter`, `anthropic`, `openai`, `ollama`, … |
| `--model ID` | remplacer le modèle pour cette exécution |
| `--mode act\|plan\|chat` | plan est en lecture seule ; chat n'a pas d'outils |
| `--no-loop` | répondre une fois au lieu de travailler jusqu'au bout |
| `--cwd PATH` | le dossier qu'il peut toucher |
| `--theme NAME` | `ember`, `midnight`, `matrix`, `mono` |
| `--ascii` | bordures ASCII |
| `--no-mouse` | laisser la souris au terminal |
| `--resume [ID]` | la dernière session, ou une par identifiant |
| `--demo` | fournisseur hors ligne scripté |
| `--version` | quelle version ceci est |
| `-h`, `--help` | la page d'aide écrite |

Aucune de ces options n'est écrite dans votre configuration. Elles ne
s'appliquent qu'à cette exécution. Pour qu'un changement persiste, utilisez
`/save` dans l'interface ou modifiez le fichier de configuration —
[Configuration](configuration.md).

---

## `comodor run` — une tâche, sans interface

```bash
comodor run "fix the failing test in tests/test_parser.py"
comodor run "add type hints to src/parser.py" --yes
comodor run "what does this project do?" --json
comodor run "refactor the parser" --max-steps 40
```

| | |
|---|---|
| `--yes` | approuver écritures et commandes automatiquement |
| `--json` | un résultat lisible par machine sur stdout |
| `--max-steps N` | remplacer la limite de pas pour cette exécution |

Sans `--yes`, il demandera, sur stderr, et refusera plutôt que de supposer si
rien ne peut répondre. C'est délibéré : un script qui s'approuve silencieusement
lui-même est un script qui fait quelque chose que vous n'attendiez pas à trois
heures du matin.

`--json` vous donne :

```json
{
  "text": "Fixed. The parser raised on empty input rather than returning [\"\"] …",
  "ok": true,
  "stopped": "done",
  "steps": 6,
  "tool_calls": 11,
  "error": "",
  "usage": {
    "input_tokens": 18422,
    "output_tokens": 640,
    "cost_usd": 0.031
  },
  "elapsed": 24.71
}
```

`stopped` dit pourquoi il s'est terminé — l'un des suivants :

| | |
|---|---|
| `done` | il a décidé qu'il avait fini |
| `max_steps` | il a atteint `agent.max_steps` |
| `budget` | il a atteint `agent.max_cost_usd` ou `agent.max_seconds` |
| `cancelled` | vous l'avez interrompu |
| `error` | quelque chose a mal tourné ; `error` dit quoi |

`ok` est vrai pour `done` et `max_steps` — manquer de pas n'est pas un échec,
c'est un plafond qui fait son travail — vérifiez donc aussi `stopped` si vous
avez besoin de la différence :

```bash
comodor run "update the changelog for this release" --yes --json > result.json
jq -e '.stopped == "done"' result.json
```

Il apprend quand même d'une exécution sans interface. Une correction que vous
faites après enseigne la même leçon qu'une session interactive.

---

## `comodor setup` — choisir un fournisseur et un modèle

```bash
comodor setup
```

Six questions, ou sept si un autre agent est installé et qu'il propose
d'importer. S'exécute automatiquement au premier lancement ; utilisez ceci pour
changer d'avis plus tard.

Les réponses vont dans `~/.comodor/config.json`.

---

## `comodor import` — depuis OpenClaw ou Hermes

```bash
comodor import             # bring keys, model and skills across
comodor import --dry-run   # say what it would take, change nothing
comodor import --keys-only # leave the skills and the model
```

Rien n'est déplacé et rien de ce qui est déjà configuré ici n'est remplacé.
Voir [Venir d'un autre agent](migrating.md).

---

## `comodor doctor` — tout va-t-il bien ?

```bash
comodor doctor
comodor doctor --fix
```

```
  ok    config file         ~/.comodor/config.json
  ok    config permissions  0o600
  ok    provider            Anthropic · claude-sonnet-5
  ok    model               claude-sonnet-5
  ok    spend limit         $2.00 per task
  ok    brain               ~/.comodor/brain.db
  ok    skills              4 loaded
  warn  version             0.8.9 installed; 0.9.0 is out
```

`--fix` répare ce qui est réparable — un nom de fournisseur périmé, un
répertoire manquant, un index de recherche cassé. Il ne change jamais rien
qu'il n'ait signalé d'abord.

Le code de sortie est non nul si quelque chose a échoué, ce qui le rend
utilisable dans une vérification de santé.

---

## `comodor web` — depuis un navigateur

```bash
comodor web                       # here, on 127.0.0.1:8765
comodor web --port 9000
comodor web --host 0.0.0.0        # reachable from elsewhere — read the warning
comodor web --no-browser          # do not open one
comodor web --token mytoken       # a fixed token instead of a fresh one
```

Guide complet : [Depuis un navigateur](web.md).

---

## `comodor telegram` — depuis votre téléphone

```bash
comodor telegram connect <token>  # a bot from @BotFather
comodor telegram pair             # a one-time code that adds your account
comodor telegram start            # here, holding this terminal
comodor telegram start -b         # detached; survives closing the terminal
comodor telegram stop             # end a background one
comodor telegram service install  # start it at login, so a reboot brings it back
comodor telegram service show     # read the unit before trusting it
comodor telegram status           # what is configured, who may talk, is it up
comodor telegram writes on        # let a phone turn edit files
comodor telegram writes off
comodor telegram forget 12345     # revoke one account
comodor telegram forget all
comodor telegram off              # stop without forgetting anything
```

La configuration du premier lancement propose tout cela comme dernière
question ; ces commandes servent à changer ensuite, ou pour une machine déjà
configurée.

Guide complet : [Depuis votre téléphone](telegram.md).

---

## `comodor slack` — depuis un espace de travail Slack

```bash
comodor slack manifest            # the app definition to paste into Slack
comodor slack connect             # the two tokens, checked as you paste them
comodor slack pair                # a one-time code that adds your account
comodor slack start               # here, holding this terminal
comodor slack start -b            # detached
comodor slack stop
comodor slack service install     # start it at login
comodor slack status              # what is set, who may talk, is it running
comodor slack writes on           # let a Slack turn edit files
comodor slack forget U01234567
comodor slack off
```

Environ cinq minutes, et aucune adresse publique : Socket Mode fait ouvrir à
l'application un websocket sortant plutôt que d'être sollicitée.

Guide complet : [Depuis Slack](slack.md).

---

## `comodor whatsapp` — depuis un numéro WhatsApp

```bash
comodor whatsapp connect          # guided: links each page, checks each value
comodor whatsapp connect --number-id … --token … --app-secret …
comodor whatsapp webhook          # what to paste into Meta's dashboard
comodor whatsapp pair             # a one-time code that adds your number
comodor whatsapp start            # here, holding this terminal
comodor whatsapp start --tunnel   # and bring a Cloudflare tunnel up with it
comodor whatsapp start -b         # detached
comodor whatsapp stop
comodor whatsapp service install  # start it at login
comodor whatsapp status           # what is set, who may talk, is it running
comodor whatsapp writes on        # let a phone turn edit files
comodor whatsapp forget 15551234567
comodor whatsapp off
```

Meta livre les messages vers une URL plutôt que de vous laisser les
interroger, donc celui-ci a besoin d'une adresse HTTPS publique. `connect` sans
arguments parcourt toute la configuration et démarre le tunnel lui-même ;
environ vingt minutes la première fois, la plupart du temps dans le tableau de
bord de Meta. Pas de vrai numéro, pas de carte, pas de vérification
d'entreprise.

Guide complet : [Depuis WhatsApp](whatsapp.md).

---

## `comodor skills` — des procédures qu'il suit

```bash
comodor skills browse             # what is available
comodor skills list               # what you have
comodor skills add review taste   # install some
comodor skills update             # refresh installed ones
comodor skills remove review
```

Guide complet : [Compétences](skills.md).

---

## `comodor mcp` — serveurs Model Context Protocol

```bash
comodor mcp list                  # what you have, and what it offers
comodor mcp catalogue             # what is available
comodor mcp add filesystem        # from the catalogue
comodor mcp custom NAME -- CMD    # a command of your own
comodor mcp remote NAME URL       # an HTTP server
comodor mcp enable NAME
comodor mcp disable NAME
comodor mcp remove NAME
comodor mcp test NAME             # connect and list its tools
```

Guide complet : [Serveurs MCP](mcp.md).

---

## `comodor update` — passer à la version la plus récente

```bash
comodor update --check     # what is out there, change nothing
comodor update             # do it
```

Il déduit comment cette copie a été installée — `uv`, `pipx`, `pip`, ou un
checkout des sources — et utilise le bon outil. Un checkout des sources est
laissé de côté : celui-là est à vous.

---

## `comodor uninstall` — le retirer complètement

```bash
comodor uninstall --dry-run    # list what would go
comodor uninstall              # ask, then do it
comodor uninstall --yes        # for scripts
```

```
Your data
  everything it has learned and everything you told it     4.2 MB
    ~/.comodor
    settings and your API key · 812 lessons · 47 sessions · 4 skills

In your projects
  api-server                                               128 KB
    ~/projects/api-server/.comodor
    checkpoints, project settings, project skills

The program
  the uv installation
    ~/.local/share/uv/tools/comodor

4.3 MB across 3 places. None of it can be undone.
```

Il nomme tout avant de retirer quoi que ce soit, et dit ce qu'il ne peut pas
trouver — un dossier `.comodor` dans un projet que vous avez utilisé mais dont
l'historique de sessions a été effacé ne peut pas être nommé, et il vous le dit
plutôt que de faire semblant.

---

## `comodor preview` — l'interface à une taille donnée

```bash
comodor preview 80x24
comodor preview 200x50 --svg wide.svg
```

Affiche une image puis quitte. Utile pour vérifier un terminal étroit, ou pour
une capture d'écran.

---

## Variables d'environnement

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, … | une clé, par fournisseur |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | forcer un fournisseur ou un modèle |
| `COMODOR_HOME` | où vivent configuration, cerveau et sessions |
| `COMODOR_BANNER=0` | pas de wordmark cette exécution |
| `COMODOR_NO_IMPORT=1` | ne pas proposer d'importer depuis un autre agent |
| `COMODOR_WEB_TOKEN` | un token fixe pour l'interface web |
| `NO_COLOR` | aucune couleur, respecté partout |

Une clé dans l'environnement n'est **jamais écrite dans votre fichier de
configuration**. En exporter une plutôt que de la sauvegarder est une décision,
et `/save` la respecte. Voir [Configuration](configuration.md).

---

## Codes de sortie

| | |
|---|---|
| `0` | cela a fonctionné |
| `1` | cela n'a pas fonctionné |
| `130` | vous l'avez interrompu |

---

## Voir aussi

- [L'interface](interface.md) — la même puissance, en interactif
- [Configuration](configuration.md) — rendre une option permanente
- [Dépannage](troubleshooting.md) — quand une commande ne fait pas ce qu'elle dit
