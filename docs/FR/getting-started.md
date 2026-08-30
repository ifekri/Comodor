# Premiers pas

Cinq minutes, qui se terminent avec l'agent faisant quelque chose d'utile.

---

## 1. Installer

Une seule ligne. Il déduit le reste.

**macOS · Linux · BSD**

```bash
curl -fsSL get.comodor.ai | sh
```

**Windows** — PowerShell

```powershell
irm get.comodor.ai | iex
```

```
Comodor — it learns the way you correct it.

  Linux x86_64
> Installing uv, a package manager Comodor needs (about 15 MB)
  from https://astral.sh/uv — it fetches a Python too, if one is missing
> Installing with uv

✓ comodor 0.9.0

  Linked into /usr/local/bin, which is on your PATH.

  comodor              start the interface
  comodor --demo       try it offline, no API key needed
  comodor doctor       check what is configured
```

**Une seule adresse pour tous.** `get.comodor.ai` ne nomme aucun fichier. Il
lit quel client demande et envoie `curl` et `wget` vers l'installateur shell,
PowerShell vers celui de Windows, et un navigateur vers cette page — la ligne
à coller est donc la même sur chaque système, et vous n'avez jamais à choisir.

**Il va au bout.** Quelqu'un qui lance une ligne depuis une page web n'a pas
accepté de déboguer quoi que ce soit, donc le script installe ce dont il a
besoin — un environnement isolé, un gestionnaire de paquets, un Python —
plutôt que de s'arrêter pour expliquer ce que vous auriez déjà dû avoir.
Vérifié sur un `debian:bookworm-slim` nu, sans aucun Python.

### Presque toujours, rien à taper ensuite

Quand il le peut, il place `comodor` quelque part où votre shell regarde déjà,
si bien que cela fonctionne dans le terminal depuis lequel vous l'avez lancé —
pas de `export`, pas de nouvelle fenêtre. Cela couvre root, les conteneurs,
l'IC, et tout Mac avec Homebrew.

Quand il ne le peut pas — un compte Linux ordinaire, où rien sur `PATH` n'est
inscriptible — aucun installateur ne peut aider, car un processus enfant ne
peut pas modifier l'environnement du shell qui l'a lancé. Alors il le dit :

```
  Every new terminal can run comodor already.
  This one started before the install, and no installer
  can reach back into the shell that ran it. For this
  terminal only:

    export PATH="/home/you/.local/bin:$PATH"
```

Ouvrez un nouveau terminal et cela fonctionne simplement. La ligne est ajoutée
à la fois dans le fichier rc de votre shell et dans votre profil de connexion,
pour que chaque type de shell la trouve — interactif, login, non interactif,
et session de bureau.

### Si vous préférez ne pas rediriger un script vers un shell

C'est tout à fait raisonnable. Les deux scripts sont du texte brut que vous
pouvez lire d'abord — nommés directement, car la courte adresse envoie tout ce
qui n'est pas un récupérateur vers la page :

```bash
curl -fsSL https://comodor.ai/install.sh  | less
curl -fsSL https://comodor.ai/install.ps1 | less
```

Ou utilisez un gestionnaire de paquets que vous avez déjà :

```bash
uv tool install comodor      # isolated, and the fastest
pipx install comodor         # isolated
pip install comodor          # into whatever environment you are in
```

Comodor a besoin de **Python 3.11 ou plus récent**, et de rien d'autre.

### Vérifier qu'il est bien arrivé

```bash
comodor --version
```

Si le shell ne le trouve pas, l'installateur a ajouté un répertoire à votre
`PATH` que ce terminal ne connaît pas encore. Ouvrez-en un nouveau, ou lancez
la ligne `export` affichée par l'installateur.

### Les options comprises par les installateurs

| | |
|---|---|
| `COMODOR_FORCE_TOOL` | imposer la méthode : `uv`, `pipx`, `venv` ou `pip` |
| `COMODOR_NO_BOOTSTRAP` | ne jamais télécharger d'outil ; échouer à la place |
| `COMODOR_NO_MODIFY_PATH` | ne pas toucher au profil de votre shell |
| `COMODOR_INSTALL_REF` | installer depuis une référence git ou un chemin local plutôt que depuis PyPI |

