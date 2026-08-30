# Die Oberfläche

Was Sie sehen, was Sie drücken, und alle 29 Befehle.

```bash
comodor          # start it
comodor --demo   # the whole interface, offline, no key
```

---

## Das Layout

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

**Die Seitenleiste** ist der Plan, wenn es einen gibt. `F2` blendet sie aus —
auf einem schmalen Terminal wert.

**Die Statuszeile** zeigt den Modus, ob es gerade iteriert, wie voll der Kontext
ist und was diese Sitzung gekostet hat. Die Kontextangabe ist echt: Sie folgt
dem Modell, sodass der Wechsel von einem Million-Token-Modell auf ein 128k-Modell
sie sofort ändert.

Es funktioniert ab etwa 60 Spalten aufwärts. Darunter faltet sich die
Seitenleiste von selbst zusammen. `comodor preview 80x24` rendert es in jeder
Größe, ohne eine Sitzung zu starten.

---

## Modi

| Modus | Was der Agent tun darf | |
|---|---|---|
| **act** | Alles, fragt vor Schreibvorgängen und Befehlen | der Standard |
| **plan** | Nur Lesen. Keine Schreibvorgänge, keine Befehle, kein Netzwerk | für „was würdest du tun?" |
| **chat** | Überhaupt keine Werkzeuge | für eine Frage zu Code, den Sie einfügen |

`F3` schaltet sie durch. `/mode plan` setzt einen direkt.

Der Plan-Modus ist wirklich nur lesend — er wird auf der Berechtigungsebene
erzwungen, nicht durch freundliches Bitten an das Modell. Ein Werkzeug mit einem
Risiko über „safe" wird abgelehnt, bevor es läuft.

---

## Tasten

| | |
|---|---|
| `Enter` | senden |
| `Ctrl+J` | Zeilenumbruch innerhalb einer Nachricht |
| `Esc` | stoppen, was es gerade tut |
| `Ctrl+C` | stoppen; zweimal zum Beenden |
| `F1` | Hilfe |
| `F2` | die Seitenleiste |
| `F3` | Modus |
| `F4` | loop an/aus |
| `F5` | das Gateway |
| `Ctrl+O` | eine Datei anhängen |
| `Ctrl+L` | die Konversation leeren |
| `PgUp` `PgDn` | scrollen |
| `Ctrl+↑` `Ctrl+↓` | frühere und spätere Nachrichten |
| `!command` | einen Shell-Befehl direkt ausführen, ohne das Modell zu fragen |

`!` ist es wert, sich zu merken. `!git status` führt es aus und zeigt Ihnen die
Ausgabe; das Modell sieht die Frage nie. Günstiger und schneller als zu fragen.

---

## Befehle

Tippen Sie `/`, und die Liste filtert sich mit jeder Eingabe.

### Ihm sagen, was es anders machen soll

| | |
|---|---|
| `/mode [act\|plan\|chat]` | was es erlaubt ist zu tun |
| `/loop` | weiterarbeiten, bis es fertig ist, oder einmal antworten |
| `/model [id]` | das Modell wählen — eine Liste, oder eines benennen |
| `/provider [name]` | den Anbieter wählen |
| `/gw` | das Gateway: über Anbieter hinweg nach Kosten, Geschwindigkeit oder Qualität routen |

### Es lehren

| | |
|---|---|
| `/good` | diese Antwort war richtig |
| `/bad` | diese Antwort war falsch |
| `/teach <text>` | sich das merken |
| `/memory` | was es gelernt hat |
| `/rules` | die Hausregeln, die es aus Ihrem Code und Ihren Änderungen abgeleitet hat |
| `/progress` | der Beleg, dass es besser wird |
| `/skills` | Abläufe, denen es folgt, wenn die Arbeit passt |

`/good` und `/bad` sind das Günstigste, was Sie für es tun können. Siehe
[Wie er lernt](learning.md).

### Rückgängig machen und zurückschauen

| | |
|---|---|
| `/undo` | die letzte von ihm geänderte Datei wiederherstellen |
| `/clear` | eine neue Konversation beginnen |
| `/resume [id]` | eine frühere Sitzung wieder öffnen |
| `/search <text>` | etwas in einer früheren Konversation finden |
| `/export [path]` | diese Sitzung in eine Datei schreiben |

### Es weiter reichen lassen

| | |
|---|---|
| `/computer [15m\|1h this app\|stop]` | es Ihren Bildschirm benutzen lassen — [Anleitung](computer.md) |
| `/mcp` | MCP-Server und ihre Werkzeuge — [Anleitung](mcp.md) |
| `/attach <path>` | eine Datei zur nächsten Nachricht hinzufügen |

### Es einrichten

