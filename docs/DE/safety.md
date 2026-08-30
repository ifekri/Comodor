# Sicherheit und Berechtigungen

Was Comodor Ihrem Rechner antun kann, was es zuerst fragt, und was es nicht tut,
was auch immer Sie sagen.

---

## Die kurze Version

- **Lesen geschieht stillschweigend.** Dateien auflisten, lesen, durchsuchen —
  kein Prompt.
- **Schreiben fragt.** Sie sehen den Diff, bevor er passiert.
- **Einen Befehl ausführen fragt lauter**, und ebenso das Netzwerk erreichen
  oder Ihren Bildschirm steuern.
- **Alles Umkehrbare wird durch `/undo` umgekehrt.**
- **Es kann den Projektordner nicht verlassen**, außer Sie schalten das ab.
- **Ein Repository kann nichts von all dem ändern.**

---

## Risikostufen

Jedes Werkzeug deklariert eine. Die Stufe entscheidet, was passiert, bevor es
läuft.

| Stufe | Werkzeuge | Was passiert |
|---|---|---|
| **safe** | `read_file`, `list_dir`, `grep`, `glob`, `todo_write` | läuft |
| **write** | `write_file`, `edit_file` | fragt, mit einem Diff |
| **dangerous** | `run_shell`, `run_python`, `web_fetch`, `web_search`, `browse`, `computer` | fragt |

Im **Plan-Modus** wird alles über `safe` hinaus verweigert, bevor es läuft.
Das wird auf der Berechtigungsebene erzwungen, nicht indem man das Modell
bittet, sich zu benehmen.

Im **Chat-Modus** gibt es überhaupt keine Werkzeuge.

---

## Der Prompt

```
  Run  pytest tests/ -x
  ────────────────────────────────────────────
  in ~/projects/api-server

  [a] allow   [A] allow always this session   [d] deny
```

`A` merkt es sich für die Sitzung, je Art von Ding — Schreibvorgänge zu erlauben
erlaubt keine Befehle, und `pytest` zu erlauben erlaubt kein `rm`.

Um nicht mehr gefragt zu werden:

```
/approve writes      files yes, commands still ask
/approve shell       commands yes, files still ask
/approve all         everything
```

Oder dauerhaft, in Ihrer Konfiguration:

```json
{
  "safety": {
    "auto_approve_writes": true,
    "auto_approve_shell": false
  }
}
```

### Ablehnen lehrt es

Eine Verweigerung ist das deutlichste Präferenzsignal, das die Oberfläche je
sammelt. Es geht an die Lern-Engine, sodass der Agent weniger geneigt ist,
dasselbe wieder vorzuschlagen. Ablehnen ist keine vergebene Mühe.

---

## Prüfpunkte und `/undo`

Jede Datei, die der Agent schreibt, wird zuerst als Prüfpunkt gesichert — der
vorherige Inhalt, gehalten unter `.comodor/checkpoints/` im Projekt.

```
/undo
```

stellt die letzte von ihm geänderte Datei wieder her. Das funktioniert, ob Sie
den Schreibvorgang genehmigt haben oder nicht, und ob die Auto-Genehmigung an
ist oder nicht. Es ist der Grund, warum `/approve all` eine vernünftige Sache
ist.

Schalten Sie es ab, wenn Sie müssen:

```json
{ "safety": { "checkpoints": false } }
```

Es gibt keinen guten Grund dazu.

---

## Die Workspace-Grenze

Der Agent darf lesen und schreiben **im Projektordner und nirgendwo sonst**.

Die Projektwurzel wird gefunden, indem man von dort aufsteigt, wo Sie gestartet
haben, bis etwas sagt „das ist ein Projekt" — eine `.git`, ein `pyproject.toml`,
ein `package.json`. Es wird Ihnen gezeigt, und gefragt wird einmal pro Ordner:

```
  Work in  /home/you/projects/api-server ?
```

Genehmigte Ordner werden gemerkt. `--cwd` benennt einen direkt und fragt nicht.

```json
{ "safety": { "workspace_only": true } }
```

Das Abzuschalten lässt den Agenten Ihr gesamtes Dateisystem anfassen. Es ist
aus genau diesem Grund für die Konfiguration eines Repositorys gesperrt.

---

## Befehle, die es nicht ausführt

Manche Dinge werden verweigert, bevor irgendein Prompt erscheint, denn kein
Prompt sollte eine Person am Ende einer langen Sitzung zu ihnen überreden
können:

```
rm -rf /     rm -rf ~     mkfs        dd if=      shutdown
reboot       format c:    del /f /s /q c:         :(){
> /dev/sda   chmod -R 777 /
```

Die vollständige Liste ist `safety.deny_commands`. Fügen Sie eigene hinzu:

```json
{
  "safety": {
    "deny_commands": ["terraform destroy", "kubectl delete namespace"]
  }
}
```

`safety.allow_commands` ist die andere Richtung — Befehle, die nie fragen:

