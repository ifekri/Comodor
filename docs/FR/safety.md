# Sécurité et permissions

Ce que Comodor peut faire à votre machine, ce qu'il demande d'abord, et ce
qu'il ne fera pas quoi que vous disiez.

---

## La version courte

- **Lire se fait en silence.** Lister des fichiers, les lire, chercher — aucune
  invite.
- **Écrire demande.** Vous voyez le diff avant que cela arrive.
- **Exécuter une commande demande plus fort**, et il en va de même pour
  atteindre le réseau ou piloter votre écran.
- **Tout ce qui est réversible est annulé par `/undo`.**
- **Il ne peut pas sortir du dossier du projet** à moins que vous ne le
  désactiviez.
- **Un dépôt ne peut rien changer de tout ce qui précède.**

---

## Niveaux de risque

Chaque outil en déclare un. Le niveau décide de ce qui arrive avant son
exécution.

| Niveau | Outils | Ce qui arrive |
|---|---|---|
| **safe** | `read_file`, `list_dir`, `grep`, `glob`, `todo_write` | s'exécute |
| **write** | `write_file`, `edit_file` | demande, avec un diff |
| **dangerous** | `run_shell`, `run_python`, `web_fetch`, `web_search`, `browse`, `computer` | demande |

En **mode plan**, tout ce qui dépasse `safe` est refusé avant de s'exécuter.
Cela est appliqué à la couche de permissions, pas en demandant au modèle d'être
sage.

En **mode chat**, il n'y a aucun outil du tout.

---

## L'invite

```
  Run  pytest tests/ -x
  ────────────────────────────────────────────
  in ~/projects/api-server

  [a] allow   [A] allow always this session   [d] deny
```

`A` retient pour la session, par type de chose — autoriser les écritures
n'autorise pas les commandes, et autoriser `pytest` n'autorise pas `rm`.

Pour cesser d'être sollicité :

```
/approve writes      files yes, commands still ask
/approve shell       commands yes, files still ask
/approve all         everything
```

Ou de façon permanente, dans votre configuration :

```json
{
  "safety": {
    "auto_approve_writes": true,
    "auto_approve_shell": false
  }
}
```

### Refuser l'enseigne

Un refus est le signal de préférence le plus net que l'interface collecte
jamais. Il part vers le moteur d'apprentissage, si bien qu'il est moins
probable que l'agent propose la même chose à nouveau. Refuser n'est pas un
effort perdu.

---

## Points de contrôle et `/undo`

Chaque fichier que l'agent écrit est sauvegardé d'abord — le contenu
précédent, conservé sous `.comodor/checkpoints/` dans le projet.

```
/undo
```

restaure le dernier fichier qu'il a changé. Cela fonctionne que vous ayez
approuvé l'écriture ou non, et que l'auto-approbation soit active ou non. C'est
la raison pour laquelle `/approve all` est une chose raisonnable à faire.

Désactivez-le s'il le faut :

```json
{ "safety": { "checkpoints": false } }
```

Il n'y a aucune bonne raison de le faire.

---

## La frontière de l'espace de travail

L'agent peut lire et écrire **dans le dossier du projet et nulle part
ailleurs**.

La racine du projet est trouvée en remontant depuis là où vous avez démarré
jusqu'à ce que quelque chose dise « ceci est un projet » — un `.git`, un
`pyproject.toml`, un `package.json`. On vous le montre et on vous le demande,
une fois par dossier :

```
  Work in  /home/you/projects/api-server ?
```

Les dossiers approuvés sont mémorisés. `--cwd` en nomme un directement et ne
demande pas.

```json
{ "safety": { "workspace_only": true } }
```

Désactiver cela laisse l'agent toucher tout votre système de fichiers. Il est
interdit à la configuration d'un dépôt précisément pour cette raison.

---

## Les commandes qu'il n'exécutera pas

Certaines choses sont refusées avant que toute invite n'apparaisse, car aucune
invite ne devrait pouvoir pousser une personne à les accepter au bout d'une
longue session :

```
rm -rf /     rm -rf ~     mkfs        dd if=      shutdown
reboot       format c:    del /f /s /q c:         :(){
> /dev/sda   chmod -R 777 /
```

La liste complète est `safety.deny_commands`. Ajoutez les vôtres :

```json
{
  "safety": {
    "deny_commands": ["terraform destroy", "kubectl delete namespace"]
  }
}
```

