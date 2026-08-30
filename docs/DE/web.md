# Im Browser

Derselbe Agent, in einem Browser-Tab. Auf dieser Maschine oder auf einem
Server, den du über SSH erreichst.

```bash
comodor web
```

```
   ______                          __
  / ____/___  ____ ___  ____  ____/ /___  _____
 / /   / __ \/ __ `__ \/ __ \/ __  / __ \/ ___/
/ /___/ /_/ / / / / / / /_/ / /_/ / /_/ / /
\____/\____/_/ /_/ /_/\____/\__,_/\____/_/

  it learns the way you correct it   0.9.0  ·  claude-sonnet-5

  Comodor is at  http://127.0.0.1:8765/?token=EYhO9St_VTy95k4gHtJytb
  Working in     /home/you/projects/api-server

  Only this machine can reach it. Ctrl-C to stop.
```

Öffne den Link. Das Token steckt darin.

---

## Optionen

```bash
comodor web --port 9000
comodor web --no-browser            # do not open one for me
comodor web --token mytoken         # a fixed token
comodor web --host 0.0.0.0          # reachable from elsewhere — read below
```

---

## Das Token

Bei jedem Lauf ein neues, sodass eine URL von gestern heute kein Weg
hinein ist. Es kommt in der URL an, wird gegen ein Cookie eingetauscht, und
jede Anfrage danach wird durch das Cookie autorisiert.

Um es über Neustarts hinweg stabil zu halten:

```bash
export COMODOR_WEB_TOKEN=something-long-and-random
```

Jeder mit dem Token hat eine Shell auf dieser Maschine. Behandle es wie
eine.

---

## An mehr als Loopback binden

`--host 0.0.0.0` stellt die Oberfläche auf jede Schnittstelle der Maschine.
**Dieser Port ist eine Shell.** Comodor sagt es, statt anzunehmen, dass du
es so gemeint hast:

```
  Listening on every address on this machine.
  Anyone who can reach this port can run commands as you.
```

Besser, wenn der Agent auf einem Server steht: auf Loopback lassen und
tunneln.

```bash
ssh -N -L 8765:127.0.0.1:8765 you@server
```

Dann öffne `http://127.0.0.1:8765` lokal. Der Port wird nie freigegeben,
und SSH macht die Authentifizierung.

---

## Zusehen, wie er einen Bildschirm benutzt

Wenn der Agent einen Desktop steuert, erscheint das Bild, das er sich
angesehen hat, in der Oberfläche mit einer Markierung, wo er gehandelt hat:

```
┌────────────────────────────────────────────┐
│                                            │
│   [ the screen the model saw ]      ✛      │
│                                            │
│   clicking Save                            │
└────────────────────────────────────────────┘
```

Das ist der Sinn der Sache. Das Overlay auf dem Bildschirm zeichnet auf der
gelenkten Maschine, was nichts nützt, wenn diese Maschine ein Server oder
ein Container ist — das Panel ist der Weg, aus der Ferne zuzusehen.

Das Bild wird einmal pro Bild aus `/api/screen` geholt, nicht im
Ereignisstrom mitgeführt: Ein Screenshot ist rund ein Megabyte groß, und
ein Browser, der das Ereignisprotokoll erneut liest, würde jedes Bild
herunterladen, das er je gesehen hat.

[Deinen Bildschirm benutzen](computer.md).

---

## Was er nicht tut

**Ohne Anbieter starten.** Er kann zwischen bereits eingerichteten
Anbietern wechseln, aber es gibt keine Stelle, an der man einen Schlüssel
eingeben könnte, und ein Browser-Tab wäre ein schlechter Ort dafür. Statt
eine URL zu servieren, die bei der ersten Aufgabe scheitert, sagt er, was
fehlt, und stoppt:

```
Comodor has no provider configured, and the browser interface has no way to
add one.

  In Docker, pass a key in as an environment variable:
    -e ANTHROPIC_API_KEY=...    -e OPENAI_API_KEY=...
  or mount a config file at ~/.comodor/config.json.
  Anywhere with a terminal, `comodor setup` asks a few questions.
```

An einem Terminal stellt es stattdessen die Einrichtungsfragen. In einem
Container gibt es immer die Meldung aus — ein Container hat ein Terminal,
ganz gleich, ob jemand angehängt ist, und ein abgelöster würde sonst auf
eine Frage warten, die niemand beantworten kann.

**Weiten, was der Agent berühren darf.** Die automatische Freigabe für
Schreibvorgänge und Befehle wird in Admin angezeigt und lässt sich dort
nicht ändern. Die Berechtigungsdialoge bieten diese Wahl bereits pro Aktion
an, vor dem Menschen, der damit leben wird; eine Seite, die jeder mit dem
Link erreichen kann, ist der falsche Ort, um daraus eine dauerhafte
Richtlinie zu machen. Ändere es dort, wo Comodor gestartet wurde — siehe
[Sicherheit](safety.md).

---

## Was auf dem Bildschirm ist