```bash
COMODOR_NO_MODIFY_PATH=1 curl -fsSL get.comodor.ai | sh
```

> **Pas certain de vouloir l'installer tout de suite ?** `comodor --demo` lance
> toute l'interface contre un fournisseur hors ligne scripté. Pas de clé, pas
> de compte, pas de réseau.

---

## 2. Choisir un modèle

Lancez-le. La première fois, il pose six questions et ne les re pose jamais.

```bash
comodor
```

```
 1/6  Which model provider?
┌─  Providers  ───────────────────────────────────────────┐
│ ›  OpenRouter        One key, hundreds of models         │
│    Anthropic         Claude, direct from the source      │
│    OpenAI            GPT models, direct                  │
│    Ollama (local)    Runs on your machine. No key        │
└──────────────────────────────────────────────────────────┘
  ↑↓ move   enter choose   tab more   esc cancel
```

Touches fléchées, ou tapez pour filtrer. **Tab** ouvre la description complète
de l'élément pointé par la flèche, dans le même cadre — les listes affichent
une ligne par entrée pour tenir à l'écran, et certaines de ces descriptions
font un paragraphe.

Redirigé ou scripté, les mêmes questions arrivent sous forme de liste numérotée,
pour que tout puisse être automatisé.

**Pas de clé et pas d'argent ?** Choisissez **Ollama** ou **LM Studio**. Ils
tournent sur votre machine, ne demandent aucune clé et ne coûtent rien. Tout ce
que dit cette documentation fonctionne avec eux, sauf les parties qui précisent
le contraire.

