# Skills

Ein Skill ist eine geschriebene Prozedur, der der Agent folgt, wenn die Arbeit
sie verlangt.

Nicht ein Prompt, den Sie jedes Mal einfügen — eine Datei, die er von selbst
lädt, wenn die Situation passt.

---

## Einige bekommen

`comodor setup` bietet die Bibliothek einmal an, am Ende. Mit den Pfeiltasten
bewegen, **Leertaste** drücken, um so viele anzukreuzen, wie Sie wollen, und
**Enter** installiert alle. Nichts ist am Anfang angekreuzt, und Enter mit
nichts Angekreuztem nimmt keins — Sie bekommen nie etwas, nach dem Sie nicht
gefragt haben.

```
┌─ Skills ──────────────────────────────────────────────────┐
│    ☑ review        Review a change before it is committed │
│ ›  ☐ commit-style  Match the commit messages already here │
│    ☑ python-tests  Write tests the way this project does  │
└───────────────────────────────────── 2 selected ──────────┘
  ↑↓ move   space select   enter install 2   tab more   esc cancel
```

**Eine Zeile je Skill**, sodass die ganze Liste auf einen Bildschirm passt,
wie lang die Bibliothek auch wird, und das Fenster folgt dem Pfeil, statt
hinter ihm herzuhinken. Manche dieser Beschreibungen laufen auf einen Absatz
hinaus — **Tab** öffnet die vollständige für das, worauf der Pfeil gerade steht,
im selben Rahmen, und nochmal Tab schließt sie.

Tippen filtert die Liste, was schneller ist als Scrollen, sobald es mehr als
eine Handvoll sind. Häkchen bleiben beim Filtern erhalten, sodass Sie die Liste
verengen, etwas ankreuzen, den Filter löschen und etwas anderes ankreuzen
können.

Ohne Terminal kann es übernehmen — eine Pipe, ein Skript, `curl | sh` — dieselbe
Frage wird als nummerierte Liste gestellt, eine Seite nach der anderen:

| | |
|---|---|
| `1,3` oder `1 3` | diese nehmen |
| `m` / `b` | nächste Seite, vorherige Seite |
| `/word` | nur zeigen, was passt |
| `?7` | die ganze Beschreibung der Nummer 7 lesen |
| enter | fertig |

Die Nummern sind absolut: Nummer 92 ist der zweiundneunzigste Skill, egal
welche Seite oder Suche Sie gerade ansehen, sodass eine Nummer, die Sie sich
notiert haben, die Nummer bleibt, die Sie tippen.

---

## Einen benutzen

```bash
comodor skills browse            # what is available
comodor skills add review        # install it
comodor skills list              # what you have
```

```
/skills                          # the same, in the interface
```

Von da an, wenn Sie um etwas bitten, das ein Skill abdeckt, wird er geladen,
und der Agent folgt ihm. Sie werden informiert, wenn das passiert:

```
  ▸ skill: review — Review a change for correctness before it is committed
```

Ein Skill, dessen Anwendung Sie nicht sehen können, ist ein Skill, den Sie
nicht korrigieren können.

---

## Einen schreiben

Ein Ordner mit einer `SKILL.md` darin:

```
~/.comodor/skills/our-tests/SKILL.md
```

```markdown
---
name: our-tests
description: How tests are written and run in this project.
---

# Tests in this project

- pytest, never unittest.
- One file per module, mirroring `src/`.
- Name the test after the behaviour, not the function:
  `test_an_empty_input_raises`, not `test_parse_2`.
- Never mock what you can construct.

## Running them

    uv run pytest -x -q

Not `python -m pytest` — the project needs the venv's own interpreter.
```

Die **Beschreibung** ist das Wichtigste. Sie ist das, womit Comodor Ihre
Anfrage abgleicht, um zu entscheiden, ob es den Skill überhaupt laden soll —
schreiben Sie sie als die Situation, nicht als einen Titel.

Neustart, oder `/skills`, und sie ist da.

### Dateien bündeln

Ein Skill kann Dateien neben `SKILL.md` mitführen:

```
~/.comodor/skills/our-tests/
  SKILL.md
  references/
    fixtures.md
    conventions.md
```

`SKILL.md` verweist auf sie; der Agent liest eine erst, wenn er sie braucht.
Das hält den Skill selbst kurz — was wichtig ist, denn der Skill wird in den
Zug geladen, und ein langer kostet Tokens, ob die Detailtiefe nun gebraucht
wurde oder nicht.

---

## Je Projekt

```
./.comodor/skills/<name>/SKILL.md
```

Mit dem Repository eingecheckt, sodass alle, die daran arbeiten, dieselben
Prozeduren bekommen. Die Skills eines Projekts werden neben Ihren geladen.

---

## Das Budget

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000
  }
}
```

`top_k` ist, wie viele für einen Zug geladen werden dürfen; `max_tokens` ist
die Decke auf das, was sie zusammen kosten dürfen. Ein Skill, zu groß, um zu
passen, wird übersprungen, und Ihnen wird gesagt, welcher — Schweigen hier war
einmal ein echter Bug, bei dem ein übergroßer Skill stillschweigend kleinere
verdrängte.

---

## Sie verwalten

```bash
comodor skills add review taste output    # several at once
comodor skills update                     # refresh installed ones
comodor skills remove review
comodor skills list                       # with versions
```

---

## Siehe auch

- [Wie er lernt](learning.md) — Lektionen, die er erschließt, statt Prozeduren, die Sie schreiben
- [Was der Agent kann](tools.md) — die Werkzeuge, denen ein Skill beibringt, wie man sie benutzt
