# Erste Schritte

Fünf Minuten, endend damit, dass der Agent etwas Nützliches tut.

---

## 1. Installation

Eine Zeile. Den Rest erledigt es selbst.

**macOS · Linux · BSD**

```bash
curl -fsSL get.comodor.ai | sh
```

**Windows** — PowerShell

```powershell
irm get.comodor.ai | iex
```

```
Comodor — it learns the way you correct it.

  Linux x86_64
> Installing uv, a package manager Comodor needs (about 15 MB)
  from https://astral.sh/uv — it fetches a Python too, if one is missing
> Installing with uv

✓ comodor 0.9.0

  Linked into /usr/local/bin, which is on your PATH.

  comodor              start the interface
  comodor --demo       try it offline, no API key needed
  comodor doctor       check what is configured
```

**Eine Adresse für beide.** `get.comodor.ai` nennt keine Datei. Es erkennt,
welcher Client fragt, und schickt `curl` und `wget` zum Shell-Installer,
PowerShell zum Windows-Installer und einen Browser auf diese Seite — die
Zeile, die Sie einfügen, ist also auf jedem System dieselbe, und Sie müssen
nie selbst wählen.

**Es macht fertig.** Wer eine Zeile von einer Web-Seite aus ausführt, hat sich
nicht bereit erklärt, irgendetwas zu debuggen. Also installiert das Skript,
was es braucht — eine isolierte Umgebung, einen Paketmanager, ein Python —,
statt stehen zu bleiben und zu erklären, was Sie längst haben sollten.
Verifiziert auf einem nackten `debian:bookworm-slim` ohne jedes Python.

### Danach fast nie etwas eintippen

Wo es kann, legt es `comodor` dorthin, wo Ihre Shell bereits sucht, sodass es
im Terminal funktioniert, aus dem Sie es gestartet haben — kein `export`,
kein neues Fenster. Das deckt root, Container, CI und jeden Mac mit Homebrew ab.

Wo es das nicht kann — ein gewöhnliches Linux-Konto, auf dem nichts auf `PATH`
beschreibbar ist —, hilft kein Installer, denn ein Kindprozess kann die
Umgebung der Shell, die ihn gestartet hat, nicht ändern. Es sagt es daher so:

```
  Every new terminal can run comodor already.
  This one started before the install, and no installer
  can reach back into the shell that ran it. For this
  terminal only:

    export PATH="/home/you/.local/bin:$PATH"
```

Ein neues Terminal öffnen, und es funktioniert einfach. Die Zeile landet sowohl
in der rc-Datei Ihrer Shell als auch in Ihrem Login-Profil, sodass jede Art von
Shell sie findet — interaktiv, Login, nicht-interaktiv und eine Desktop-Sitzung.

### Wenn Sie ein Skript lieber nicht in eine Shell pipen

Völlig vernünftig. Beide Skripte sind Klartext, den Sie vorher lesen können —
direkt benannt, weil die Kurzadresse alles, was kein Fetcher ist, auf die Seite
schickt:

```bash
curl -fsSL https://comodor.ai/install.sh  | less
curl -fsSL https://comodor.ai/install.ps1 | less
```

Oder benutzen Sie einen Paketmanager, den Sie bereits haben:

```bash
uv tool install comodor      # isolated, and the fastest
pipx install comodor         # isolated
pip install comodor          # into whatever environment you are in
```

Comodor braucht **Python 3.11 oder neuer** und sonst nichts.

### Prüfen, dass es angekommen ist

```bash
comodor --version
```

Wenn die Shell es nicht findet, hat der Installer ein Verzeichnis zu Ihrem
`PATH` hinzugefügt, das dieses Terminal noch nicht kennt. Öffnen Sie ein neues,
oder führen Sie die `export`-Zeile aus, die der Installer ausgegeben hat.

### Optionen, die die Installer verstehen

| | |
|---|---|
| `COMODOR_FORCE_TOOL` | die Methode festnageln: `uv`, `pipx`, `venv` oder `pip` |
| `COMODOR_NO_BOOTSTRAP` | niemals ein Werkzeug herunterladen; stattdessen fehlschlagen |
| `COMODOR_NO_MODIFY_PATH` | Ihr Shell-Profil nicht anfassen |
| `COMODOR_INSTALL_REF` | aus einem git ref oder einem lokalen Pfad statt von PyPI installieren |

