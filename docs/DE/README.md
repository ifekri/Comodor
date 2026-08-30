# Comodor-Dokumentation

Ein Terminal-Coding-Agent, der lernt, wie Sie ihn korrigieren.

Neu hier? **[Erste Schritte](getting-started.md)** dauert etwa fünf Minuten und
endet damit, dass der Agent etwas Nützliches tut.

---

## Wonach Sie gerade suchen

### Den Einstieg finden

| | |
|---|---|
| [Erste Schritte](getting-started.md) | Installation, Modellwahl, erste Aufgabe |
| [Von einem anderen Agenten kommend](migrating.md) | Schlüssel und Skills aus OpenClaw oder Hermes übernehmen |
| [Ein Modell wählen](models.md) | Welcher Anbieter, welches Modell, was es kostet |

### Es benutzen

| | |
|---|---|
| [Die Oberfläche](interface.md) | Panels, Tasten, Modi und alle 29 Befehle |
| [Aus dem Terminal](cli.md) | Jeder Befehl und jedes Flag, mit Beispielen |
| [Was der Agent kann](tools.md) | Die 13 Werkzeuge, die er hat, und wann er welches einsetzt |
| [Skills](skills.md) | Abläufe, die Sie einmal schreiben und denen er folgt |

### Es weiter reichen lassen

| | |
|---|---|
| [Der echte Browser](browser.md) | Ein Browser, der JavaScript ausführt und sich anmelden kann |
| [Den Bildschirm benutzen](computer.md) | Maus und Tastatur, in jeder Anwendung |
| [Aus dem Browser](web.md) | Die Weboberfläche, lokal oder auf einem Server |
| [Im Editor](acp.md) | Comodor aus Zed oder einem beliebigen Agent Client Protocol Client steuern |
| [In Docker](docker.md) | Ein Befehl, in einem Container |
| [MCP-Server](mcp.md) | Werkzeuge aus dem Model Context Protocol |

### Es verstehen

| | |
|---|---|
| [Vom Handy aus](telegram.md) | Der Telegram-Bot: Kopplung, die Tasten und wem er antwortet |
| [Aus Slack](slack.md) | Socket Mode — fünf Minuten, keine öffentliche Adresse, und er antwortet in Threads |
| [Aus WhatsApp](whatsapp.md) | Die Cloud API — etwa zwanzig Minuten und technisch. Telegram tut dasselbe in einem |
| [Modelle auf dem eigenen Rechner](local-models.md) | Eines herunterladen, offline betreiben, zur Liste hinzufügen |
| [Rückfragen](questions.md) | Das Formular, das er einblendet, wenn eine Anfrage zweideutig ist |
| [Wie er lernt](learning.md) | Korrekturen, Lektionen, Regeln und der Nachweis |
| [Sicherheit und Berechtigungen](safety.md) | Was er kann, was er fragt, was er niemals tut |
| [Kosten](cost.md) | Caching, Budgets und weniger zahlen für dieselbe Arbeit |
| [Konfiguration](configuration.md) | Jede Einstellung, wo die Dateien liegen, was sich durchsetzt |

### Wenn etwas nicht stimmt

| | |
|---|---|
| [Fehlerbehebung](troubleshooting.md) | `doctor`, übliche Probleme und wie man eines meldet |

---

## Die kürzest mögliche Version

```bash
curl -fsSL get.comodor.ai | sh      # macOS, Linux
irm get.comodor.ai | iex           # Windows

comodor                  # es stellt ein paar Fragen, einmalig
```

Dann tippen Sie, was Sie wollen. Korrigieren Sie es, wenn es falsch liegt —
ändern Sie die Datei oder sagen Sie es einfach — und es lernt. `/progress`
zeigt Ihnen, ob das tatsächlich funktioniert.

```bash
comodor run "fix the failing test in tests/test_parser.py"   # eine Aufgabe, keine Oberfläche
comodor web                                                  # aus dem Browser
comodor doctor                                               # ist alles in Ordnung?
comodor help                                                 # die geschriebene Hilfeseite
```

## Was es anders macht

**Es lernt aus Korrekturen, nicht aus Lob.** Die meisten Agents vergessen den
Moment, in dem eine Sitzung endet. Comodor beobachtet, was Sie an seiner
Ausgabe ändern, und macht daraus eine Lektion mit einem Vertrauenswert, der
steigt, wenn sie sich bewährt, und sinkt, wenn nicht. [Wie er lernt](learning.md)
erklärt den Mechanismus; `/progress` zeigt die Belege.

**Es fragt, bevor es handelt, und alles ist rückgängig zu machen.** Lesen
geschieht stillschweigend. Schreiben fragt. Ein Befehl fragt deutlicher. Jeder
Schreibvorgang wird als Prüfpunkt gesichert, und `/undo` stellt den letzten
wieder her. [Sicherheit und Berechtigungen](safety.md).

**Eine einzige Abhängigkeit.** Der HTTP-Client, der SSE-Reader, das WebSocket
für den Browser, der PNG-Encoder für Screenshots — alles Teil des Pakets. Die
Installation von Comodor zieht `rich` nach sich und sonst nichts.

**Es kann einen echten Browser und einen echten Desktop benutzen.** Kein
Text-Fetcher: ein Browser, der JavaScript ausführt und Cookies behält, und —
unter Windows — Maus und Tastatur, mit einem Halo auf dem Bildschirm, der
zeigt, wo er als Nächstes klicken wird. [Browser](browser.md),
[Bildschirm](computer.md).

---

## Außerdem im Repository

| | |
|---|---|
| [CHANGELOG](../CHANGELOG.md) | Was sich geändert hat, und warum |
| [CONTRIBUTING](../CONTRIBUTING.md) | An Comodor selbst arbeiten |
| [SECURITY](../SECURITY.md) | etwas Sensibles melden |
| [RELEASING](../RELEASING.md) | Wie ein Release geschnitten wird |
