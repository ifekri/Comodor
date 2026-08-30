# Dans votre éditeur

Comodor parle le [Agent Client Protocol](https://agentclientprotocol.com), si
bien qu'un éditeur qui le prend en charge peut piloter Comodor directement —
avec son propre panneau, ses propres demandes d'autorisation, sa propre vue des
fichiers — avec le même agent, les mêmes règles apprises et les mêmes
transcriptions que dans le terminal.

```bash
comodor acp
```

Vous n'aurez généralement pas à taper cela : c'est l'éditeur qui le lance.

---

## Configuration

Comodor affiche le bloc que votre éditeur attend :

```bash
comodor acp --print-config
```

```json
{
  "agent_servers": {
    "Comodor": {
      "command": "/home/you/.local/bin/comodor",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

L'emplacement où placer ce bloc dépend de l'éditeur. Trois d'entre eux ont été
configurés et vérifiés sur une vraie machine pendant la rédaction de cette
documentation :

**JetBrains** — PyCharm, IntelliJ, WebStorm et les autres, via le plugin AI
Assistant. Placez le bloc dans `~/.jetbrains/acp.json`, ou utilisez *Add Custom
Agent* depuis le menu de la fenêtre AI Chat, qui ouvre le même fichier. Comodor
apparaît alors dans le sélecteur d'agents en bas du panneau de discussion.
Aucun abonnement JetBrains AI n'est nécessaire pour cela — les agents ACP
fonctionnent sans.

**VS Code** — installez une extension cliente ACP ; [ACP
Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client)
est celle avec laquelle cela a été vérifié. Le bloc se place sous `acp.agents`
dans `settings.json`, et Comodor apparaît dans la liste des agents du panneau
ACP.

**Zed** — `settings.json`, et Comodor apparaît dans le panneau des agents.

D'autres ont été signalés comme fonctionnant, sans avoir été vérifiés ici :
Neovim (CodeCompanion, avante.nvim, agentic.nvim), Emacs (agent-shell.el),
Qt Creator, Obsidian et Visual Studio.

Le protocole est le même partout ; seul le fichier de paramètres diffère.

Configurez d'abord Comodor, dans un terminal :

```bash
comodor setup
```

Un éditeur n'a nul part où demander quel fournisseur utiliser, si bien qu'un
Comodor jamais configuré refuse de démarrer une session et indique quelle
commande exécuter. Cela se traduit par un message clair dans l'éditeur plutôt
que par un échec dès la première tâche.

---

## Ce que l'éditeur obtient

| | |
|---|---|
| Réponses en continu | telles que le modèle les écrit |
| Appels d'outils | chacun nommé, avec ce qu'il a fait, et marqué read / edit / execute pour que l'éditeur choisisse une icône |
| Demandes d'autorisation | posées dans l'éditeur, traitées dans l'éditeur |
| Plans | quand Comodor écrit une liste de tâches, l'éditeur la dessine |
| Annulation | le bouton d'arrêt de l'éditeur interrompt le tour |
| Sessions | listées, reprises et supprimées — les mêmes transcriptions que reprend `comodor` |

Le dossier de travail vient de l'éditeur : le projet que vous avez ouvert est
celui où l'agent lit et écrit, et il y est confiné.

---

## Ce qu'il ne fait pas

**Prendre un fournisseur de modèle auprès de l'éditeur.** Le fournisseur, le
modèle, les règles, les compétences et les autorisations de Comodor lui sont
propres, configurés avec `comodor setup` ou dans l'interface navigateur. Un
éditeur qui voudrait aussi configurer un modèle constituerait une deuxième
source de vérité pour le même paramètre.

**Se connecter.** Comodor s'authentifie auprès d'un fournisseur de modèle, pas
auprès de votre éditeur ; il n'annonce donc aucune méthode d'authentification et
un client ne vous proposera pas de connexion.

---

## Quand quelque chose ne va pas

Le protocole réserve la sortie standard aux messages, si bien que les journaux
de Comodor vont sur la sortie d'erreur. Les éditeurs l'affichent généralement
quelque part — dans Zed, c'est le journal du serveur d'agents.

```
comodor acp — speaking ACP v2 on stdio
```

Un cas fréquent, qui ressemble à un agent cassé alors qu'il n'en est rien : le
fournisseur refuse votre clé. Cela arrive dans l'éditeur sous la forme
`Error during prompt turn`, ou dans les mots du fournisseur lui-même —
`OpenRouter: User not found`, par exemple, ce qui signifie que la clé a été
révoquée. `comodor doctor` indique quel fournisseur est configuré ; l'interface
navigateur acceptera une nouvelle clé, ou vous connectera.

Si l'agent se connecte puis ne fait plus rien, lancez d'abord `comodor doctor`
dans un terminal : un fournisseur injoignable se présente de la même façon
depuis un éditeur qu'un agent cassé.

---

## Voir aussi

- [Depuis un navigateur](web.md) — le même agent, dans un onglet de navigateur
- [L'interface](interface.md) — la version terminal
- [Sécurité](safety.md) — ce qu'il demande avant, et ce qu'il ne fait jamais