```bash
COMODOR_NO_MODIFY_PATH=1 curl -fsSL get.comodor.ai | sh
```

> **Noch nicht sicher, ob Sie es installieren wollen?** `comodor --demo` führt
> die gesamte Oberfläche gegen einen skriptgesteuerten Offline-Provider aus.
> Kein Schlüssel, kein Konto, kein Netzwerk.

---

## 2. Ein Modell wählen

Starten Sie es. Beim ersten Mal stellt es sechs Fragen und fragt nie wieder.

```bash
comodor
```

```
 1/6  Which model provider?
┌─  Providers  ───────────────────────────────────────────┐
│ ›  OpenRouter        One key, hundreds of models         │
│    Anthropic         Claude, direct from the source      │
│    OpenAI            GPT models, direct                  │
│    Ollama (local)    Runs on your machine. No key        │
└──────────────────────────────────────────────────────────┘
  ↑↓ move   enter choose   tab more   esc cancel
```

Pfeiltasten, oder tippen zum Filtern. **Tab** öffnet die vollständige
Beschreibung dessen, worauf der Pfeil gerade steht, im selben Rahmen — die
Listen zeigen eine Zeile pro Eintrag, damit sie auf den Bildschirm passen,
und manche dieser Beschreibungen sind ein Absatz lang.

Bei einer Pipe oder in einem Skript kommen dieselben Fragen als nummerierte
Liste, sodass sich das automatisieren lässt.

**Kein Schlüssel und kein Geld?** Wählen Sie **Ollama** oder **LM Studio**.
Sie laufen auf Ihrem Rechner, brauchen keinen Schlüssel und kosten nichts.
Alles in dieser Dokumentation funktioniert mit ihnen, außer den Teilen, die
etwas anderes sagen.

**Benutzen Sie bereits OpenClaw oder Hermes?** Der erste Bildschirm bietet an,
Ihre Schlüssel, Ihr Modell und Ihre Skills herüberzuholen. Nichts wird
verschoben und nichts, was hier bereits gesetzt ist, wird ersetzt. Siehe
[Von einem anderen Agenten kommend](migrating.md).

Ihre Antworten landen in `~/.comodor/config.json`, nur von Ihnen lesbar.
Später ändern Sie Ihre Meinung mit `comodor setup`, oder Einstellung für
Einstellung — siehe [Konfiguration](configuration.md).

### Die letzte Frage ist Ihr Handy

```
 6/6  Run it from your phone?
┌─  From your phone  ─────────────────────────────────────────────┐
│ ›  Not now    you can set any of them up later                   │
│    Telegram   one token from @BotFather — about a minute         │
│    Slack      an app from a manifest, two tokens — five minutes  │
│    WhatsApp   a Meta app and a public address — twenty minutes   │
└──────────────────────────────────────────────────────────────────┘
```

