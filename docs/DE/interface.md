# Die Oberfläche

Was Sie sehen, was Sie drücken, und woher alles auf dem Bildschirm kommt.

```bash
comodor          # starten
comodor --demo   # die ganze Oberfläche, offline, ohne Schlüssel
```

Die Oberfläche läuft auf [Bun](https://bun.sh) — `comodor doctor` sagt, ob es
da ist. Ohne Bun erledigt `comodor run "..."` eine Aufgabe ohne Oberfläche, und
`comodor web` stellt eine im Browser bereit.

Wie sie gebaut ist — der Kern, den sie steuert, das Protokoll zwischen beiden,
und warum jede Tatsache auf dem Bildschirm dem Kern gehört und nicht dem
Bildschirm — steht in [tui-v2.md](../tui-v2.md). Diese Seite ist die kurze
Fassung für die Person, die sie benutzt.

---

## Der Bildschirm

```
┌──────────────────────────────────────────┬───────────────────────┐
│ Comodor   ~/work/my-project  fake-1      │ Agents         1 live │
│                                          │  ● d1 running    12.3s│
│  You                                     │    survey the retries │
│  fix the failing parser test             │ Tasks            2/5  │
│                                          │  ◐ write the tests    │
│  Comodor                                 │  ● read the code      │
│  The test expects parse("") to raise, …  │  ○ run the suite      │
│  ✓ read_file  tests/test_parser.py  0.2s │                       │
│  ● run_shell  pytest tests/…     running…│                       │
│      collected 12 items                  │                       │
│                                          │                       │
├──────────────────────────────────────────┴───────────────────────┤
│ ▌ask for anything                                                │
├──────────────────────────────────────────────────────────────────┤
│  [ACT]   PLAN    ASK    Reads, writes and runs commands…         │
│ ● 1 agent  tab Mode  ctrl+b Work  ctrl+k Commands      42% ctx  │
└──────────────────────────────────────────────────────────────────┘
```

**Die Kopfzeile** nennt das Projekt sowie den Anbieter und das Modell, die
antworten. Es ist das, was der Kern meldet, nicht das, was eine
Konfigurationsdatei sagt: Wechselt das Modell — von hier aus, von einem anderen
Client, oder durch den Kern selbst — folgt die Kopfzeile.

**Das Gespräch** trägt die Werkzeug-Zeitleiste in sich. Jeder Werkzeugaufruf
sitzt dort, wo er geschah, als eine Zeile: ein Zeichen (`●` läuft, `✓` fertig,
`×` fehlgeschlagen), der Name, eine einzeilige Zusammenfassung, und wie lange
es gedauert hat. Ein laufendes Werkzeug zeigt die letzten Zeilen seiner
Ausgabe; ein fertiges klappt zusammen, und ein Klick darauf öffnet, was der
Kern noch hält.

**Die Werkbank** — `Ctrl+B` — ist die Arbeit außerhalb des Gesprächs: die
Aufgabenliste, die der Agent für sich führt, und alle Hintergrund-Agenten, die
er gestartet hat, jeder mit seinem Zustand. In einem schmalen Terminal öffnet
sie sich über dem Gespräch statt daneben, und dieselbe Taste schließt sie.

**Die Fußzeile** zeigt, was Sie drücken können, aus derselben Liste, aus der
die Tasten gelesen werden, und was diese Sitzung gekostet hat, wo der Anbieter
es misst.

---

## Tasten

| Taste | Tut |
|---|---|
| `Enter` | sendet, was Sie getippt haben |
| `Tab` / `Shift+Tab` | nächster / vorheriger Modus |
| `Ctrl+K` | die Befehlspalette — jede Aktion, durchsuchbar |
| `Ctrl+B` | Werkbank öffnen oder schließen |
| `End` | zurück zur neuesten Ausgabe nach dem Hochscrollen |
| `PageUp` / `PageDown` | das Gespräch scrollen |
| `Ctrl+R` | eine Nachricht erneut senden, die der Kern abgelehnt hat |
| `Ctrl+C` | anhalten, was er tut; beenden, wenn er untätig ist |
| `Ctrl+D` | beenden |
| `Esc` | Palette schließen, ein Feld verlassen, oder die sichere Option einer Karte nehmen |

Jede Tastenkombination, die die Fußzeile zeigt, existiert; für eine Taste, die
nicht belegt ist, kann kein Hinweis gedruckt werden.

---

## Modi

```
ACT    liest, schreibt und führt Befehle aus; fragt, bevor er etwas ändert
PLAN   liest und plant; kann nichts schreiben, ausführen oder ändern
ASK    spricht es durch; gar keine Werkzeuge
```

`Tab` schaltet durch. Das Label bewegt sich, wenn der Kern bestätigt, nicht
wenn die Taste gedrückt wird: Drücke innerhalb einer Hin- und Rückreise sammeln
sich — drei Tabs fragen einmal, nach dem, worauf der dritte zeigte — und eine
abgelehnte Änderung sagt es in Worten, statt das Label zu bewegen.

---

## Wenn sie Sie etwas fragt

Eine Berechtigungskarte oder ein Frageformular nimmt die Tastatur, solange es
offen ist, damit eine Taste, die für eine Entscheidung gemeint war, nicht
zugleich eine Nachricht senden kann.

- **Pfeiltasten** bewegen sich zwischen den Wahlmöglichkeiten oder Fragen;
  **Enter** sendet.
- **Esc** nimmt die eigene sichere Option der Anfrage — bei einer Berechtigung
  ist das *ablehnen*, bei einem vorgeschlagenen Moduswechsel *keine
  Änderung* — und die Karte sagt, welche. Sie erlaubt nie etwas.
- Für *erlauben* gibt es keine Einzeltaste. Erlauben kostet einen Schritt zur
  Wahl und einen, um sie zu bestätigen, damit eine aus irgendeinem anderen Grund
  gedrückte Taste keinen Befehl autorisieren kann.
- Eine Frage mit einer Zeile zum Selbstschreiben öffnet dafür mit `Space` ein
  Feld; `Esc` verlässt das Feld, bevor es das Formular abbricht.

Zwei Dinge können zugleich warten — zwei parallele Werkzeuge können beide
fragen — und sie werden in der Reihenfolge ihres Eintreffens gezeigt, keines
geht verloren.

Modustasten funktionieren auch, während eine Karte offen ist. Die Palette
nicht: ein Starter über einer Entscheidung würde verdecken, was beantwortet
werden muss.

---

## Mitlesen

Eine lange Antwort hält die neueste Zeile im Blick. Scrollen Sie hoch, hört sie
auf zu folgen; neue Ausgabe zieht Sie nicht wieder herunter, und eine Markierung
sagt, dass unten mehr ist. `End` kehrt zum lebendigen Ende zurück, und eine neue
Nachricht zu senden tut dasselbe.

---

## Sitzungen

`Ctrl+K` → *Ein früheres Gespräch öffnen* listet, was der Kern behalten hat,
und öffnet eines an Ort und Stelle. Derselbe Speicher bedient den Browser, also
kann ein hier begonnenes Gespräch dort wieder geöffnet werden.

`comodor --resume` öffnet beim Start das jüngste; `--resume ID` nennt eines.

---

## Text herauskopieren

Markieren Sie mit der Maus, wie Ihr Terminal es erlaubt. Die Optionen
`--theme` und `--ascii` gelten für das, was die Befehle ausgeben — `setup`,
`doctor`, `help` — nicht für die Oberfläche, die aus ihren eigenen Design-Tokens
zeichnet.

---

## Text von rechts nach links

Persisch, Arabisch und gemischte Zeilen werden dem Terminal so übergeben, wie
sie geschrieben sind, nie vom Programm umgekehrt. Wie gut eine gemischte Zeile
geformt wird, ist Sache des Terminals, und die, die es gut können, können es
auch hier.

---

## Siehe auch

- [tui-v2.md](../tui-v2.md) — wie die Oberfläche gebaut ist, und was sie
  kann und noch nicht kann
- [questions.md](questions.md) — die Formulare, die der Agent Ihnen vorlegt
- [safety.md](safety.md) — was fragt, was nicht, und warum
- [computer.md](computer.md) — ihm Ihren Bildschirm überlassen
