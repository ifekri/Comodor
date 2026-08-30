# Configuration

Un fichier JSON que vous n'avez jamais besoin d'éditer à la main — mais voici
tout ce qu'il contient.

---

## Où vivent les choses

| | |
|---|---|
| `~/.comodor/config.json` | le vôtre. L'assistant l'écrit ; permissions réservées au propriétaire |
| `~/.comodor/brain.db` | ce qu'il a appris |
| `~/.comodor/sessions/` | chaque conversation |
| `~/.comodor/skills/` | les compétences que vous avez installées ou écrites |
| `./.comodor/config.json` | celui du projet. Sûr à committer — voir [ce qu'il peut définir](safety.md#what-a-repository-may-set) |
| `./.comodor/checkpoints/` | le contenu précédent de chaque fichier qu'il a changé |

Sous Windows, `~/.comodor` est `%APPDATA%\Comodor`. `COMODOR_HOME` l'emporte
partout.

```bash
comodor doctor      # tells you exactly where all of these are
```

---

## Ce qui prime

Quatre couches. Ce qui vient après l'emporte sur ce qui vient avant.

```
1. built-in defaults
2. ~/.comodor/config.json         yours
3. ./.comodor/config.json         the project's — restricted
4. environment variables          ANTHROPIC_API_KEY, COMODOR_MODEL, …
5. the command line               --model, --mode, … for one run
```

### Ce que `/save` écrit

**Seulement ce que vous avez choisi.** Cela compte plus qu'il n'y paraît.

La configuration sur laquelle l'agent tourne est la fusion des quatre couches.
La réécrire dans votre fichier ferait du plafond de dépense d'un dépôt cloné
votre défaut global permanent, et copierait sur le disque une clé API que vous
avez délibérément gardée dans votre environnement.

Donc `/save` se souvient d'où vient chaque valeur. Une valeur qui garde encore
ce qu'une couche empruntée fournissait revient à ce que disait *votre* fichier ;
une valeur que vous avez changée pendant la session est à vous et est écrite.

- `/model x` puis `/save` → persiste `x`
- `/save` dans un dépôt qui fige `max_cost_usd: 500` → ne persiste rien de tel
- `/save` avec `ANTHROPIC_API_KEY` exportée → la clé reste dans votre
  environnement

---

## Chaque réglage

### `provider` et `model`

```json
{ "provider": "anthropic", "model": "claude-sonnet-5" }
```

Voir [Choisir un modèle](models.md).

### `agent` — comment il fonctionne

```json
{
  "agent": {
    "mode": "act",
    "loop": true,
    "max_steps": 0,
    "max_seconds": 3600.0,
    "max_cost_usd": 2.0,
    "context_limit": 1000000,
    "compact_at": 0.75,
    "temperature": 0.3,
    "max_output_tokens": 8192,
    "max_tool_chars": 12000,
    "keep_screenshots": 2,
    "system_prompt_extra": "",
    "prompt_cache": true,
    "prompt_cache_ttl": "5m"
  }
}
```

| | |
|---|---|
| `mode` | `act`, `plan` (lecture seule), `chat` (aucun outil) |
| `loop` | travailler jusqu'au bout, ou répondre une seule fois |
| `max_steps` | **`0` — aucune limite, et c'est le défaut.** Un refactor traversant une douzaine de fichiers est tombé à court de vingt-quatre pas en pleine réflexion, et un nombre de pas n'a aucun rapport avec le danger. Fixez un nombre pour la ramener |
| `max_seconds` | une heure. `0` pour aucune limite |
| `max_cost_usd` | le plafond qui correspond à ce que coûte un dérapage — [quand le modèle a un tarif publié](cost.md#when-the-limit-cannot-fire). `0` pour aucune limite |
| `context_limit` | la jauge. Suit le modèle automatiquement quand vous changez |
| `compact_at` | résume l'historique au-delà de cette fraction de la limite |
| `max_tool_chars` | quelle part d'un résultat d'outil atteint le modèle. Le reste est écrit dans un fichier qu'on lui apprend à lire — pas tronqué |
| `keep_screenshots` | combien restent dans la conversation. [Pourquoi](computer.md#screenshots-and-what-they-cost) |
| `system_prompt_extra` | vos propres instructions permanentes |
| `prompt_cache` | laisser le fournisseur re-servir le préfixe inchangé. [Coût](cost.md) |
| `prompt_cache_ttl` | `5m` ou `1h`. L'heure coûte plus cher à l'écriture |

### `safety` — ce qu'il peut faire

```json
{
  "safety": {
    "auto_approve_safe": true,
    "auto_approve_writes": false,
    "auto_approve_shell": false,
    "checkpoints": true,
    "workspace_only": true,
    "allow_commands": [],
    "deny_commands": ["rm -rf /", "..."],
    "max_file_read_bytes": 512000,
    "max_file_scan_bytes": 64000000,
    "trusted_folders": []
  }
}
```

Explication complète : [Sécurité et permissions](safety.md).

### `learning` — ce dont il se souvient

```json
{
  "learning": {
    "enabled": true,
    "top_k": 6,
    "max_playbook_tokens": 800,
    "reflect": true,
    "reflect_model": "",
    "min_confidence": 0.15,
    "half_life_days": 45.0,
    "share_scope": "project",
    "associative": true,
    "corrections": true,
    "rules": true,
    "announce": true,
    "prefetch": true
  }
}
```

| | |
|---|---|
| `top_k` | leçons rappelées par tour |
| `max_playbook_tokens` | plafond strict sur ce que le rappel peut injecter |
| `reflect` | distiller des leçons après une tâche — celui-ci coûte un appel au modèle |
| `reflect_model` | un modèle moins cher pour cela, si vous voulez |
| `half_life_days` | la vitesse à laquelle une leçon inutilisée s'estompe |
| `share_scope` | `project` ou `global` |
| `corrections`, `rules`, `announce`, `prefetch` | la voie rapide — gratuit, sans appel au modèle, actif même quand `reflect` est désactivé |

Explication complète : [Comment il apprend](learning.md).

### `ui` — son apparence

```json
{
  "ui": {
    "theme": "ember",
    "ascii_borders": false,
    "mouse": true,
    "max_fps": 20,
    "show_timestamps": false,
    "sidebar": true,
    "banner": true,
    "syntax_theme": ""
  }
}
```

`banner: false` désactive le wordmark pour de bon ; `COMODOR_BANNER=0` ne le
fait que pour une exécution.

### `skills` — procédures

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000,
    "install_examples": true
  }
}
```

Explication complète : [Compétences](skills.md).

### `telegram` — depuis votre téléphone

```json
{
  "telegram": {
    "enabled": false,
    "token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300
  }
}
```

| | |
|---|---|
| `enabled` | si `comodor telegram start` lance le bot |
| `token` | celui de [@BotFather](https://t.me/botfather). La configuration du premier lancement le demande, ou `comodor telegram connect` |
| `allowed` | les identifiants numériques d'utilisateurs Telegram auxquels il répond, et personne d'autre. Rempli par `comodor telegram pair`, jamais par Telegram lui-même |
| `allow_writes` | si un tour commencé depuis un téléphone peut modifier des fichiers et exécuter des commandes. Désactivé, il reste en mode plan quel que soit le réglage du terminal |
| `pair_window` | secondes pendant lesquelles un code d'appairage reste valable |

**Le `.comodor/config.json` d'un projet ne peut rien définir de tout cela.** Un
dépôt qui pourrait ajouter un compte à `allowed` serait une porte dérobée, et
contrairement au navigateur ou à l'écran, il n'y aurait rien de visible pendant
que cela arrive.

Explication complète : [Depuis votre téléphone](telegram.md).

### `slack` — depuis un espace de travail Slack

```json
{
  "slack": {
    "enabled": false,
    "bot_token": "",
    "app_token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300,
    "team": ""
  }
}
```

| | |
|---|---|
| `bot_token` | `xoxb-…` issu de OAuth & Permissions. Fait tout ce que fait le bot |
| `app_token` | `xapp-…` issu de Basic Information, scope `connections:write`. Ouvre le websocket de Socket Mode, et rien d'autre |
| `allowed` | Les identifiants d'utilisateurs Slack auxquels il répond. Pas les noms affichés : un nom affiché peut être changé par la personne qui le détient |
| `allow_writes` | Si un tour Slack peut modifier des fichiers et exécuter des commandes |
| `pair_window` | Secondes pendant lesquelles un code d'appairage reste valable |
| `team` | L'espace de travail auquel il était connecté, mémorisé pour que `status` puisse le nommer sans aller-retour |

**Le `.comodor/config.json` d'un projet ne peut rien définir de tout cela**,
pour la même raison que les autres : un dépôt qui pourrait ajouter un compte à
`allowed` serait une porte dérobée.

Explication complète : [Depuis Slack](slack.md).

### `whatsapp` — depuis un numéro WhatsApp

```json
{
  "whatsapp": {
    "enabled": false,
    "token": "",
    "phone_number_id": "",
    "app_secret": "",
    "verify_token": "",
    "allowed": [],
    "allow_writes": false,
    "host": "127.0.0.1",
    "port": 8770,
    "path": "/whatsapp",
    "public_url": "",
    "api_version": "v21.0"
  }
}
```

| | |
|---|---|
| `token` | Un token d'accès Meta. Un token d'Utilisateur Système n'expire pas ; celui du tableau de bord dure 24 heures |
| `phone_number_id` | L'identifiant numérique que Meta affiche à côté du numéro, pas le numéro |
| `app_secret` | Chaque webhook est signé avec lui. Sans lui, rien n'est vérifié |
| `verify_token` | Renvoyé pendant la poignée de main unique de Meta. Généré, pas choisi |
| `allowed` | Les numéros auxquels il répond, comparés en chiffres. Tout le reste reçoit le silence |
| `allow_writes` | Si un tour WhatsApp peut modifier des fichiers et exécuter des commandes |
| `host`, `port`, `path` | Où le webhook écoute. En local, derrière quelque chose qui termine TLS |
| `public_url` | L'adresse vers laquelle Meta livre, mémorisée pour que `whatsapp webhook` puisse l'afficher |
| `api_version` | Figé, parce que Meta déprécie les versions selon leur calendrier, pas le vôtre |

**Le `.comodor/config.json` d'un projet ne peut rien définir de tout cela**,
pour la même raison que `telegram` : un dépôt qui pourrait ajouter un numéro à
`allowed` serait une porte dérobée sans rien à l'écran pour montrer que cela
arrive.

Explication complète : [Depuis WhatsApp](whatsapp.md).

### `browser` — le vrai navigateur

```json
{
  "browser": {
    "executable": "",
    "headless": true,
    "width": 1280,
    "height": 800,
    "port": 0
  }
}
```

`headless: false` est la façon de le regarder travailler. `port` se rattache à
un navigateur que vous avez démarré vous-même, pour qu'il puisse utiliser une
session où vous êtes déjà connecté plutôt que de recevoir votre profil.

Explication complète : [Le vrai navigateur](browser.md).

### `computer` — votre écran

```json
{
  "computer": {
    "enabled": false,
    "screenshot_tokens": 1600,
    "grant_seconds": 900,
    "travel_seconds": 0.32,
    "overlay": true,
    "never": []
  }
}
```

Explication complète : [Utiliser votre écran](computer.md).

### `gateway` — router entre fournisseurs

```json
{
  "gateway": {
    "enabled": false,
    "policy": "quality",
    "chain": [],
    "failure_threshold": 3,
    "cooldown_seconds": 60.0
  }
}
```

`policy` vaut `cost`, `speed` ou `quality`. Avec `enabled: true`, il choisit
dans `chain` et passe outre un fournisseur qui échoue sans cesse. `F5` ou `/gw`
dans l'interface.

### `mcp` — serveurs Model Context Protocol

```json
{
  "mcp": {
    "enabled": true,
    "servers": { }
  }
}
```

Géré avec `comodor mcp`, pas à la main. [Serveurs MCP](mcp.md).

---

## Variables d'environnement

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, … | une par fournisseur |
| `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODEL` | remplacer un point de terminaison ou un modèle |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | forcer l'un ou l'autre |
| `COMODOR_HOME` | où tout vit |
| `COMODOR_BANNER=0` | pas de wordmark |
| `COMODOR_NO_IMPORT=1` | ne pas proposer d'importer depuis un autre agent |
| `COMODOR_WEB_TOKEN` | un token fixe pour l'interface web |
| `NO_COLOR` | aucune couleur |

---

## Quand un réglage ne prend pas effet

Comodor le dit plutôt que de vous ignorer :

```
config: agent.max_steps must be a whole number; keeping 24
config: this project cannot set safety, computer — only your own can
```

Une valeur du mauvais type est convertie quand c'est sans ambiguïté, refusée
quand ce ne l'est pas, et le refus nomme la clé et ce qui était attendu. `null`
ne remplace pas silencieusement une chaîne par `None`.

Si un réglage semble encore ne rien faire :

```bash
comodor doctor          # what it actually loaded
```

```
/settings               # the same, in the interface
```
