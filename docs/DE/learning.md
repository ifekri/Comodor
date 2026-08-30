# Wie es lernt

Die meisten Agenten vergessen in dem Moment, in dem eine Sitzung endet.
Dieser beobachtet, was du an seiner Ausgabe änderst, und behält es.

---

## Die Idee

Lob ist billig und Korrekturen sind teuer, also lernt er von den
Korrekturen.

Wenn du eine Datei bearbeitest, die er schrieb, oder ihm klar sagst, dass
er falsch lag, wird das eine **Lektion**: eine kurze Regel mit einer
Zuverlässigkeit, die jedes Mal steigt, wenn sie hält, und abfällt, wenn sie
ungenutzt bleibt. Lektionen werden abgerufen, wenn die Situation ähnlich
aussieht, und in diesen Zug eingespeist — nie in den System-Prompt, was den
Prompt-Cache kosten würde.

Nichts verlässt deine Maschine. Das Gehirn ist eine SQLite-Datei unter
deinem Konfigurationsverzeichnis.

---

## Die zwei Bahnen

### Reflex — gratis, sofort, immer an

Kein Modellaufruf, keine Token, keine Verzögerung.

- **Korrekturen.** Du änderst `"` zu `'` in einer Datei, die er schrieb.
  Das ist ein Diff, und ein Diff ist eine Tatsache.
- **Regeln.** Er liest deinen bestehenden Code einmal, am Anfang, und
  zieht Konventionen daraus — Einrückung, Anführungsstil, wie Tests
  benannt sind.
- **Ankündigungen.** Wird eine Regel angewendet, sagt er es, in einer
  Zeile. Eine Regel, die du nicht sehen kannst, ist eine Regel, die du
  nicht korrigieren kannst.
- **Vorausladen.** Der Abruf beginnt, während du noch tippst.

Diese Bahn ist an, selbst wenn die Reflexion ausgeschaltet ist, denn sie
kostet nichts.

### Reflexion — ein Modellaufruf, nach einer Aufgabe

Am Ende einer Aufgabe sieht er sich an, was geschah, und schreibt auf, was
er sich merken sollte. Dieser kostet einen Aufruf. Nimm dafür ein
günstigeres Modell, wenn du magst:

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

Oder schalte es ab und behalte Reflex:

```json
{ "learning": { "reflect": false } }
```

---

## Es absichtlich lehren

| | |
|---|---|
| `/good` | diese Antwort war richtig |
| `/bad` | diese Antwort war falsch |
| `/teach we use pytest, never unittest` | merke dir das |

`/good` und `/bad` kosten einen Tastendruck und sind das Billigste, was du
für ihn tun kannst.

Einen Berechtigungsdialog abzulehnen lehrt ihn ebenfalls. Eine Ablehnung
ist das klarste Präferenzsignal, das die Oberfläche einsammelt, und es wird
als eines behandelt.

---

## Sehen, was er weiß

```
/memory
```

Eine durchsuchbare Liste — jede Lektion mit dem, was sie auslöst, was sie
sagt, ihrer Art und ihrer aktuellen Zuverlässigkeit:

```
┌─  Memory (23)  ────────────────────────────────────────────────────┐
│ ›  #41 writing Python strings                                      │
│      Use single quotes for string literals.  [style 91%]           │
│    #38 adding a test                                               │
│      Tests go in tests/, mirroring the src layout.  [layout 84%]   │
│    #29 adding a dependency                                         │
│      Ask before adding one; this project has exactly one.  [78%]   │
│    #12 parsing empty input                                         │
│      Raise, do not return an empty list.  [behaviour 62%]          │
└────────────────────────────────────────────────────────────────────┘
  ↑↓ move   enter open   type filter   esc close
```

`/memory <text>` durchsucht. Eines zu öffnen lässt dich es anheften, sodass
es nicht mehr abfällt, oder löschen, falls es falsch war.

```
/rules
```

Die Hausregeln, die er aus deinem Code zog, statt dir zu sagen, sie ihm zu
übermitteln.

---

## Sehen, ob es funktioniert

```
/progress
```

```
◈ Corrections per task down 100% since the first tasks in this project.

metric                trend                       now  vs first
Steps per task        ▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇    6.1      ↑10%
Corrections per task  ████████▅▅▅▅▅▅▅▅▁▁▁▁▁▁▁▁    0.0     ↓100%
Approvals asked       ▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅    2.0         —
Tokens per task       ▁▁▁▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▇▇▇███  12.0K      ↑40%
First-try success     ▁██████▁██████▁██████▁██    86%         —

brain    7 rules · 812 lessons · 24 corrections learned from
history  24 tasks over 8 days
success  83% overall
```

**Die Zeile oben ist die, die zählt.** Fallen die Korrekturen pro Aufgabe
nicht, lernt er nicht — und das Panel führt das so oder so an der Spitze,
statt es unter Aktivität zu vergraben. Alles andere in der Tabelle ist
Aufwand; das eine ist Ergebnis.

---

## Abruf und warum er nicht im System-Prompt steht

Abgerufene Lektionen reiten auf dem Zug, als Teil der
Benutzernachricht, nicht im System-Prompt.

Das ist eine Kostenentscheidung. Prompt-Caching wirkt nur auf einen
byteidentischen Präfix, und der System-Prompt ist der Präfix. Irgendetwas
abfrageabhängiges hineinzustellen entwertet den Zwischenspeicher bei jedem
einzelnen Zug. Den Abruf auf den Zug zu verlagern hob die gemessenen
Cache-Trefferquoten von 72 % auf 87 %. Siehe [Kosten](cost.md).

---

## Wörter, die er von dir lernt

Er lernt auch, welche *deiner* Wörter zusammengehören, aus deinen eigenen
abgeschlossenen Aufgaben — dass „der Parser" und „tokenisieren" zur
selben Ecke deiner Codebasis gehören. Das kostet keine Token und keinen
Modellaufruf; es ist Zählen.

Das ist es, was bewirkt, dass eine über „den Tokenisierer" aufgezeichnete
Lektion auftaucht, wenn du nach „dem Lexer" fragst.

```json
{ "learning": { "associative": true } }
```

---

## Geltungsbereich

```json
{ "learning": { "share_scope": "project" } }
```

`project` hält Lektionen in dem Repository, in dem sie gelernt wurden — die
richtige Voreinstellung, denn eine Konvention in einer Codebasis ist in
einer anderen falsch. `global` teilt sie überall.

---

## Vergessen

Eine ungenutzte Lektion fällt ab. `half_life_days` (45 standardmäßig)
setzt, wie schnell, und `min_confidence` (0.15) ist die Untergrenze, unter
der er aufhört, sie abzurufen.

Das zählt: Eine Codebase ändert ihre Meinung, und ein Agent, der eine
zwei Jahre alte Konvention mit völliger Zuversicht hält, ist schlechter als
einer, der vergaß.

---

## Abschalten

```json
{ "learning": { "enabled": false } }
```

Alles funktioniert weiter. Er fängt nur jede Sitzung als Fremder an.

---

## Wo er lebt

```
~/.comodor/brain.db
```

SQLite. Deins. `comodor uninstall` entfernt es und sagt, wie viel es war.

---

## Siehe auch

- [Skills](skills.md) — Verfahren, die du schreibst, statt Lektionen, die er folgert
- [Kosten](cost.md) — warum der Abruf auf dem Zug liegt und nicht im Präfix