`safety.allow_commands` est l'autre sens — des commandes qui ne sollicitent
jamais :

```json
{ "safety": { "allow_commands": ["git status", "pytest", "ls"] } }
```

---

## Vos clés

**Où elles vivent.** Votre propre `~/.comodor/config.json`, écrit avec des
permissions réservées au propriétaire, ou votre environnement. Nulle part
ailleurs.

**Où elles ne vont jamais.** Pas dans la configuration d'un dépôt. Pas dans
l'interface. Pas dans un journal. Pas dans un `repr` — celui-là fut un vrai
bogue, trouvé et corrigé : toute trace d'erreur nommant une Config imprimait la
clé, et pytest imprime des traces d'erreur en permanence.

**Une clé dans votre environnement y reste.** Si vous exportez
`ANTHROPIC_API_KEY` plutôt que de la sauvegarder, `/save` ne la copiera pas
dans votre fichier de configuration. L'exporter plutôt que la sauvegarder est
une décision et elle est respectée.

**Occultation.** Tout ce qui ressemble à l'une de vos clés est masqué dans la
sortie des outils, dans la transcription, et dans les exports. Cela fonctionne
sur du texte. Cela ne peut pas lire les pixels — voir
[Utiliser votre écran](computer.md#what-goes-to-the-model).

---

## Ce qu'un dépôt peut définir

Un `.comodor/config.json` dans un projet est lu depuis le répertoire où vous
avez démarré — ce qui, pour un agent de codage, signifie *depuis un dépôt
écrit par quelqu'un d'autre, immédiatement après l'avoir cloné*.

Il est donc restreint aux choses qui ne peuvent pas être retournées contre
vous :

| Un projet peut définir | |
|---|---|
| `provider`, `model` | quel modèle utiliser |
| `agent` | mode, boucle, les budgets, la température, la taille de sortie |
| `ui` | thème, bordures, bannière |
| `learning`, `skills` | s'ils sont actifs, et leurs limites |
| `mcp.servers` | quels serveurs il utilise — **en arrivant désactivés** |

| Un projet ne peut **pas** définir | parce que |
|---|---|
| `providers.*.base_url` | votre clé partirait vers leur serveur à la première requête |
| `safety.*` | il pourrait empêcher l'agent de demander, ou vider la liste d'interdiction |
| `agent.system_prompt_extra` | des instructions injectées avec votre autorité |
| `browser.executable` | il nomme un binaire que l'agent doit lancer |
| `computer.*` | il demande à la machine sur laquelle il vient d'être cloné votre souris |
| `mcp.enabled` | déclarer un serveur est une suggestion ; en démarrer un est une décision |

C'est une **liste blanche**, pas une liste noire, donc un réglage ajouté
l'année prochaine reste non fiable jusqu'à ce que quelqu'un décide autrement —
la bonne façon d'avoir tort.

Les refus sont dits à voix haute :

```
config: this project cannot set safety, computer — only your own can
```

Ignorer silencieusement le fichier de quelqu'un est ainsi qu'un fichier de
configuration se bâtit une réputation de non-fonctionnement.

---

## Plafonds

Trois, et ils s'appliquent à chaque tâche :

```json
{
  "agent": {
    "max_steps": 24,
    "max_seconds": 900,
    "max_cost_usd": 2.0
  }
}
```

**Celui de l'argent ne fonctionne que pour un modèle avec un tarif publié.**
Pour un modèle que le tableau des tarifs ne connaît pas, le compteur de coût
affiche zéro et la limite ne se déclenche jamais. Comodor le dit plutôt que de
vous laisser croire que vous avez un plafond :

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Dit au début d'une session et dans `comodor doctor`. Voir [Coût](cost.md).

---

## Sous-agents

`delegate` lance un sous-agent dans un git worktree — une copie isolée du
dépôt. Il n'a pas de mémoire, ne peut pas déléguer davantage, et **ne reçoit
pas l'écran** : un sous-agent qui travaille dans un worktree n'a rien à faire
de votre souris.

---

## Signaler quelque chose

Si vous trouvez un problème de sécurité, merci de ne pas ouvrir un ticket
public. Voir [SECURITY.md](../SECURITY.md).

---

## Voir aussi

- [Utiliser votre écran](computer.md) — le modèle de permissions le plus strict d'ici
- [Configuration](configuration.md) — où vit chaque réglage
- [L'interface](interface.md#approvals) — à quoi ressemblent les invites
