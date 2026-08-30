# Ce que l'agent peut faire

Treize outils. Chacun déclare un niveau de risque, qui décide s'il demande
d'abord — voir [Sécurité](safety.md#risk-tiers).

---

## Fichiers

| | Risque | |
|---|---|---|
| `read_file` | safe | Lire un fichier texte. En flux, pour qu'une tranche d'un gros journal reste accessible |
| `list_dir` | safe | Les entrées d'un répertoire, avec leurs tailles |
| `glob` | safe | Trouver des fichiers par motif de nom — `src/**/*.py` |
| `grep` | safe | Chercher dans le contenu avec une expression régulière |
| `write_file` | write | Créer un fichier ou le remplacer entièrement |
| `edit_file` | write | Remplacer une chaîne exacte dans un fichier |

Tout est confiné au dossier du projet, sauf si vous désactivez
`safety.workspace_only`.

`edit_file` est préféré à `write_file` pour une modification d'un fichier
existant : c'est plus petit, cela se relit comme un diff, et cela ne peut pas
perdre silencieusement le reste du fichier.

---

## Exécuter des choses

| | Risque | |
|---|---|---|
| `run_shell` | dangerous | Une commande shell dans l'espace de travail |
| `run_python` | dangerous | Un court extrait Python, dans un sous-processus |

Tous deux demandent avant d'exécuter, tous deux sont soumis à
`safety.deny_commands`, et tous deux ont leur sortie bornée — voir
[Quand la sortie est trop grosse](#when-output-is-too-big).

Dans l'interface, vous pouvez sauter le modèle entièrement :

```
!git status
```

Cela l'exécute, vous montre la sortie, et n'en parle jamais au modèle. Plus
rapide et moins cher que de demander.

---

## Le web

| | Risque | |
|---|---|---|
| `web_fetch` | dangerous | Télécharger une URL et renvoyer son texte lisible |
| `web_search` | dangerous | Chercher, et renvoyer titres, URLs et extraits |
| `browse` | dangerous | Un vrai navigateur — JavaScript, cookies, connexions |

`web_fetch` est le moins cher : il réduit la page à du texte. Utilisez-le quand
la page est un document.

`browse` est pour quand c'est une application — quelque chose qui exige du
JavaScript, une connexion, ou un clic. [Guide complet](browser.md).

---

## La machine

| | Risque | |
|---|---|---|
| `computer` | dangerous | Souris, clavier et écran, dans n'importe quelle application |

Désactivé tant que vous ne l'activez pas, et même alors pas permis tant que ce
n'est pas accordé. [Guide complet](computer.md). Windows seulement pour
l'instant.

---

## Garder le cap

| | Risque | |
|---|---|---|
| `todo_write` | safe | La liste de tâches que vous voyez dans la barre latérale |

L'agent y écrit son propre plan. Ce n'est pas de la décoration — c'est ainsi
qu'une longue tâche reste cohérente, et comment vous pouvez voir où il en est.

---

## Parfois là, parfois non

Comodor n'offre au modèle qu'un outil qu'il pourrait réellement utiliser. Un
outil qu'il voit et ne pourrait jamais utiliser avec succès invite à un appel
gâché à chaque tour.

| | Apparaît quand |
|---|---|
| `read_skill_file` | une compétence que vous avez installée embarque des fichiers |
| `search_history` | il y a des sessions passées à chercher |
| `delegate` | un sous-agent pourrait être lancé |
| `computer` | la plate-forme a un moteur **et** vous l'avez activé |
| Outils MCP | un serveur est configuré et activé |

`browse` a deux implémentations : le vrai navigateur quand Chrome, Chromium,
Edge ou Brave est installé, et un navigateur texte quand aucun ne l'est. Les
deux s'appellent `browse`, car choisir entre deux choses appelées « browser »
est un tour que le modèle ne devrait pas avoir à dépenser.

---

## Quand la sortie est trop grosse

Une commande qui affiche cinquante mille lignes n'est pas tronquée jusqu'à
l'inutilité et ne fait pas exploser le contexte.

Ce qui tient va au modèle — le début et la fin, puisque c'est là que se trouve
d'habitude la réponse. Le reste est écrit dans un fichier sous
`~/.comodor/output/`, et le modèle reçoit le chemin et la façon de le lire.
Ainsi il peut aller voir si besoin, et ne paie rien s'il ne le fait pas.

```json
{ "agent": { "max_tool_chars": 12000 } }
```

---

## Sous-agents

`delegate` lance un second agent dans un **git worktree** — un checkout isolé
du même dépôt. Il y travaille, et ses modifications reviennent sous forme de
patch appliqué par une fusion à trois voies.

Il n'a pas de mémoire, ne peut pas déléguer davantage, et ne reçoit pas
l'écran. Il hérite de l'annulation du parent, si bien que `Esc` l'arrête
aussi.

Utile pour quelque chose de réellement séparé — « porte ce module vers la
nouvelle API pendant que je continue à travailler » — et gaspilleur pour tout
le reste.

---

## Outils MCP

Tout ce qu'un serveur Model Context Protocol activé fournit apparaît à côté
des outils intégrés et passe par exactement le même contrôle de permission.

```bash
comodor mcp list
```

[Guide complet](mcp.md).

---

## Voir aussi

- [Sécurité et permissions](safety.md) — ce que chaque niveau signifie en pratique
- [L'interface](interface.md) — voir les outils s'exécuter
- [Compétences](skills.md) — lui enseigner *comment* utiliser tout cela pour un travail précis