```json
{ "safety": { "allow_commands": ["git status", "pytest", "ls"] } }
```

---

## Ihre Schlüssel

**Wo sie leben.** Ihre eigene `~/.comodor/config.json`, geschrieben mit
nur-besitzer-Berechtigungen, oder Ihre Umgebung. Nirgendwo sonst.

**Wohin sie nie gehen.** Nicht in die Konfiguration eines Repositorys. Nicht in
die Oberfläche. Nicht in ein Log. Nicht in ein `repr` — das war ein echter Bug,
gefunden und behoben: Jeder Traceback, der ein Config nannte, druckte
früher den Schlüssel, und pytest druckt Tracebacks ständig.

**Ein Schlüssel in Ihrer Umgebung bleibt dort.** Wenn Sie `ANTHROPIC_API_KEY`
exportieren, statt ihn zu speichern, kopiert `/save` ihn nicht in Ihre
Konfigurationsdatei. Exportieren statt Speichern ist eine Entscheidung, und sie
wird respektiert.

**Schwärzung.** Alles, was wie einer Ihrer Schlüssel aussieht, wird maskiert in
der Werkzeugausgabe, in der Mitschrift und in Exporten. Es wirkt auf Text. Es
kann keine Pixel lesen — siehe
[Den Bildschirm benutzen](computer.md#what-goes-to-the-model).

---

## Was ein Repository setzen darf

Eine `.comodor/config.json` in einem Projekt wird aus welchem Verzeichnis auch
immer gelesen, in dem Sie gestartet sind — was für einen Coding-Agent bedeutet:
*aus einem Repository, das jemand anderes geschrieben hat, unmittelbar nach dem
Klonen*.

Deshalb ist sie auf Dinge beschränkt, die sich nicht gegen Sie wenden lassen:

| Ein Projekt darf setzen | |
|---|---|
| `provider`, `model` | welches Modell benutzt werden soll |
| `agent` | Modus, loop, die Budgets, Temperatur, Ausgabegröße |
| `ui` | Theme, Rahmen, Banner |
| `learning`, `skills` | ob sie an sind, und ihre Grenzen |
| `mcp.servers` | welche Server es benutzt — **ankommend abgeschaltet** |

| Ein Projekt darf **nicht** setzen | weil |
|---|---|
| `providers.*.base_url` | Ihr Schlüssel ginge bei der ersten Anfrage an ihren Server |
| `safety.*` | es könnte den Agenten vom Fragen abhalten oder die Verbotsliste leeren |
| `agent.system_prompt_extra` | Anweisungen, mit Ihrer Autorität injiziert |
| `browser.executable` | es benennt eine Binärdatei, die der Agent starten soll |
| `computer.*` | es fragt die Maschine, auf die es gerade geklont wurde, nach Ihrer Maus |
| `mcp.enabled` | einen Server zu deklarieren ist ein Vorschlag; einen zu starten ist eine Entscheidung |

Das ist eine **Erlaubnisliste**, keine Verbotsliste, sodass eine Einstellung,
die nächstes Jahr hinzukommt, nicht vertrauenswürdig ist, bis jemand anders
entscheidet — die richtige Herumrichtung, um falsch zu liegen.

Verweigerungen werden laut ausgesprochen:

```
config: this project cannot set safety, computer — only your own can
```

Die Datei von jemandem stillschweigend zu ignorieren ist die Art, wie eine
Konfigurationsdatei einen Ruf bekommt, nicht zu funktionieren.

---

## Decken

Drei, und sie gelten für jede Aufgabe:

```json
{
  "agent": {
    "max_steps": 24,
    "max_seconds": 900,
    "max_cost_usd": 2.0
  }
}
```

**Die Gelddecke funktioniert nur für ein Modell mit veröffentlichtem Tarif.**
Für ein Modell, das die Preistabelle nicht kennt, zeigt der Kostenmesser null,
und das Limit löst nie aus. Comodor sagt es, statt Sie glauben zu lassen, Sie
hätten eine Decke:

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Gesagt am Beginn einer Sitzung und in `comodor doctor`. Siehe
[Kosten](cost.md).

---

## Sub-Agents

`delegate` führt einen Sub-Agenten in einem git worktree aus — einer isolierten
Kopie des Repositorys. Er hat kein Gedächtnis, kann nicht weiter delegieren,
und **bekommt den Bildschirm nicht**: Ein Sub-Agent, der in einem Worktree
arbeitet, hat kein Recht, Ihre Maus zu nehmen.

---

## Etwas melden

Wenn Sie ein Sicherheitsproblem finden, öffnen Sie bitte kein öffentliches
Issue. Siehe [SECURITY.md](../SECURITY.md).

---

## Siehe auch

- [Den Bildschirm benutzen](computer.md) — das strengste Berechtigungsmodell hier
- [Konfiguration](configuration.md) — wo jede Einstellung lebt
- [Die Oberfläche](interface.md#approvals) — wie die Prompts aussehen
