# Kosten

Was eine Sitzung kostet, und wie man sie billiger macht, ohne sie schlechter
zu machen.

```
/cost
```

```
This session

- prompt tokens: 84,210
- output tokens: 3,180
- served from cache: 72,418 (86% of the prompt)
- cost: $0.1904
- saved by caching: $0.4126 (68%)
- context used: 87,390 / 1,000,000
- compactions: 0

Brain

- lessons: 812
- skills: 4
- episodes: 137 (83% succeeded)
```

---

## Prompt-Caching, das der Großteil davon ist

Jede Anfrage sendet die Teile neu, die sich nicht ändern — den System-Prompt,
die Werkzeugschemata, die bisherige Konversation. Anbieter liefern einen
byte-identischen Präfix für etwa ein Zehntel des Preises neu aus.

Comodor ist darauf aufgebaut, und es ist standardmäßig an:

```json
{ "agent": { "prompt_cache": true, "prompt_cache_ttl": "5m" } }
```

An echten Sitzungen gemessen: **86% der Input-Tokens aus dem Cache bedient**.

### Warum nichts Dynamisches in den System-Prompt kommt

Caching funktioniert nur auf einem Präfix, der byte-identisch zum letzten Mal
ist. Der System-Prompt *ist* der Präfix. Alles, was sich pro Zug ändert —
abgerufene Lektionen, der passende Skill, die Tageszeit — invalidiert ihn, und
Sie zahlen den vollen Preis für alles, bei jedem Zug.

Deshalb reisen abgerufene Lektionen auf dem *Zug*, als Teil der
Benutzernachricht. Diese eine Änderung hob die gemessene Cache-Trefferquote von
72% auf 87%.

Wenn Sie eigene stehende Anweisungen hinzufügen, legen Sie sie in
`agent.system_prompt_extra` ab, das stabil ist, statt sie zu variieren.

### Der Ein-Stunden-Cache

```json
{ "agent": { "prompt_cache_ttl": "1h" } }
```

Kostet beim *Schreiben* eines Eintrags etwa 25% mehr und hält ihn eine Stunde
statt fünf Minuten. Wert, wenn Sie immer wieder zu einer Sitzung zurückkehren;
verschwenderisch für eine einzelne Arbeitsphase.

---

## Decken

```json
{
  "agent": {
    "max_steps": 0,
    "max_seconds": 3600,
    "max_cost_usd": 2.0
  }
}
```

Was zuerst kommt, stoppt die Aufgabe, und `0` bedeutet kein Limit. `stopped`
in `--json` sagt, welches es war.

**Es gibt standardmäßig kein Schrittlimit.** Vierundzwanzig Schritte sind nichts
auf einer echten Codebasis — ein Refactor über ein Dutzend Dateien ging ihnen
mitten im Gedanken aus — und eine Schrittanzahl hat keine Beziehung zu Schaden:
zehn Schritte, die Dateien lesen, kosten fast nichts. Die Decken, die Schaden
entsprechen, sind Zeit und Geld, und die bleiben an. Setzen Sie `max_steps` auf
eine Zahl, wenn Sie einen harten Stopp zurück wollen.

Wenn eine davon eine Aufgabe stoppt, sagt die Nachricht, wie man darüber
hinausgeht, und „continue" macht von dort weiter, wo es war.

### Wenn das Limit nicht auslösen kann

**Eine Ausgabenbegrenzung funktioniert nur für ein Modell mit veröffentlichtem
Tarif.**

Die Preistabelle lässt Tarife bewusst für Modelle ungesetzt, bei denen es sich
nicht sicher ist — einen Preis zu erzeugen liefert falsche Zahlen, was schlimmer
ist als keine. Für ein unpreisgestaltetes Modell zeigt der Kostenmesser null,
also ist `spent >= max_cost_usd` nie wahr und das Limit löst nie aus.

Comodor sagt es, statt Sie glauben zu lassen, Sie seien geschützt:

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Gesagt am Beginn einer Sitzung, und in `comodor doctor`:

```
  warn  spend limit    $2.00 per task cannot be enforced for gpt-4o
                       → No published rate is known for this model, so the
                         cost meter reads zero and the limit never fires.
                         The step and time limits still apply.
```

Für ein Modell auf Ihrem eigenen Rechner sagt es etwas anderes, denn dort
kostet es ohnehin nichts.

---

## Was tatsächlich Geld kostet

**Screenshots.** Etwa 1.600 visuelle Tokens je Stück beim Standardbudget — und
das wiederum bei jedem Zug, in dem sie in der Konversation bleiben. Comodor
behält die letzten zwei und ersetzt den Rest durch eine Zeile, die sagt, dass
eines da war. Ohne das trägt eine dreißigschrittige Desktop-Aufgabe nahe an
fünfzigtausend Tokens aus Pixeln mit sich herum, die Bildschirme beschreiben,
die seitdem angeklickt wurden.

```json
{ "agent":    { "keep_screenshots": 2 } }
{ "computer": { "screenshot_tokens": 1600 } }
```

Setzen Sie `screenshot_tokens` nicht zu niedrig. Ein Bild, das das Modell nicht
lesen kann, ist schlimmer als kein Bild: Es rät, statt zu fragen. Siehe
[Den Bildschirm benutzen](computer.md#screenshots-and-what-they-cost).

**Große Werkzeugausgabe.** Begrenzt durch `agent.max_tool_chars`. Was nicht
passt, wird in eine Datei geschrieben, der gesagt wird, wie sie zu lesen ist,
sodass es nur zahlt, wenn es nachsieht.

**Reflexion.** Ein Modellaufruf am Ende einer Aufgabe. Richten Sie ihn auf ein
billigeres Modell:

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

Oder schalten Sie ihn ab. Die freie Spur — Korrekturen, Regeln, Ankündigungen —
arbeitet so oder so weiter. [Wie er lernt](learning.md#the-two-lanes).

**Der Browser, wenn er hinschaut.** `browse` gibt standardmäßig Text zurück und
nur auf Verlangen einen Screenshot, denn ein Bild einer Seite kostet jedes Mal
dasselbe und lässt sich nicht stutzen.

---

## Nichts ausgeben

```bash
ollama pull qwen2.5-coder:14b
comodor setup       # choose Ollama
```

Alles in dieser Dokumentation funktioniert, ohne Kosten, außer wo es etwas
anderes sagt. [Ein Modell wählen](models.md#running-it-locally-for-nothing).

---

## Siehe auch

- [Ein Modell wählen](models.md) — was jeder Anbieter für was berechnet
- [Konfiguration](configuration.md#agent--how-it-works) — jeder Regler
