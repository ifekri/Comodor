# Was der Agent kann

Dreizehn Werkzeuge. Jedes deklariert eine Risikostufe, die entscheidet, ob es
zuerst fragt — siehe [Sicherheit](safety.md#risk-tiers).

---

## Dateien

| | Risiko | |
|---|---|---|
| `read_file` | safe | Eine Textdatei lesen. Streamt, sodass ein Ausschnitt aus einem großen Log erreichbar ist |
| `list_dir` | safe | Einträge eines Verzeichnisses, mit Größen |
| `glob` | safe | Dateien nach Namensmuster finden — `src/**/*.py` |
| `grep` | safe | Inhalte mit einem regulären Ausdruck durchsuchen |
| `write_file` | write | Eine Datei erstellen oder sie vollständig ersetzen |
| `edit_file` | write | Eine exakte Zeichenkette in einer Datei ersetzen |

Alles ist auf den Projektordner beschränkt, außer Sie schalten
`safety.workspace_only` ab.

`edit_file` wird `write_file` für eine Änderung an einer bestehenden Datei
vorgezogen: es ist kleiner, es ist als Diff prüfbar, und es kann nicht
stillschweigend den Rest der Datei verlieren.

---

## Dinge ausführen

| | Risiko | |
|---|---|---|
| `run_shell` | dangerous | Ein Shell-Befehl im Workspace |
| `run_python` | dangerous | Ein kurzes Python-Snippet, in einem Subprozess |

Beide fragen vor dem Ausführen, beide unterliegen `safety.deny_commands`, und
beide haben ihre Ausgabe begrenzt — siehe
[Wenn die Ausgabe zu groß ist](#when-output-is-too-big).

In der Oberfläche können Sie das Modell ganz überspringen:

```
!git status
```

Führt es aus, zeigt Ihnen die Ausgabe, und erwähnt es dem Modell gegenüber nie.
Schneller und billiger als zu fragen.

---

## Das Web

| | Risiko | |
|---|---|---|
| `web_fetch` | dangerous | Eine URL herunterladen und ihren lesbaren Text zurückgeben |
| `web_search` | dangerous | Suchen, und Titel, URLs und Schnipsel zurückgeben |
| `browse` | dangerous | Ein echter Browser — JavaScript, Cookies, Anmeldungen |

`web_fetch` ist das günstige: Es schält die Seite auf Text. Benutzen Sie es,
wenn die Seite ein Dokument ist.

`browse` ist dafür da, wenn es eine Anwendung ist — etwas, das JavaScript, eine
Anmeldung oder einen Klick braucht. [Vollständige Anleitung](browser.md).

---

## Die Maschine

| | Risiko | |
|---|---|---|
| `computer` | dangerous | Maus, Tastatur und Bildschirm, in jeder Anwendung |

Ausgeschaltet, außer Sie schalten es ein, und dann trotzdem nicht erlaubt,
bis es gewährt wurde. [Vollständige Anleitung](computer.md). Bisher nur unter
Windows.

---

## Den Überblick behalten

| | Risiko | |
|---|---|---|
| `todo_write` | safe | Die Aufgabenliste, die Sie in der Seitenleiste sehen |

Der Agent schreibt hier seinen eigenen Plan hinein. Es ist keine Dekoration —
es ist die Art, wie eine lange Aufgabe kohärent bleibt, und wie Sie sehen
können, wo es gerade ist.

---

## Mal da, mal nicht

Comodor bietet nur ein Werkzeug an, das das Modell tatsächlich benutzen könnte.
Ein Werkzeug, das es sehen und nie erfolgreich benutzen kann, lädt zu einem
verschwendeten Aufruf bei jedem Zug ein.

| | Erscheint, wenn |
|---|---|
| `read_skill_file` | ein installierter Skill von Ihnen Dateien bündelt |
| `search_history` | es frühere Sitzungen zum Durchsuchen gibt |
| `delegate` | ein Sub-Agent erzeugt werden könnte |
| `computer` | die Plattform ein Backend hat **und** Sie es aktiviert haben |
| MCP-Werkzeuge | ein Server konfiguriert und aktiviert ist |

`browse` hat zwei Implementierungen: den echten Browser, wenn Chrome, Chromium,
Edge oder Brave installiert ist, und einen Text-Browser, wenn keines davon da
ist. Beide heißen `browse`, denn die Wahl zwischen zwei Dingen namens „browser"
wäre ein Zug, den das Modell nicht verbrauchen sollte.

---

## Wenn die Ausgabe zu groß ist

Ein Befehl, der fünfzigtausend Zeilen ausgibt, wird weder zur Nutzlosigkeit
gekürzt, noch sprengt er den Kontext.

Was hineinpasst, geht an das Modell — der Anfang und das Ende, denn dort ist
die Antwort meistens. Der Rest wird in eine Datei unter `~/.comodor/output/`
geschrieben, und dem Modell werden der Pfad und die Art zu lesen mitgeteilt.
Es kann also hingehen und nachsehen, wenn es muss, und zahlt nichts, wenn es
nicht muss.

```json
{ "agent": { "max_tool_chars": 12000 } }
```

---

## Sub-Agents

`delegate` führt einen zweiten Agenten in einem **git worktree** aus — einem
isolierten Checkout desselben Repositorys. Er arbeitet dort, und seine Änderungen
kommen als Patch zurück, der mit einem Drei-Wege-Merge angewendet wird.

Er hat kein Gedächtnis, kann nicht weiter delegieren und bekommt den Bildschirm
nicht. Er erbt die Abbruchbedingung des Elternprozesses, also stoppt `Esc` auch
ihn.

Nützlich für etwas wirklich Getrenntes — „portiere dieses Modul auf die neue
API, während ich weiterarbeite" — und Verschwendung für alles andere.

---

## MCP-Werkzeuge

Alles, was ein aktivierter Model Context Protocol Server bereitstellt, erscheint
neben den eingebauten Werkzeugen und geht durch exakt dieselbe
Berechtigungsschleuse.

```bash
comodor mcp list
```

[Vollständige Anleitung](mcp.md).

---

## Siehe auch

- [Sicherheit und Berechtigungen](safety.md) — was jede Stufe in der Praxis bedeutet
- [Die Oberfläche](interface.md) — Werkzeugen bei der Arbeit zusehen
- [Skills](skills.md) — ihm beibringen, *wie* es diese für eine bestimmte Arbeit benutzt
