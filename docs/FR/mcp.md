# Serveurs MCP

Le Model Context Protocol est un moyen pour un outil de se décrire à un agent.
Comodor le parle, si bien que tout ce qui possède un serveur MCP devient quelque
chose que l'agent peut utiliser.

---

## En ajouter un

```bash
comodor mcp catalogue          # servers Comodor can set up for you
comodor mcp add filesystem     # one of them
comodor mcp list               # what you have, and what each offers
```

Quelque chose qui n'est pas dans le catalogue :

```bash
comodor mcp custom notes -- npx -y @some/mcp-notes
comodor mcp remote github https://mcp.example.com/sse
```

Puis vérifiez qu'il fonctionne réellement avant de lui faire confiance :

```bash
comodor mcp test notes
```

```
  notes            started in 0.8s
    create_note    Create a note with a title and body
    search_notes   Find notes by text
    delete_note    Delete a note by id
```

---

## Les activer et les désactiver

```bash
comodor mcp enable notes
comodor mcp disable notes
comodor mcp remove notes       # forget it entirely
```

```
/mcp                           # the same, in the interface
```

Un serveur désactivé n'est pas démarré et ses outils ne sont pas proposés.

---

## Ce sont des outils comme les autres

Quoi que fournit un serveur apparaît à côté des outils intégrés et passe par
**exactement la même barrière d'autorisation**. Un outil MCP qui écrit un
fichier demande comme le demande `write_file`. Il n'y a pas de porte dérobée
ici.

---

## Un projet peut déclarer, pas activer

Le `.comodor/config.json` d'un dépôt peut lister les serveurs qu'il utilise :

```json
{
  "mcp": {
    "servers": {
      "project-db": { "command": "npx", "args": ["-y", "@acme/db-mcp"] }
    }
  }
}
```

C'est utile : une nouvelle personne clone le dépôt et peut voir ce que le projet
attend.

**Ils arrivent désactivés.** Nommer un serveur est une suggestion ; en démarrer
un exécute une commande sur votre machine, et c'est votre décision. Activez-le
une fois que vous avez regardé :

```bash
comodor mcp enable project-db
```

Un projet ne peut pas du tout définir `mcp.enabled`, l'interrupteur maître.
[Sécurité](safety.md#what-a-repository-may-set).

---

## Transports

| | |
|---|---|
| **stdio** | une commande que Comodor démarre et avec laquelle il parle via des pipes. Le cas habituel |
| **Streamable HTTP** | un serveur déjà lancé quelque part, via HTTP |

Les deux sont implémentés dans le paquet — aucune dépendance pour l'un ni pour
l'autre.

---

## Quand l'un se comporte mal

Un serveur qui refuse de démarrer, ou qui prend trop de temps, est signalé et
ignoré. Il n'entraîne pas la session dans sa chute.

```bash
comodor mcp test <name>        # start it and see
comodor doctor                 # includes every configured server
```

---

## Voir aussi

- [Ce que l'agent peut faire](tools.md) — les outils intégrés que ceux-ci rejoignent
- [Sécurité](safety.md) — la barrière qu'ils traversent
