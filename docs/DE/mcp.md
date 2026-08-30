# MCP-Server

Das Model Context Protocol ist eine Möglichkeit für ein Werkzeug, sich
einem Agenten zu beschreiben. Comodor spricht es, sodass alles mit einem
MCP-Server etwas wird, das der Agent benutzen kann.

---

## Einen hinzufügen

```bash
comodor mcp catalogue          # servers Comodor can set up for you
comodor mcp add filesystem     # one of them
comodor mcp list               # what you have, and what each offers
```

Etwas, das nicht im Katalog steht:

```bash
comodor mcp custom notes -- npx -y @some/mcp-notes
comodor mcp remote github https://mcp.example.com/sse
```

Dann prüfe, dass es tatsächlich funktioniert, bevor du ihm vertraust:

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

## Ein- und ausschalten

```bash
comodor mcp enable notes
comodor mcp disable notes
comodor mcp remove notes       # forget it entirely
```

```
/mcp                           # the same, in the interface
```

Ein deaktivierter Server wird nicht gestartet, und seine Werkzeuge werden
nicht angeboten.

---

## Sie sind Werkzeuge wie jedes andere

Was auch immer ein Server bereitstellt, erscheint neben den eingebauten
Werkzeugen und geht durch **genau dieselbe Berechtigungsschleuse**. Ein
MCP-Werkzeug, das eine Datei schreibt, fragt auf die Weise, wie
`write_file` fragt. Hier gibt es keine Hintertür.

---

## Ein Projekt darf erklären, nicht einschalten

Die `.comodor/config.json` eines Repositorys darf die Server auflisten, die
es benutzt:

```json
{
  "mcp": {
    "servers": {
      "project-db": { "command": "npx", "args": ["-y", "@acme/db-mcp"] }
    }
  }
}
```

Das ist nützlich: Ein neuer Mensch klont das Repository und kann sehen, was
das Projekt erwartet.

**Sie kommen ausgeschaltet an.** Einen Server zu benennen ist ein Vorschlag;
einen zu starten führt einen Befehl auf deiner Maschine aus, und das ist
deine Entscheidung. Schalte ihn frei, sobald du nachgesehen hast:

```bash
comodor mcp enable project-db
```

Ein Projekt kann `mcp.enabled`, den Hauptschalter, überhaupt nicht setzen.
[Sicherheit](safety.md#what-a-repository-may-set).

---

## Transporte

| | |
|---|---|
| **stdio** | ein Befehl, den Comodor startet und über Pipes anspricht. Der übliche |
| **Streamable HTTP** | ein Server, der bereits irgendwo läuft, über HTTP |

Beide sind im Paket implementiert — für keinen eine Abhängigkeit.

---

## Wenn sich einer schlecht verhält

Ein Server, der nicht startet oder zu lange braucht, wird gemeldet und
übersprungen. Er reißt die Sitzung nicht mit hinunter.

```bash
comodor mcp test <name>        # start it and see
comodor doctor                 # includes every configured server
```

---

## Siehe auch

- [Was der Agent kann](tools.md) — die eingebauten Werkzeuge, zu denen diese hinzukommen
- [Sicherheit](safety.md) — die Schleuse, durch die sie gehen
