# Deinen Bildschirm benutzen

Comodor kann die Maschine so steuern, wie es ein Mensch tut — auf den
Bildschirm schauen, die Maus bewegen, klicken und tippen — in jeder
Anwendung, nicht nur in einem Browser.

Das ist das Mächtigste, was er tun kann, und das Gefährlichste. Lies dir das
[Berechtigungsmodell](#permission) durch, bevor du es einschaltest.

> **Bisher nur unter Windows.** Die macOS- und Linux-Backends sind nicht
> geschrieben. Auf diesen Plattformen wird das Werkzeug überhaupt nicht
> angeboten, statt angeboten zu werden und zu scheitern — siehe
> [Warum es nicht da ist](#why-it-is-not-there).

---

## Wie es aussieht

Du siehst es dabei zu. Bevor sich der Zeiger bewegt, erscheint ein Halo dort,
wo er gleich klicken wird:

```
   ┌─────────────────────────────────────────┐
   │   Comodor · 14m 32s left, anywhere      │   ← the panel, top centre
   │   move the mouse to a corner to stop    │
   └─────────────────────────────────────────┘


               ╭──────────╮
               │   Save   │      ◎  ← the halo, drawn before it moves
               ╰──────────╯
                               clicking (842, 517)
```

Der Zeiger bewegt sich dann in rund einem Drittel einer Sekunde dorthin,
statt zu teleportieren, und eine Welle markiert, wo der Klick gelandet ist.

**Die Pause ist keine Dekoration.** Sie ist der Moment, in dem du es noch
stoppen kannst. Ein Cursor, der springt und im selben Augenblick klickt,
lässt dir nichts übrig.

Läuft der Agent woanders — auf einem Server, in einem Container — erscheint
dasselbe stattdessen in der [Web-Oberfläche](web.md): das Bild, das er sich
angesehen hat, mit einer Markierung, wo er gehandelt hat.

---

## Einschalten

Zwei Schritte, mit Absicht. Keiner von beiden geschieht von selbst.

**1. Dem Werkzeug erlauben, überhaupt zu existieren**, in
`~/.comodor/config.json`:

```json
{
  "computer": {
    "enabled": true
  }
}
```

Solange das nicht gesetzt ist, wird dem Modell das Werkzeug überhaupt nicht
angeboten. Es steht nicht in der Werkzeugliste, es kann also nicht danach
fragen und nicht hineingeredet werden.

**2. Ihm erlauben zu handeln**, in dem Moment, in dem es darauf ankommt:

```
/computer 15m              fifteen minutes, anywhere on screen
/computer 1h this app      one hour, only while the current window is in front
/computer                  how things stand
/computer stop             end it now
```

Oder das Modell lässt fragen. Das erste Mal, wenn es den Bildschirm braucht,
bekommst du das:

```
  Let Comodor use your screen, mouse and keyboard?

  It will be able to see everything on your screen and to click and type
  anywhere, in any application.

  Screenshots go to the model. Whatever is on screen goes with them - open
  messages, tokens, anything visible. Redaction works on text and cannot
  read pixels.

  It will never touch a password manager, a window asking for a password,
  a locked screen, or Comodor's own window.

  To stop it at any moment: move your mouse into a corner of the screen.

  [15 minutes]  [15 minutes, this app only]  [1 hour]  [no]
```

---

## Stoppen

**Bewege die Maus in eine Ecke des Bildschirms.** Das ist die ganze Sache.

Es funktioniert, während der Agent den Zeiger hält — was keine
Tastenkombination versprechen kann, denn der Agent tippt in diesem Moment
möglicherweise in ein Fenster. Es ist auch das, was Menschen tatsächlich
tun, wenn ihr Bildschirm von selbst anfängt sich zu bewegen.

Das Berühren einer Ecke beendet den Lauf und nimmt die Erlaubnis wieder weg.
Erneutes Nachfragen ist eine neue Erteilung.

Der Agent kann selbst weiterhin in eine Ecke klicken — der Start-Knopf, ein
Schließfeld. Er merkt sich, wo er den Zeiger gelassen hat; nur ein Zeiger,
der sich irgendwohin bewegte, wo ihn niemand hingesetzt hat, zählt als du.

Andere Wege, es zu stoppen, wenn deine Hände auf der Tastatur sind:

```
/computer stop       ends the permission
Esc                  stops the current task
```

---

## Berechtigung

Eine Erteilung ist drei Dinge zugleich, und keines davon ist ein
Ankreuzfeld.

| | |
|---|---|
| **Ein Geltungsbereich** | überall, oder eine Anwendung anhand ihres Fenstertitels |
| **Eine Uhr** | sie läuft ab, und die verbleibende Zeit steht die ganze Zeit auf dem Bildschirm |
| **Ein Ausweg** | die Ecke, die funktioniert, während der Zeiger gelenkt wird |

Geprüft wird **vor jeder einzelnen Aktion**, nicht einmal am Anfang. Ein
Fenster, das mitten in einem erlaubten Lauf auftaucht, wird erwischt.

### Verweigert, egal was du erlaubt hast

- Ein Passwort-Manager — 1Password, Bitwarden, KeePass, LastPass, Dashlane,
  NordPass und die System-Zugangsdatenspeicher.
- Jedes Fenster, dessen Titel ein Passwort, eine Passphrase, 2FA oder einen
  Einmalcode erwähnt.
- Eine Wallet- oder Hardware-Wallet-Anwendung — MetaMask, Ledger Live,
  Trezor.
- Alles, was wie Online-Banking aussieht.
- Ein gesperrter Bildschirm.
- **Comodors eigenes Fenster.** Ein Agent, der in das Terminal klickt, das
  ihn antreibt, tippt in seine eigene Eingabe.

Eigene hinzufügen:

```json
{
  "computer": {
    "never": ["Internal HR", "Payroll"]
  }
}
```

Abgeglichen wird an beliebiger Stelle im Fenstertitel,
Groß-/Kleinschreibung wird nicht beachtet.

### Was eine Erteilung nicht ist

Sie wird **niemals in deine Konfigurationsdatei geschrieben**. Comodor
schließen beendet sie. Es gibt kein „immer erlauben" für den Bildschirm,
und dieses Fehlen ist Absicht.

Ein Repository kann das nicht einschalten. `computer` steht nicht in der
Liste der Dinge, die die `.comodor/config.json` eines Projekts setzen darf,
und ein Repository, das es versucht, wird lautstark abgewiesen. Siehe
[Sicherheit](safety.md#what-a-repository-may-set).

---

## Was zum Modell geht

**Screenshots, und alles, was darin sichtbar ist.** Das ist einen Moment des
Innehaltens wert.

Wenn hinter deinem Editor ein Passwort-Manager offen ist, wenn in einem
Chat-Fenster eine Nachricht steht, wenn in einem Terminal ein API-Schlüssel
steht — das ist alles auf dem Bild, und das Bild geht an den Anbieter, den
du konfiguriert hast.

Comodors Schwärzung arbeitet auf Text und kann keine Pixel lesen. An dieser
Stelle führt kein Weg vorbei: Das Feature heißt „lass das Modell deinen
Bildschirm sehen".

Praktische Ratschläge:

- Schließe, was du nicht in ein Chat-Fenster einfügen würdest.
- Benutze `/computer 1h this app`, damit es nur handelt, solange ein
  Fenster vorn ist — es *sieht* trotzdem alles, was auf dem Screenshot ist.
- Bevorzuge das [Browser-Werkzeug](browser.md), wenn die Arbeit eine
  Webseite ist. Es gibt Text statt Pixel zurück und kostet einen Bruchteil.

---

## Was es kann

Siebzehn Aktionen, hinter einem Werkzeug. Die Namen sind Anthropics, denn
Modelle werden auf diesem Vokabular trainiert.

### Ansehen

| Aktion | Was sie tut |
|---|---|
| `screenshot` | Der aktive Monitor. `whole_desktop: true` für jeden Monitor. |
| `zoom` | Ein Bereich in voller Auflösung — so liest es kleinen Text |
| `cursor_position` | Wo der Zeiger steht |

### Zeigen

| Aktion | |
|---|---|
| `mouse_move` | Irgendwohin fahren, ohne zu klicken |
| `left_click` `right_click` `middle_click` | Mit optionalen Zusatztasten |
| `double_click` `triple_click` | Dreifach markiert eine Zeile in den meisten Editoren |
| `left_click_drag` | Von einem Punkt zu einem anderen |
| `left_mouse_down` `left_mouse_up` | Für alles, was ein Ziehen nicht ausdrücken kann |
| `scroll` | Auf, ab, links, rechts, in Radklicks |

### Tippen

| Aktion | |
|---|---|
| `type` | Text, Zeichen für Zeichen — korrekt auf jedem Tastaturlayout |
| `key` | `Return`, `ctrl+s`, `alt+Tab`, `F5`, `Page_Down`, … |
| `hold_key` | Eine Taste oder Kombination für eine Dauer halten |
| `wait` | Etwas auf dem Bildschirm auslaufen lassen |

Text wird **zeichenweise getippt, nicht über die Position der Taste**. Die
Taste zu drücken, auf der `@` auf einer US-Tastatur liegt, ergibt auf einer
französischen etwas anderes; das Zeichen zu benennen ergibt `@` überall,
auch auf Layouts ohne Taste dafür.

---

## Getippt ist nicht dasselbe wie angekommen

Anwendungen schreiben um, was in sie getippt wird.

Windows 11s Editor hat Autokorrektur standardmäßig an. `ümlaut` hinein zu
tippen ergibt `umlaut`. Unterwegs ging nichts verloren — jeder von dreißig
getesteten Akzent- und Nicht-Latein-Zeichen kommt einzeln gesendet intakt
an, und `üxqzv` an derselben Stelle bleibt unangetastet. Die Anwendung hat
es geändert.

Comodor sagt es bei jedem `type`:

```
Typed 29 characters. Applications can autocorrect or reformat what is
typed into them - take a screenshot if what arrived matters.
```

Wenn der genaue Text zählt — ein Passwortfeld, ein Konfigurationswert, eine
Commit-Nachricht —, lass es noch einmal nachsehen.

---

## Screenshots und was sie kosten

Ein Screenshot ist das Teuerste, was dieses Werkzeug sendet.

Die Größe richtet sich danach, was das Modell akzeptiert: eine lange Kante
von 2.576 Pixeln und ein Token-Budget. Das Standard-Budget sind 1.600
visuelle Token, was auf jedem ausprobierten Bildschirm ein lesbares Bild
ergibt.

| Dein Bildschirm | Beim Standard-Budget | Kosten |
|---|---|---|
| 1920 × 1080 | 1480 × 833 | ~1.590 Token |
| 3840 × 1080 | 2068 × 582 | ~1.554 Token |
| 3840 × 2160 | 1064 × 599 | ~836 Token |

**Setze das nicht zu niedrig an.** Der übliche Rat „mit 1280 Breite
aufnehmen" geht von einem 16:9-Bildschirm aus. Auf einem 3840 × 1080
Display bedeutet das eine dreifache Verkleinerung, und in dieser Größe
bekommt das Modell Text, den es nicht lesen kann — es rät also, statt zu
fragen. Gemessen auf diesem Bildschirm: Menübeschriftungen bei 1280 Breite
unlesbar, bei 2068 einwandfrei klar.

```json
{
  "computer": {
    "screenshot_tokens": 1600
  }
}
```

700 ist günstig und auf einem Laptop noch lesbar. 4784 ist das Maximum, das
das Modell annimmt.

**Alte Screenshots werden automatisch verworfen.** Nur die letzten zwei
bleiben im Gespräch; der Rest wird zu einer Zeile, die sagt, dass einer da
war. Ohne das würde eine Aufgabe mit dreißig Schritten nahezu fünfzigtausend
Token an Pixeln mit sich tragen, fast alle davon beschreibend einen
Bildschirm, auf den seither geklickt wurde. Ändere es mit
`agent.keep_screenshots`, falls du einen Grund hast.

---

## Alle Einstellungen

```json
{
  "computer": {
    "enabled": false,
    "screenshot_tokens": 1600,
    "grant_seconds": 900,
    "travel_seconds": 0.32,
    "overlay": true,
    "never": []
  }
}
```

| Einstellung | Standard | |
|---|---|---|
| `enabled` | `false` | Ob dem Modell das Werkzeug überhaupt angeboten wird |
| `screenshot_tokens` | `1600` | Lesbarkeit gegen Preis. Max. 4784 |
| `grant_seconds` | `900` | Wie lange eine einfache Erteilung gilt |
| `travel_seconds` | `0.32` | Wie lange der Zeiger zum Fahren braucht. `0` würde funktionieren und wäre nicht mit anzusehen |
| `overlay` | `true` | Halo und Panel zeichnen. Aus für eine Maschine, an der niemand sitzt |
| `never` | `[]` | Zusätzliche Fenstertitel, die nie berührt werden |

---

## Warum es nicht da ist

Wenn `computer` nicht unter den Werkzeugen ist, trifft eines davon zu:

**Die Plattform hat kein Backend.** Bisher nur Windows. Das Werkzeug wird
nicht angeboten, statt angeboten zu werden und jedes Mal zu scheitern — ein
Werkzeug, das das Modell sehen, aber nie benutzen kann, lädt bei jedem Zug
zu einem verschwendeten Aufruf ein.

**Es ist abgeschaltet.** `computer.enabled` ist standardmäßig `false`.

Frage es direkt:

```
/computer
```

```
no screen control: it is switched off. Set computer.enabled in your config.
```

---

## Unter der Haube

Für Neugierige, und für alle, die es auf eine andere Plattform portieren.

**Keine Abhängigkeiten.** Die Bildschirmaufnahme ist GDI über `ctypes`; die
Verkleinerung ist `StretchBlt` im `HALFTONE`-Modus, der mittelt statt
Pixel zu verwerfen — der Unterschied zwischen lesbarem kleinem Text und
Griesel. Die PNG-Kodierung ist `zlib` und `struct`, etwa vierzig Zeilen. Die
Eingabe ist `SendInput`.

**DPI-Erkennung wird gesetzt, bevor irgendetwas eine Bildschirmmetrik
liest.** Auf einem auf 125 % skalierten Display — dem Standard auf den
meisten Windows-Laptops — wird einem Prozess, der sich nicht als
DPI-fähig erklärt hat, gesagt, der Bildschirm sei kleiner als er ist, und
jeder Klick landet genau um den Skalierungsfaktor zu kurz. Die Ursache ist
unsichtbar; es sieht so aus, als könne das Modell nicht zielen.

**Koordinaten werden an genau einer Stelle umgerechnet.** Das Modell
antwortet in den Pixeln des Bildes, das ihm gezeigt wurde — einem
verkleinerten Ausschnitt eines Bildschirms mit einem Ursprung, von dem ihm
nie erzählt wurde. `Shot.to_screen` ist der einzige Code, der das weiß,
denn eine zweite Kopie ist eine zweite Chance, es falsch zu machen.

**Das Overlay ist ein durchklickbares, nie fokussiertes Fenster.**
`WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`, sodass der Zeiger
das darunter Liegende erreicht und die Tastatur bleibt, wo sie war. Es
läuft in seinem eigenen Thread mit eigener Ereignisschleife, und ein
fehlgeschlagenes Zeichnen ist ein fehlendes Bild, kein fehlendes Feature —
der Agent arbeitet auch ganz ohne Anzeige.

Portieren auf macOS oder Linux heißt, eine Datei neben `win32.py` mit
denselben gut zwölf Funktionen zu schreiben. Nichts oberhalb dieser Ebene
importiert `ctypes`.

---

## Siehe auch

- [Sicherheit und Berechtigungen](safety.md) — der Rest des
  Berechtigungsmodells
- [Der echte Browser](browser.md) — günstiger, wenn die Arbeit eine
  Webseite ist
- [Im Browser](web.md) — bei der Arbeit aus der Ferne zusehen
- [Kosten](cost.md) — was eine lange Desktop-Sitzung tatsächlich kostet