**Vous utilisez déjà OpenClaw ou Hermes ?** Le premier écran propose de
rapporter vos clés, votre modèle et vos compétences. Rien n'est déplacé et rien
de ce qui est déjà configuré ici n'est remplacé. Voir
[Venir d'un autre agent](migrating.md).

Vos réponses vont dans `~/.comodor/config.json`, lisible uniquement par vous.
Changez d'avis plus tard avec `comodor setup`, ou un réglage à la fois — voir
[Configuration](configuration.md).

### La dernière question, c'est votre téléphone

```
 6/6  Run it from your phone?
┌─  From your phone  ─────────────────────────────────────────────┐
│ ›  Not now    you can set any of them up later                   │
│    Telegram   one token from @BotFather — about a minute         │
│    Slack      an app from a manifest, two tokens — five minutes  │
│    WhatsApp   a Meta app and a public address — twenty minutes   │
└──────────────────────────────────────────────────────────────────┘
```

**Telegram** prend un token auprès de [@BotFather](https://t.me/botfather), le
vérifie auprès de Telegram immédiatement, et affiche un code à envoyer au bot
pour qu'il sache quel compte servir — une minute, du début à la fin.
Voir [Depuis votre téléphone](telegram.md).

**Slack** en prend environ cinq. L'application est créée à partir d'un manifest
que Comodor affiche, si bien que c'est un seul collage plutôt qu'une page de
cases à cocher, et Socket Mode signifie aucune adresse publique du tout — voir
[Depuis Slack](slack.md).

**WhatsApp** fait la même chose et prend environ vingt minutes : une
application Meta, un numéro professionnel, un secret d'application et une
adresse HTTPS publique, dont aucun ne peut être créé depuis un terminal. Cela
ne vaut la peine que si cela doit être WhatsApp — voir
[Depuis WhatsApp](whatsapp.md).

Dans tous les cas il ne lit et ne planifie que jusqu'à ce que vous disiez le
contraire, et refuser coûte une seule touche.

### Puis il propose de démarrer

```
 What now?
   1  Start Comodor          — the interface, here in this terminal
   2  Start the Telegram bot — in the background, answers while this is closed
   3  Both
   4  Nothing yet            — `comodor` starts it whenever you want
```

La configuration se terminait autrefois ici, au prompt du shell, sans rien qui
tourne. Une ligne de téléphone apparaît pour chaque canal connecté et appairé,
nommé — quelqu'un qui a configuré WhatsApp ne se voit pas proposer « the
Telegram bot ».

---

## 3. Il demande dans quel dossier

```
  Work in  /home/you/projects/api-server ?
```

Posé une seule fois par dossier. Tout ce que l'agent peut toucher est dedans —
il ne peut pas lire ou écrire dehors sans que vous désactiviez cela
délibérément. Les dossiers approuvés sont mémorisés.

---

## 4. Demander quelque chose

Tapez-le et appuyez sur Entrée.

```
> the tests in tests/test_parser.py are failing, work out why and fix it
```

Il va lire des fichiers, lancer les tests, et changer quelque chose. Avant
d'écrire un fichier, vous recevez un diff et un choix :

```
  Write  src/parser.py
    - 12 lines removed, 8 added
  [a] allow   [A] allow always this session   [d] deny
```

Répondez `a` une fois, ou `A` si vous préférez qu'il cesse de demander pour le
reste de la session. Chaque écriture est sauvegardée dans tous les cas :
`/undo` restaure la précédente.

---

## 5. Le corriger — c'est la partie qui compte

Quand il se trompe, dites-le-lui. Deux façons, qui lui enseignent la même
chose :

**Modifiez le fichier vous-même.** Comodor remarque ce que vous changez dans
ses résultats.

**Dites-le.**

```
> no — we use single quotes in this codebase, not double
```

Dans tous les cas cela devient une leçon : rappelée la prochaine fois que la
situation semble similaire, avec une confiance qui monte quand elle se vérifie
et décroît quand elle ne se vérifie pas.

Après quelques sessions :

```
> /progress
```

```
◈ Corrections per task down 100% since the first tasks in this project.

metric                trend                       now  vs first
Steps per task        ▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇    6.1      ↑10%
Corrections per task  ████████▅▅▅▅▅▅▅▅▁▁▁▁▁▁▁▁    0.0     ↓100%
Approvals asked       ▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅    2.0         —
Tokens per task       ▁▁▁▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▇▇▇███  12.0K      ↑40%
First-try success     ▁██████▁██████▁██████▁██    86%         —

brain    7 rules · 812 lessons · 24 corrections learned from
history  24 tasks over 8 days
success  83% overall
```

C'est une preuve, pas une affirmation. Si le taux de corrections ne baisse pas,
l'apprentissage ne fonctionne pas, et le panneau le dit plutôt que de le
cacher.

[Comment il apprend](learning.md) explique le mécanisme.

---

## 6. Ce qu'il vaut la peine de savoir dès le premier jour

```
/help          every command
/mode          act · plan (read-only) · chat (no tools)     F3 cycles
/undo          restore the last file it changed
/cost          tokens, spend, what the cache saved
Esc            stop it, mid-thought
Ctrl-C twice   leave
```

---

## Pour aller plus loin

| Vous voulez | À lire |
|---|---|
| L'utiliser sans l'interface, dans un script | [Depuis le terminal](cli.md) |
| Savoir exactement ce qu'il peut faire à votre machine | [Sécurité et permissions](safety.md) |
| Payer moins | [Coût](cost.md) |
| Lui laisser utiliser un navigateur | [Le vrai navigateur](browser.md) |
| Lui laisser utiliser votre souris et votre clavier | [Utiliser votre écran](computer.md) |
| Écrire une procédure qu'il suit à chaque fois | [Compétences](skills.md) |
| Le lancer sur un serveur, ou dans Docker | [Depuis un navigateur](web.md), [Dans Docker](docker.md) |

---

## Si quelque chose a mal tourné

```bash
comodor doctor
```

Il vérifie tout ce qu'il peut et vous dit quoi faire de tout ce qu'il trouve.
`comodor doctor --fix` répare ce qui est réparable. Voir
[Dépannage](troubleshooting.md).
