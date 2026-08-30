# L'interface

Ce que vous voyez, ce que vous pressez, et les 29 commandes.

```bash
comodor          # start it
comodor --demo   # the whole interface, offline, no key
```

---

## La disposition

```
┌────────────────────────────────────────────────────────────────────────┐
│  Comodor                              Anthropic · claude-sonnet-5      │
│  ────────────────────────────────────────────────────────────────────  │
│                                                                        │
│  TASKS                    > fix the failing parser test                │
│  ● read the test          ▸ read_file  tests/test_parser.py     0.1s   │
│  ◐ find the cause         ▸ run_shell  pytest tests/test_pa…    2.3s   │
│  ○ fix it                                                              │
│                           The test expects `parse("")` to raise, but…  │
│                                                                        │
│  ────────────────────────────────────────────────────────────────────  │
│  ▌Type a task, or / for commands                                       │
│                                                                        │
│  act · loop on · 12% of 1M · $0.03      ⏎ send  ^O attach  F3 mode     │
└────────────────────────────────────────────────────────────────────────┘
```

**La barre latérale** est le plan, quand il y en a un. `F2` la masque — cela
vaut la peine sur un terminal étroit.

**La ligne d'état** montre le mode, s'il itère, le remplissage du contexte, et
ce que cette session a coûté. Le chiffre du contexte est réel : il suit le
modèle, si bien que passer d'un modèle à un million de tokens à un modèle
128k le change immédiatement.

Cela fonctionne à partir d'environ 60 colonnes. En dessous, la barre latérale
se replie d'elle-même. `comodor preview 80x24` l'affiche à n'importe quelle
taille sans démarrer de session.

---

## Modes

| Mode | Ce que l'agent peut faire | |
|---|---|---|
| **act** | Tout, en demandant avant les écritures et les commandes | par défaut |
| **plan** | Lecture seule. Aucune écriture, aucune commande, aucun réseau | pour « que ferais-tu ? » |
| **chat** | Aucun outil du tout | pour une question sur du code que vous collez |

`F3` les fait défiler. `/mode plan` en fixe un directement.

Le mode plan est réellement en lecture seule — c'est appliqué à la couche de
permissions, pas en priant le modèle d'être gentil. Un outil dont le risque
dépasse « safe » est refusé avant de s'exécuter.

---

## Touches

| | |
|---|---|
| `Enter` | envoyer |
| `Ctrl+J` | saut de ligne dans un message |
| `Esc` | arrêter ce qu'il est en train de faire |
| `Ctrl+C` | arrêter ; deux fois pour quitter |
| `F1` | aide |
| `F2` | la barre latérale |
| `F3` | mode |
| `F4` | boucle activée/désactivée |
| `F5` | la passerelle |
| `Ctrl+O` | joindre un fichier |
| `Ctrl+L` | effacer la conversation |
| `PgUp` `PgDn` | faire défiler |
| `Ctrl+↑` `Ctrl+↓` | messages précédents et suivants |
| `!command` | exécuter une commande shell directement, sans demander au modèle |

`!` mérite d'être retenu. `!git status` l'exécute et vous montre la sortie ; le
modèle ne voit jamais la question. Moins cher et plus rapide que de demander.

---

## Commandes

Tapez `/` et la liste se filtre au fur et à mesure.

### Lui demander de changer ce qu'il est en train de faire

| | |
|---|---|
| `/mode [act\|plan\|chat]` | ce qui lui est permis |
| `/loop` | travailler jusqu'au bout, ou répondre une seule fois |
| `/model [id]` | choisir le modèle — une liste, ou en nommer un |
| `/provider [name]` | choisir le fournisseur |
| `/gw` | la passerelle : router entre fournisseurs selon le coût, la vitesse ou la qualité |

### L'enseigner

| | |
|---|---|
| `/good` | cette réponse était juste |
| `/bad` | cette réponse était fausse |
| `/teach <text>` | retiens ceci |
| `/memory` | ce qu'il a appris |
| `/rules` | les règles de la maison qu'il a tirées de votre code et de vos modifications |
| `/progress` | la preuve qu'il s'améliore |
| `/skills` | des procédures qu'il suit quand le travail correspond |

`/good` et `/bad` sont ce que vous pouvez faire de moins cher pour lui. Voir
[Comment il apprend](learning.md).

### Annuler et regarder en arrière

| | |
|---|---|
| `/undo` | restaurer le dernier fichier qu'il a changé |
| `/clear` | commencer une conversation neuve |
| `/resume [id]` | rouvrir une session antérieure |
| `/search <text>` | retrouver quelque chose dans une conversation antérieure |
| `/export [path]` | écrire cette session dans un fichier |

### Le pousser plus loin