**Das Gespräch**, im Streaming, wie es eintrifft, mit eingerahmtem Code als
Code und jedem Tool-Aufruf als Zeile, die du aufklappen kannst, um zu
sehen, was er tatsächlich tat.

**Die Chat-Liste**, links. Jedes Gespräch wird nach
`~/.comodor/sessions` geschrieben — derselbe Ordner, den das Terminal
benutzt, sodass ein am Prompt begonnener Chat im Browser geöffnet werden
kann und umgekehrt. Die Suche sieht in ihnen hinein, nicht nur auf ihre
Titel.

**Admin**, der zweite Tab, die Antwort auf die Frage „was hat das Ding
gerade mit meiner Maschine vor":

| | |
|---|---|
| Modell | welcher Anbieter und welches Modell antwortet, und das Wechseln zwischen denen, für die du Schlüssel hast |
| Wie es läuft | der Modus, ob es von selbst weitermacht, und die vier Deckel — Kontext, Schritte, Zeit, Ausgaben |
| Berechtigungen | was es ohne Nachfragen darf, worüber es fragen wird und was in dieser Sitzung gewährt wurde |
| Was es gelernt hat | Regeln, Lektionen, Skills, Aufgaben, und wie viele davon erfolgreich waren |
| Werkzeuge | jedes Werkzeug, das es erreichen kann, nach Risiko farbcodiert, dazu deine Skills und etwaige MCP-Server |
| Diese Maschine | Version, Python, und wo die Einstellungen, Chats und das Gehirn liegen |

**Der Statusstreifen** am unteren Rand: ob die Seite verbunden ist, der
Arbeitsordner, wie voll der Kontext ist, was die Sitzung gekostet hat und
wie viele gelernte Regeln in Kraft sind.

**Das Bildschirm-Panel**, wenn der Agent einen steuert — das Bild, das er
zuletzt angesehen hat, mit einer Markierung, wo er gleich klicken wird.
Siehe [Deinen Bildschirm benutzen](computer.md).

---

## Tastatur

| | |
|---|---|
| `Enter` | senden |
| `Shift`+`Enter` | neue Zeile |
| `Esc` | die laufende Aufgabe stoppen oder die Seitenleiste schließen |
| `Ctrl`/`⌘`+`K` | die Chats durchsuchen |
| `Ctrl`/`⌘`+`B` | die Seitenleiste zeigen oder verbergen |
| `/` | zum Nachrichtenfeld springen |

---

## Auf einem Telefon

Dieselbe Seite. Unter 900 Pixeln wird die Chat-Liste zu einer Schublade über
dem Gespräch statt zu einer Spalte daneben, denn 292 Pixel Seitenleiste auf
einem 390-Pixel-Bildschirm lassen nichts breit genug, um Code darin zu
lesen. Tippe außerhalb, drücke `Esc` oder benutze den Schließen-Knopf, um
sie wegzuräumen.

Erreiche sie von deinem Telefon aus so, wie du alles andere auf deiner
Maschine erreichst — ein SSH-Tunnel, kein öffentliches Binden. [An mehr als
Loopback binden](#binding-to-more-than-loopback) erklärt, warum.

---

## In jeder Sprache schreiben

Tippe auf Persisch, Arabisch oder Hebräisch, und das Nachrichtenfeld dreht
sich beim Tippen um; Antworten in diesen Sprachen werden beim Eintreffen
von rechts nach links gesetzt. Nichts ist konfiguriert und es gibt keine
Spracheinstellung: Jede Nachricht wird für sich beurteilt, sodass ein
Gespräch, das zwischen Sprachen wechselt, mitwechselt.

Die Beurteilung geschieht durch Zählen statt durch den ersten Buchstaben,
und genau deshalb stimmen die beiden unbequemen Fälle — ein
persischer Satz, der mit einem Paketnamen beginnt, bleibt persisch, und ein
englischer Satz, der ein persisches Wort zitiert, bleibt englisch. Code,
Pfade und URLs werden innerhalb eines rechts-nach-links-Absatzes
links-nach-rechts gesetzt, wo sie hingehören.

Arabischschriftlicher Text wird in Vazirmatn gesetzt, der im Paket
mitreist, statt von einem Font-Host geholt zu werden: Das muss auf einer
Maschine funktionieren, die das Internet nicht erreicht. Er gilt für
arabischschriftliche Zeichen und für nichts anderes, sodass eine Zeile, die
Persisch mit einem englischen Bezeichner mischt, für jedes das richtige
Schriftbild bekommt.

---

## Hell und dunkel

Folgt dem System standardmäßig; die Sonne oben rechts schaltet um, und die
Wahl wird in diesem Browser gemerkt.

---

## In Docker

```bash
docker compose up
```

und öffne die Adresse, die es ausgibt. [Docker](docker.md).

---

## Siehe auch

- [Docker](docker.md) — dasselbe in einem Container
- [Die Oberfläche](interface.md) — die Terminal-Version
- [Sicherheit](safety.md) — die Berechtigungen, über die der Admin-Tab berichtet
- [Deinen Bildschirm benutzen](computer.md) — was das Bild-Panel dir zeigt