**Telegram** nimmt einen Token von [@BotFather](https://t.me/botfather),
prüft ihn direkt dort gegen Telegram und zeigt einen Code, den Sie dem Bot
schicken, damit er weiß, welchem Konto er antworten soll — eine Minute,
von Anfang bis Ende. Siehe [Vom Handy aus](telegram.md).

**Slack** dauert etwa fünf. Die App wird aus einem Manifest erstellt, das
Comodor ausgibt, sodass ein einziger Einfügevorgang genügt statt einer Seite
von Checkboxen, und Socket Mode bedeutet gar keine öffentliche Adresse —
siehe [Aus Slack](slack.md).

**WhatsApp** tut dasselbe und dauert etwa zwanzig Minuten: eine Meta-App, eine
Geschäftsnummer, ein App-Geheimnis und eine öffentliche HTTPS-Adresse, von
denen sich keines aus einem Terminal erstellen lässt. Es lohnt sich nur, wenn
es WhatsApp sein muss — siehe [Aus WhatsApp](whatsapp.md).

In beiden Fällen liest und plant es nur, bis Sie etwas anderes sagen, und ein
Nein kostet einen Tastendruck.

### Und dann bietet es an zu starten

```
 What now?
   1  Start Comodor          — the interface, here in this terminal
   2  Start the Telegram bot — in the background, answers while this is closed
   3  Both
   4  Nothing yet            — `comodor` starts it whenever you want
```

Das Setup endete früher an dieser Stelle, zurück am Shell-Prompt ohne etwas
Laufendes. Eine Handyzeile erscheint für jeden Kanal, der verbunden und
gekoppelt ist, namentlich — wer WhatsApp eingerichtet hat, bekommt nicht
„den Telegram-Bot" angeboten.

---

## 3. Es fragt, in welchem Ordner

```
  Work in  /home/you/projects/api-server ?
```

Einmal pro Ordner gefragt. Alles, was der Agent anfassen darf, liegt darunter —
ohne Ihr bewusstes Abschalten kann es weder außerhalb lesen noch schreiben.
Genehmigte Ordner werden gemerkt.

---

## 4. Um etwas bitten

Eintippen und Enter drücken.

```
> the tests in tests/test_parser.py are failing, work out why and fix it
```

Es wird Dateien lesen, die Tests laufen lassen und etwas ändern. Bevor es eine
Datei schreibt, bekommen Sie einen Diff und eine Wahl:

```
  Write  src/parser.py
    - 12 lines removed, 8 added
  [a] allow   [A] allow always this session   [d] deny
```

Antworten Sie `a` einmalig, oder `A`, wenn es für den Rest der Sitzung lieber
aufhören soll zu fragen. Jeder Schreibvorgang wird so oder so als Prüfpunkt
gesichert: `/undo` stellt den letzten wieder her.

---

## 5. Es korrigieren — das ist der Teil, der zählt

Wenn es etwas falsch macht, sagen Sie es ihm. Zwei Wege, und beide lehren es
dasselbe:

**Ändern Sie die Datei selbst.** Comodor bemerkt, was Sie an seiner Ausgabe
ändern.

**Sagen Sie es.**

```
> no — we use single quotes in this codebase, not double
```

So oder so wird daraus eine Lektion: beim nächsten Mal abgerufen, wenn die
Situation ähnlich aussieht, mit einem Vertrauenswert, der steigt, wenn sie
sich bewährt, und verfällt, wenn nicht.

Nach einigen Sitzungen:

```
> /progress
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

Das ist ein Beleg, keine Behauptung. Fällt die Korrekturrate nicht, funktioniert
das Lernen nicht, und das Panel sagt das, statt es zu verbergen.

[Wie er lernt](learning.md) erklärt den Mechanismus.

---

## 6. Was man am ersten Tag wissen sollte

```
/help          every command
/mode          act · plan (read-only) · chat (no tools)     F3 cycles
/undo          restore the last file it changed
/cost          tokens, spend, what the cache saved
Esc            stop it, mid-thought
Ctrl-C twice   leave
```

---

## Wohin als Nächstes

| Sie möchten | Lesen Sie |
|---|---|
| Es ohne die Oberfläche benutzen, in einem Skript | [Aus dem Terminal](cli.md) |
| Genauso wissen, was es Ihrem Rechner antun kann | [Sicherheit und Berechtigungen](safety.md) |
| Weniger zahlen | [Kosten](cost.md) |
| Ihm einen Browser erlauben | [Der echte Browser](browser.md) |
| Ihm Maus und Tastatur erlauben | [Den Bildschirm benutzen](computer.md) |
| Einen Ablauf schreiben, dem es jedes Mal folgt | [Skills](skills.md) |
| Es auf einem Server oder in Docker betreiben | [Aus dem Browser](web.md), [In Docker](docker.md) |

---

## Wenn etwas schiefgegangen ist

```bash
comodor doctor
```

Es prüft alles, was es kann, und sagt Ihnen, was Sie gegen alles Gefundene tun
sollen. `comodor doctor --fix` repariert das Reparierbare. Siehe
[Fehlerbehebung](troubleshooting.md).