| | |
|---|---|
| `/computer [15m\|1h this app\|stop]` | lui laisser votre écran — [guide](computer.md) |
| `/mcp` | serveurs MCP et leurs outils — [guide](mcp.md) |
| `/attach <path>` | ajouter un fichier au prochain message |

### L'apprivoiser

| | |
|---|---|
| `/settings` | ce qui est configuré en ce moment |
| `/approve [writes\|shell\|all]` | cesser de demander avant cela |
| `/theme [name]` | ember, midnight, matrix, mono |
| `/save` | écrire les réglages actuels dans votre fichier de configuration |
| `/cost` | tokens, dépense, et ce que le cache a économisé |
| `/copy [all\|task]` | la dernière réponse, ou tout, vers le presse-papiers |
| `/mouse [on\|off]` | suivi de la souris, pour que vous puissiez sélectionner du texte vous-même |
| `/help` | tout cela, dans l'interface |
| `/quit` | quitter |

**`/save` n'écrit que ce que vous avez choisi.** Pas les réglages du dépôt, pas
une clé que vous gardez dans votre environnement, pas un `--model` passé pour
une seule exécution. Voir
[Configuration](configuration.md#what-save-writes).

---

## Approbations

Quand l'agent veut écrire un fichier ou exécuter une commande :

```
  Write  src/parser.py
  ────────────────────────────────────────────
   - def parse(text):
   -     return text.split(",")
   + def parse(text):
   +     if not text:
   +         raise ValueError("nothing to parse")
   +     return text.split(",")

  [a] allow   [A] allow always this session   [d] deny
```

`A` retient pour la session, par type de chose — autoriser les écritures
n'autorise pas les commandes.

Refuser n'est pas perdu. Un refus est le signal de préférence le plus net que
l'interface collecte jamais, et il part vers le moteur d'apprentissage : il est
moins probable que l'agent le propose à nouveau.

Pour cesser d'être sollicité tout court :

```
/approve writes      files, yes; commands, still ask
/approve all         everything
```

Tout reste sauvegardé. `/undo` fonctionne quoi qu'il arrive.

---

## Copier du texte

Pendant que la souris est suivie, un glissement appartient à Comodor et le
terminal ne le voit jamais — l'habituel sélectionner-copier ne fonctionne
donc pas. Trois façons de contourner :

```
/copy              the last answer
/copy all          the whole conversation
/copy task         the last thing you asked for
/mouse             mouse tracking off, so selection works as usual
```

`/copy` ne demande rien d'installé sous Windows ni macOS. Sous Linux, il
utilise `wl-copy`, `xclip` ou `xsel`, selon celui qui est présent, et dit
lequel manque s'il n'y en a aucun.

Par SSH, il revient à une séquence d'échappement qui demande à *votre*
terminal de remplir *votre* presse-papiers — le texte d'un agent sur un serveur
atterrit donc là où vous pouvez le coller, plutôt que sur un serveur qui n'a
pas de presse-papiers.

La plupart des terminaux permettent aussi de sélectionner avec **Shift**
maintenu, ce qui contourne le suivi de la souris sans le désactiver.

---

## Qui parle

Chaque tour s'assoit sur une bande discrète — une nuance derrière ce que vous
avez tapé, une autre derrière la réponse :

```
▌ › why does the parser drop the last field?              ← warm

▌   Because split is called with a maxsplit of 2 …        ← neutral
▌
▌   ┌─ python ────────────────────────┐
▌   │ return text.split(',', 2)       │
▌   └─────────────────────────────────┘
```

Volontairement atténué. C'est derrière du texte courant que vous lisez pendant
des minutes d'affilée, et un arrière-plan qui a trop de présence se dispute les
mots. Chaque thème a sa propre paire, à quelques pour cent de son
arrière-plan ; `mono` n'en a pas, car un thème dont le principe est l'absence
de couleur n'en veut pas deux.

Elles ne coûtent aucun espace vertical — le changement de couleur est la
frontière.

---

## Texte de droite à gauche

Le persan, l'arabe et l'hébreu sont alignés à droite, là où leurs lignes
commencent, avec une pile de polices qui leur convient. Les paragraphes mixtes
— un identifiant anglais dans une phrase persane — sont traités par ligne
plutôt que par fichier, ce qui correspond à ce qui se passe réellement dans une
conversation technique.

---

## Thèmes

```
/theme midnight
```

`ember` (le défaut, ambre chaud), `midnight` (bleu froid), `matrix` (vert),
`mono` (aucune couleur).

`--ascii` remplace les caractères de tracé de cadre par de l'ASCII, pour les
terminaux qui n'en ont pas. `NO_COLOR` dans votre environnement est respecté.

---

## Voir aussi

- [Depuis le terminal](cli.md) — la même puissance sans l'interface
- [Ce que l'agent peut faire](tools.md) — les outils derrière ces lignes `▸`
- [Sécurité](safety.md) — ce que les demandes d'approbation protègent