| | |
|---|---|
| `/settings` | was gerade konfiguriert ist |
| `/approve [writes\|shell\|all]` | bei diesen nicht mehr vorher fragen |
| `/theme [name]` | ember, midnight, matrix, mono |
| `/save` | die aktuellen Einstellungen in Ihre Konfigurationsdatei schreiben |
| `/cost` | Tokens, Ausgaben und was der Cache gespart hat |
| `/copy [all\|task]` | die letzte Antwort, oder alles, in die Zwischenablage |
| `/mouse [on\|off]` | Maus-Tracking, damit Sie selbst Text auswählen können |
| `/help` | all das, innerhalb der Oberfläche |
| `/quit` | verlassen |

**`/save` schreibt nur, was Sie gewählt haben.** Nicht die Einstellungen des
Repositorys, keinen Schlüssel, den Sie in Ihrer Umgebung halten, kein `--model`,
das Sie für einen einzigen Lauf übergeben haben. Siehe
[Konfiguration](configuration.md#what-save-writes).

---

## Genehmigungen

Wenn der Agent eine Datei schreiben oder einen Befehl ausführen will:

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

`A` merkt es sich für die Sitzung, je Art von Ding — Schreibvorgänge zu
erlauben erlaubt keine Befehle.

Ablehnen ist nicht verloren. Eine Verweigerung ist das deutlichste
Präferenzsignal, das die Oberfläche je sammelt, und es geht an die
Lern-Engine: Der Agent schlägt das seltener wieder vor.

Um gar nicht mehr gefragt zu werden:

```
/approve writes      files, yes; commands, still ask
/approve all         everything
```

Alles wird trotzdem als Prüfpunkt gesichert. `/undo` funktioniert
unabhängig davon.

---

## Text herauskopieren

Solange die Maus verfolgt wird, gehört ein Ziehen zu Comodor, und das Terminal
sieht es nie — das übliche Auswählen-und-Kopieren funktioniert also nicht.
Drei Wege daran vorbei:

```
/copy              the last answer
/copy all          the whole conversation
/copy task         the last thing you asked for
/mouse             mouse tracking off, so selection works as usual
```

`/copy` braucht unter Windows oder macOS nichts Installiertes. Unter Linux
benutzt es `wl-copy`, `xclip` oder `xsel`, je nachdem, was da ist, und sagt,
was fehlt, wenn keines davon vorhanden ist.

Über SSH weicht es auf eine Escape-Sequenz aus, die *Ihr* Terminal bittet, *Ihre*
Zwischenablage zu setzen — sodass Text von einem Agenten auf einem Server dort
landet, wo Sie ihn einfügen können, und nicht auf einem Server ohne Zwischenablage.

Die meisten Terminals erlauben außerdem, bei gedrückter **Shift**-Taste
auszuwählen, was das Maus-Tracking umgeht, ohne es abzuschalten.

---

## Wer spricht

Jeder Zug sitzt auf einem leisen Band — eine Nuance hinter dem, was Sie
getippt haben, eine andere hinter der Antwort:

```
▌ › why does the parser drop the last field?              ← warm

▌   Because split is called with a maxsplit of 2 …        ← neutral
▌
▌   ┌─ python ────────────────────────┐
▌   │ return text.split(',', 2)       │
▌   └─────────────────────────────────┘
```

Bewusst gedämpft. Das liegt hinter Fließtext, den Sie minutenlang lesen, und
ein Hintergrund mit eigener Präsenz konkurriert mit den Worten. Jedes Theme
hat sein eigenes Paar, wenige Prozent von seinem Hintergrund entfernt; `mono`
hat keines, denn ein Theme, dessen Prämisse keine Farbe ist, will keine zwei.

Sie kosten keinen vertikalen Raum — der Farbwechsel ist die Grenze.

---

## Text von rechts nach links

Persisch, Arabisch und Hebräisch werden rechtsbündig gesetzt, dort, wo ihre
Zeilen beginnen, mit einem Font-Stack, der zu ihnen passt. Gemischte Absätze —
ein englischer Bezeichner innerhalb eines persischen Satzes — werden pro Zeile
statt pro Datei behandelt, was tatsächlich in einem technischen Gespräch passiert.

---

## Themes

```
/theme midnight
```

`ember` (der Standard, warmes Bernstein), `midnight` (kühles Blau), `matrix`
(Grün), `mono` (gar keine Farbe).

`--ascii` tauscht die Box-Zeichen gegen ASCII, für Terminals ohne sie.
`NO_COLOR` in Ihrer Umgebung wird respektiert.

---

## Siehe auch

- [Aus dem Terminal](cli.md) — dieselbe Kraft ohne die Oberfläche
- [Was der Agent kann](tools.md) — die Werkzeuge hinter diesen `▸`-Zeilen
- [Sicherheit](safety.md) — wovor die Genehmigungsdialoge schützen
