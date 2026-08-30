# Aus dem Terminal

Jeder Befehl und jedes Flag, mit etwas, das Sie einfügen können.

```bash
comodor help              # the written help page
comodor help computer     # one topic in more detail
```

---

## Installation und Aktualisierung

```bash
curl -fsSL get.comodor.ai | sh     # macOS, Linux, BSD
```

```powershell
irm get.comodor.ai | iex          # Windows
```

`get.comodor.ai` nennt keine Datei: Es erkennt, welcher Client fragt, und
antwortet mit dem Installer, den dieser Client ausführen kann. Dieselbe Zeile
aktualisiert eine bestehende Installation. Oder, sobald es auf Ihrem Rechner ist:

```bash
comodor update --check    # what is out there
comodor update            # move to it
```

[Erste Schritte](getting-started.md#1-install) hat den Rest — die
Paketmanager und was die Installer akzeptieren.

---

## Es starten

```bash
comodor                              # the interface
comodor --demo                       # the interface, offline, no key needed
comodor --resume                     # reopen the last session
comodor --resume 2026-08-22-a4f1     # reopen one by id
comodor --cwd ~/projects/api         # work somewhere other than here
comodor --model claude-sonnet-5      # a different model, this run only
comodor --mode plan                  # start read-only
```

### Optionen

| | |
|---|---|
| `--provider NAME` | `openrouter`, `anthropic`, `openai`, `ollama`, … |
| `--model ID` | das Modell für diesen Lauf überschreiben |
| `--mode act\|plan\|chat` | plan ist nur lesend; chat hat keine Werkzeuge |
| `--no-loop` | einmal antworten, statt zu arbeiten, bis es fertig ist |
| `--cwd PATH` | der Ordner, den es anfassen darf |
| `--theme NAME` | `ember`, `midnight`, `matrix`, `mono` |
| `--ascii` | ASCII-Rahmen |
| `--no-mouse` | die Maus beim Terminal lassen |
| `--resume [ID]` | die letzte Sitzung, oder eine per id |
| `--demo` | skriptgesteuerter Offline-Provider |
| `--version` | welche Version dies ist |
| `-h`, `--help` | die geschriebene Hilfeseite |

Keine davon wird in Ihre Konfiguration geschrieben. Sie gilt für diesen einen
Lauf. Damit eine Änderung hängen bleibt, benutzen Sie `/save` innerhalb der
Oberfläche oder bearbeiten Sie die Konfigurationsdatei —
[Konfiguration](configuration.md).

---

## `comodor run` — eine Aufgabe, keine Oberfläche

```bash
comodor run "fix the failing test in tests/test_parser.py"
comodor run "add type hints to src/parser.py" --yes
comodor run "what does this project do?" --json
comodor run "refactor the parser" --max-steps 40
```

| | |
|---|---|
| `--yes` | Schreibvorgänge und Befehle automatisch genehmigen |
| `--json` | ein maschinenlesbares Ergebnis auf stdout |
| `--max-steps N` | das Schrittlimit für diesen Lauf überschreiben |

Ohne `--yes` fragt es, auf stderr, und verweigert lieber, statt anzunehmen, wenn
nichts antworten kann. Das ist Absicht: Ein Skript, das sich stillschweigend
selbst genehmigt, ist ein Skript, das etwas tut, das Sie um drei Uhr morgens
nicht erwartet haben.

`--json` gibt Ihnen:

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

`stopped` sagt, warum es fertig ist — eines von:

| | |
|---|---|
| `done` | es hat entschieden, dass es fertig ist |
| `max_steps` | es hat `agent.max_steps` erreicht |
| `budget` | es hat `agent.max_cost_usd` oder `agent.max_seconds` erreicht |
| `cancelled` | Sie haben es unterbrochen |
| `error` | etwas ist schiefgegangen; `error` sagt, was |

`ok` ist wahr für `done` und `max_steps` — die Schritte aufgebraucht zu haben
ist kein Fehlschlag, sondern eine Decke, die ihren Job macht —, also prüfen
Sie auch `stopped`, wenn Sie den Unterschied brauchen:

```bash
comodor run "update the changelog for this release" --yes --json > result.json
jq -e '.stopped == "done"' result.json
```

Es lernt auch aus einem Headless-Lauf. Eine Korrektur, die Sie im Nachhinein
machen, lehrt dieselbe Lektion, die ein interaktiver Lauf auch gelehrt hätte.

---

## `comodor setup` — einen Anbieter und ein Modell wählen

```bash
comodor setup
```

Sechs Fragen, oder sieben, wenn ein anderer Agent installiert ist und es einen
Import anbietet. Läuft beim ersten Lauf automatisch; benutzen Sie dies, um es
Ihnen später anders zu überlegen.

Die Antworten landen in `~/.comodor/config.json`.

---

## `comodor import` — aus OpenClaw oder Hermes

```bash
comodor import             # bring keys, model and skills across
comodor import --dry-run   # say what it would take, change nothing
comodor import --keys-only # leave the skills and the model
```

Nichts wird verschoben und nichts, was hier bereits gesetzt ist, wird ersetzt.
Siehe [Von einem anderen Agenten kommend](migrating.md).

---

## `comodor doctor` — ist alles in Ordnung?

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

`--fix` repariert das Reparierbare — einen veralteten Anbieternamen, ein
fehlendes Verzeichnis, einen beschädigten Suchindex. Es ändert nie etwas, das
es nicht vorher gemeldet hat.

Der Exit-Code ist ungleich null, wenn etwas fehlgeschlagen ist, sodass es in
einer Gesundheitsprüfung funktioniert.

---

## `comodor web` — aus einem Browser

```bash
comodor web                       # here, on 127.0.0.1:8765
comodor web --port 9000
comodor web --host 0.0.0.0        # reachable from elsewhere — read the warning
comodor web --no-browser          # do not open one
comodor web --token mytoken       # a fixed token instead of a fresh one
```

Vollständige Anleitung: [Aus dem Browser](web.md).

---

## `comodor telegram` — vom Handy aus

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

Das Ersteinrichtung-Setup bietet all dies als letzte Frage an; diese sind dafür
gedacht, es später zu ändern, oder für eine bereits eingerichtete Maschine.

Vollständige Anleitung: [Vom Handy aus](telegram.md).

---

## `comodor slack` — aus einem Slack-Workspace

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

Etwa fünf Minuten, und keine öffentliche Adresse: Socket Mode lässt die App
einen Websocket nach außen öffnen, statt an ihn gepostet zu werden.

Vollständige Anleitung: [Aus Slack](slack.md).

---

## `comodor whatsapp` — von einer WhatsApp-Nummer

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

Meta liefert Nachrichten an eine URL, statt Polling zu erlauben, also braucht
dieser eine öffentliche HTTPS-Adresse. `connect` ohne Argumente geht die ganze
Einrichtung durch und startet den Tunnel selbst; beim ersten Mal etwa zwanzig
Minuten, das meiste davon im Meta-Dashboard. Keine echte Nummer, keine Karte,
keine Geschäftsprüfung.

Vollständige Anleitung: [Aus WhatsApp](whatsapp.md).

---

## `comodor skills` — Abläufe, denen es folgt

```bash
comodor skills browse             # what is available
comodor skills list               # what you have
comodor skills add review taste   # install some
comodor skills update             # refresh installed ones
comodor skills remove review
```

Vollständige Anleitung: [Skills](skills.md).

---

## `comodor mcp` — Model Context Protocol Server

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

Vollständige Anleitung: [MCP-Server](mcp.md).

---

## `comodor update` — zum neuesten Release wechseln

```bash
comodor update --check     # what is out there, change nothing
comodor update             # do it
```

Es erarbeitet, wie diese Kopie installiert wurde — `uv`, `pipx`, `pip` oder ein
Source-Checkout — und benutzt das Richtige. Ein Source-Checkout bleibt unangetastet:
der ist Ihres.

---

## `comodor uninstall` — es vollständig entfernen

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

Es nennt alles, bevor es etwas entfernt, und sagt, was es nicht finden kann —
ein `.comodor`-Ordner in einem Projekt, das Sie benutzt haben, dessen
Sitzungsverlauf aber geleert wurde, kann nicht benannt werden, und es sagt das,
statt es vorzutäuschen.

---

## `comodor preview` — die Oberfläche in einer gegebenen Größe

```bash
comodor preview 80x24
comodor preview 200x50 --svg wide.svg
```

Rendert einen Rahmen und beendet sich. Nützlich, um ein schmales Terminal zu
prüfen, oder für einen Screenshot.

---

## Umgebungsvariablen

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, … | ein Schlüssel, je Anbieter |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | einen Anbieter oder ein Modell erzwingen |
| `COMODOR_HOME` | wo Konfiguration, Brain und Sitzungen leben |
| `COMODOR_BANNER=0` | kein Wortmarken-Banner in diesem Lauf |
| `COMODOR_NO_IMPORT=1` | keinen Import aus einem anderen Agenten anbieten |
| `COMODOR_WEB_TOKEN` | ein fester Token für die Weboberfläche |
| `NO_COLOR` | keine Farbe, überall respektiert |

Ein Schlüssel in der Umgebung wird **niemals in Ihre Konfigurationsdatei
geschrieben**. Einen zu exportieren, statt ihn zu speichern, ist eine
Entscheidung, und `/save` respektiert sie. Siehe [Konfiguration](configuration.md).

---

## Exit-Codes

| | |
|---|---|
| `0` | es hat funktioniert |
| `1` | hat es nicht |
| `130` | Sie haben es unterbrochen |

---

## Siehe auch

- [Die Oberfläche](interface.md) — dieselbe Kraft, interaktiv
- [Konfiguration](configuration.md) — ein Flag dauerhaft machen
- [Fehlerbehebung](troubleshooting.md) — wenn ein Befehl nicht tut, was er sagt
