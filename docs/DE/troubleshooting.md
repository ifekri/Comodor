# Fehlerbehebung

## Hier anfangen

```bash
comodor doctor
```

Er prüft die Konfigurationsdatei und ihre Berechtigungen, den Anbieter, das
Modell, das Ausgabenlimit, das Gehirn, den Suchindex, deine Skills,
übriggebliebene Dateien, MCP-Server und, ob es eine neuere Veröffentlichung
gibt.

```bash
comodor doctor --fix
```

repariert, was reparabel ist. Er ändert nie etwas, das er nicht vorher
gemeldet hat.

---

## Er startet nicht

**`comodor: command not found`, direkt nach der Installation** — das
Installationsprogramm hat ihn auf deinen `PATH` gelegt, aber ein
Kindprozess kann die Umgebung der Shell, die ihn startete, nicht ändern.
Jedes *neue* Terminal funktioniert bereits. Für das, in dem du gerade bist,
hat das Installationsprogramm die einzufügende Zeile ausgegeben; oder:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`comodor: command not found`, in einem neuen Terminal** — das ist ein
echtes Problem. `python -m comodor` bestätigt, ob er überhaupt installiert
ist, und `ls ~/.local/bin/comodor`, wo er sein sollte.

**`No provider is configured`** — führe `comodor setup` aus, oder exportiere
einen Schlüssel:

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

**Python zu alt.** Comodor braucht 3.11 oder neuer. Prüfe mit `python
--version`.

---

## Eine Einstellung scheint nichts zu bewirken

Comodor sagt dir, wenn er eine ablehnt:

```
config: agent.max_steps must be a whole number; keeping 0
config: this project cannot set safety, computer — only your own can
```

Wird nichts gesagt und es bleibt wirkungslos, prüfe, welche Ebene gewinnt:

```
/settings          # what is actually loaded
```

```bash
comodor doctor     # the same, plus where every file is
```

Ein `--model` auf der Befehlszeile schlägt deine Konfigurationsdatei, und
ein Schlüssel in deiner Umgebung schlägt einen in der Datei. Das ist mit
Absicht so — [Konfiguration](configuration.md#what-wins).

---

## `/save` hat nicht gespeichert, was ich erwartete

Mit Absicht. Es schreibt **nur das, was du gewählt hast** — nicht die
Einstellungen eines Repositorys, nicht einen Schlüssel, den du in deiner
Umgebung hältst, nicht eine Option, die du für einen Lauf übergabst.

Um die Einstellung eines Repositorys zu deiner zu machen, setze sie selbst
zuerst (`/model x`) und speichere dann.

---

## Anfragen scheitern

**`401` oder `invalid api key`** — der Schlüssel ist falsch, abgelaufen,
oder gehört einem anderen Anbieter. `comodor doctor` zeigt, welcher
Anbieter aktiv ist.

**`404 model not found`** — dieser Anbieter liefert diese Modell-id nicht.
`/model` listet, was er tatsächlich anbietet.

**Zeitüberschreitungen.** Ein lokales Modell auf einer bescheidenen Maschine
kann wahrhaftig Minuten brauchen. Erhöhe `providers.<name>.timeout`.

**Er hört zu früh auf.** Sieh dir `stopped` an. `max_steps` und `budget`
sind Deckel, die ihre Arbeit tun, keine Fehlschläge. Erhöhe sie für einen
Lauf mit `--max-steps`, oder dauerhaft unter `agent`.

---

## Das Ausgabenlimit funktioniert nicht

Es kann vermutlich nicht sein, und Comodor sagt es. Siehe
[Kosten — wann das Limit nicht auslösen kann](cost.md#when-the-limit-cannot-fire).

---

## Das Browser-Werkzeug

**„no browser found"** — installiere Chrome, Chromium, Edge oder Brave,
oder setze `browser.executable`. Ohne einen fällt `browse` auf einen
Textbrowser zurück, der dennoch die meisten Fragen zu einer Seite
beantwortet.

**Ich will bei der Arbeit zusehen** — `browser.headless: false`.

**Er braucht eine Anmeldung, die ich schon habe** — starte deinen eigenen
Browser mit einem DevTools-Port und setze `browser.port`, sodass er diese
Sitzung benutzt, statt dir dein Profil hingereicht zu bekommen.

---

## Das Bildschirm-Werkzeug

**Es ist nicht in der Werkzeugliste.** Entweder hat diese Plattform kein
Backend — bisher nur Windows — oder `computer.enabled` ist false. Frage
es:

```
/computer
```

**Klicks landen an der falschen Stelle.** Das sollte nicht geschehen:
DPI-Erkennung wird gesetzt, bevor eine Bildschirmmetrik gelesen wird.
Falls es doch geschieht, berichte es bitte mit deiner
Anzeigeskalierung und -auflösung. Das ist ein echter Fehler.

**Er hat von selbst aufgehört.** Die Maus ging in eine Ecke des
Bildschirms, was die Erteilung mit Absicht beendet. `/computer 15m`
startet eine neue.

**Der Text, der ankam, ist nicht der, den er tippte.** Die Anwendung hat
ihn umgeschrieben — Windows 11s Editor korrigiert beim Tippen. Kein
Comodor-Fehler, und er sagt es bei jedem `type`.
[Mehr](computer.md#typed-is-not-the-same-as-arrived).

---

## Die Web-Oberfläche

**Er weigert sich zu starten.** Kein Anbieter ist konfiguriert, und die
Browser-Oberfläche hat keinen Weg, einen hinzuzufügen. Die Meldung nennt,
was zu setzen ist.

**„Unauthorised".** Bei jedem Lauf wird ein neues Token erzeugt — benutze
die URL von *diesem* Lauf, oder setze `COMODOR_WEB_TOKEN`, um es stabil zu
halten.

**In Docker, nichts unter `localhost:8765`.** Prüfe, dass der Port als
`127.0.0.1:8765:8765` veröffentlicht ist. [Docker](docker.md).

---

## Etwas ist langsam

**Die erste Anfrage einer Sitzung.** Es ist noch nichts zwischengespeichert;
die zweite ist viel schneller.

**Reflexion nach jeder Aufgabe.** Ein Modellaufruf. Benutze
`learning.reflect_model` für ein günstigeres, oder `reflect: false`.

**Screenshots.** Rund 80 ms, um sie aufzunehmen, plus das Modell, das sie
ansieht. Senke `computer.screenshot_tokens`, falls du das Ergebnis noch
lesen kannst.

---

## Von vorne anfangen

```bash
comodor uninstall --dry-run     # what would go, named
comodor uninstall               # do it
```

Oder nur das Gehirn, mit deinen Einstellungen:

```bash
rm ~/.comodor/brain.db
```

---

## Ein Problem melden

Füge ein:

```bash
comodor --version
comodor doctor
```

`doctor` schwärzt deinen Schlüssel. Lies die Ausgabe trotzdem, bevor du sie
einfügst.

- Probleme: <https://github.com/ifekri/Comodor/issues>
- Etwas Sensibles: [SECURITY.md](../SECURITY.md)
