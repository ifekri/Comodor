# In Docker

Der Agent, sein Browser und alles, was er braucht, in einem Container.

```bash
git clone https://github.com/ifekri/Comodor.git
cd Comodor
export ANTHROPIC_API_KEY=…        # or OPENAI_API_KEY, OPENROUTER_API_KEY, …
docker compose up
```

Er baut das Image beim ersten Mal, gibt dann die Adresse aus:

```
  Comodor is at  http://127.0.0.1:8765/?token=…
  Working in     /work
```

Öffne den Link. Bei jedem Lauf gibt es ein neues Token, also nimm das von
*diesem* Lauf.

Oder ohne irgendetwas zu klonen:

```bash
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e ANTHROPIC_API_KEY \
  -v "$PWD:/work" \
  ghcr.io/ifekri/comodor:latest
```

---

## Ein Schlüssel ist hier nicht optional

Die Browser-Oberfläche hat keine Möglichkeit, einen einzugeben. Ohne
Schlüssel sagt der Container also, was fehlt, und stoppt, statt eine URL zu
servieren, die bei der ersten Aufgabe scheitert.

Compose reicht durch, welches davon auch immer in deiner Shell gesetzt ist,
ohne es in das Image oder die Compose-Datei zu schreiben:

```
ANTHROPIC_API_KEY   OPENAI_API_KEY   OPENROUTER_API_KEY   DEEPSEEK_API_KEY
GOOGLE_API_KEY      GROQ_API_KEY     XAI_API_KEY          MISTRAL_API_KEY
XIAOMI_API_KEY
```

Lieber eine Datei als deine Shell-History? Lege sie in eine `.env` neben die
Compose-Datei — Compose liest diese, und sie ist git-ignoriert.

---

## Wo es arbeitet

Alles, was der Agent berühren kann, ist der Ordner `work/` neben der
Compose-Datei. Verweise ihn auf etwas anderes:

```yaml
volumes:
  - "/path/to/your/project:/work"
```

Was er lernt — das Gehirn, deine Korrekturen, Sitzungs-Transkripte — liegt
in einem benannten Volume, übersteht also `docker compose down` und wird
vergessen von `docker compose down -v`.

---

## Wer ihn erreichen kann

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

**Das `127.0.0.1` auf der linken Seite ist das gesamte
Sicherheitsmodell.** Lass es weg, und der Port liegt auf jeder Schnittstelle
der Maschine — und dieser Port ist eine Shell.

Im Container bindet Comodor an `0.0.0.0`, was kein Versäumnis ist: Ein
Container hat seinen eigenen Netzwerk-Namespace, sodass das Binden an
Loopback innerhalb eines den Port vor der Maschine versteckt, die ihn
betreibt. Wer ihn tatsächlich erreichen darf, entscheidet sich dadurch, wie
der Port veröffentlicht wurde, und das Banner sagt es.

---

## Was der Container darf

```yaml
cap_drop: [ALL]
security_opt:
  - no-new-privileges:true
```

Er führt Shell-Befehle aus; der Container ist also das, was zwischen diesen
und deiner Maschine steht. Er bekommt nichts, was er nicht braucht, und
läuft als Nicht-Root-Benutzer.

---

## Eine Version pinnen

```yaml
args:
  COMODOR_VERSION: ""
```

Standardmäßig gepinnt, damit ein Neubau reproduzierbar ist. Stattdessen die
neueste Veröffentlichung:

```bash
docker compose build --build-arg COMODOR_VERSION=
```

---

## Etwas anderes in ihm ausführen

```bash
docker compose run --rm comodor comodor doctor
docker compose run --rm comodor sh
```

Keine Argumente oder Argumente mit führendem Strich bedeuten „starte die
Web-Oberfläche mit diesen Optionen". Alles andere ist ein Befehl, der
stattdessen ausgeführt wird.

---

## Was nicht im Container ist

**Dein Bildschirm.** Die [Desktop-Steuerung](computer.md) lenkt die
Maschine, auf der Comodor läuft, und das ist in einem Container eine
Maschine ohne Anzeige. Das Werkzeug wird dort nicht angeboten.

Der [Browser](browser.md) funktioniert — Chromium samt Schriftarten ist im
Image.

---

## Wenn er nicht startet

**Nichts unter `localhost:8765`** — prüfe, ob der Port veröffentlicht ist:
`docker compose ps`.

**Er beendet sich sofort** — lies das Protokoll. Fast immer ist kein
Anbieter konfiguriert; die Meldung sagt, was zu setzen ist.

**`exec /usr/local/bin/comodor-start: no such file or directory`** — ein
CRLF-Checkout. Behoben in dem Zweig durch eine `.gitattributes`; wenn du es
siehst, lade neu.

---

## Siehe auch

- [Im Browser](web.md) — die Oberfläche, die du benutzen wirst
- [Sicherheit](safety.md) — was der Agent innerhalb des Containers darf
