# In deinem Editor

Comodor spricht das [Agent Client Protocol](https://agentclientprotocol.com), sodass
ein Editor, der es unterstützt, Comodor direkt steuern kann — mit seinem eigenen
Panel, seinen eigenen Berechtigungsdialogen, seiner eigenen Dateiansicht — mit
demselben Agenten, denselben gelernten Regeln und denselben Transkripten wie im
Terminal.

```bash
comodor acp
```

Das tippst du normalerweise nicht selbst. Der Editor startet es.

---

## Einrichtung

Comodor gibt den Block aus, den dein Editor erwartet:

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

Wohin der Block gehört, hängt vom Editor ab. Drei, die bei der Entstehung
dieses Textes auf einer echten Maschine eingerichtet und geprüft wurden:

**JetBrains** — PyCharm, IntelliJ, WebStorm und die übrigen, über das
AI-Assistant-Plugin. Lege den Block in `~/.jetbrains/acp.json` ab, oder wähle
*Add Custom Agent* im Menü des AI-Chat-Fensters, das dieselbe Datei öffnet.
Comodor erscheint danach in der Agentenauswahl am unteren Rand des
Chat-Panels. Ein JetBrains-AI-Abo wird dafür nicht benötigt — ACP-Agenten
funktionieren auch ohne eines.

**VS Code** — installiere eine ACP-Client-Erweiterung; [ACP
Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client)
ist die, gegen die das geprüft wurde. Der Block gehört unter `acp.agents` in
`settings.json`, und Comodor erscheint in der Agentenliste des ACP-Panels.

**Zed** — `settings.json`, und Comodor erscheint im Agenten-Panel.

Laut Berichten ebenfalls funktionsfähig, hier jedoch nicht geprüft: Neovim
(CodeCompanion, avante.nvim, agentic.nvim), Emacs (agent-shell.el), Qt
Creator, Obsidian und Visual Studio.

Das Protokoll ist überall dasselbe; nur die Einstellungsdatei unterscheidet
sich.

Richte Comodor zuerst ein, in einem Terminal:

```bash
comodor setup
```

Ein Editor hat keine Stelle, an der er fragen könnte, welcher Anbieter zu
verwenden ist. Ein Comodor, das noch nie konfiguriert wurde, weigert sich
daher, eine Sitzung zu starten, und nennt den auszuführenden Befehl. Das ist
eine klare Meldung im Editor statt eines Fehlschlags bei der ersten Aufgabe.

---

## Was der Editor bekommt

| | |
|---|---|
| Streaming-Antworten | so, wie das Modell sie schreibt |
| Tool-Aufrufe | jeder einzeln benannt, mit dem, was er tat, und markiert als Lesen / Bearbeiten / Ausführen, damit der Editor ein Symbol wählen kann |
| Berechtigungsdialoge | im Editor gestellt, im Editor beantwortet |
| Pläne | wenn Comodor eine Aufgabenliste schreibt, zeichnet der Editor sie |
| Abbruch | der Stopp-Knopf des Editors unterbricht den Zug |
| Sitzungen | aufgelistet, fortgesetzt und gelöscht — dieselben Transkripte, die `comodor` fortsetzt |

Der Arbeitsordner kommt vom Editor: Welches Projekt auch immer du geöffnet
hast, dort liest und schreibt der Agent, und er bleibt darauf beschränkt.

---

## Was es nicht tut

**Einen Modellanbieter vom Editor übernehmen.** Comodors Anbieter, Modell,
Regeln, Skills und Berechtigungen sind seine eigenen, konfiguriert mit
`comodor setup` oder in der Browser-Oberfläche. Ein Editor, der zusätzlich ein
Modell konfigurieren will, wäre eine zweite Quelle der Wahrheit für dieselbe
Einstellung.

**Anmelden.** Comodor authentifiziert sich bei einem Modellanbieter, nicht bei
deinem Editor, und bietet daher keine Authentifizierungsmethoden an; ein
Client wird dir keinen Login anbieten.

---

## Wenn etwas nicht stimmt

Das Protokoll reserviert die Standardausgabe für Nachrichten, daher geht
Comodors Protokollierung auf die Standardfehlerausgabe. Editoren zeigen diese
gewöhnlich an irgendeiner Stelle — in Zed ist es das Protokoll des
Agentenservers.

```
comodor acp — speaking ACP v2 on stdio
```

Ein häufiger Fall, der wie ein defekter Agent aussieht, obwohl er es nicht
ist: Der Anbieter weist deinen Schlüssel zurück. Er erreicht den Editor als
`Error during prompt turn`, oder in den Worten des Anbieters — etwa
`OpenRouter: User not found`, was bedeutet, dass der Schlüssel widerrufen
wurde. `comodor doctor` sagt, welcher Anbieter konfiguriert ist; die
Browser-Oberfläche nimmt einen neuen Schlüssel entgegen oder meldet dich an.

Wenn sich der Agent verbindet und dann nichts tut, führe zuerst `comodor
doctor` in einem Terminal aus: Ein nicht erreichbarer Anbieter sieht aus einem
Editor heraus genauso aus wie ein defekter Agent.

---

## Siehe auch

- [Im Browser](web.md) — derselbe Agent, in einem Browser-Tab
- [Die Oberfläche](interface.md) — die Terminal-Version
- [Sicherheit](safety.md) — was sie vorher fragt und was sie niemals tut
