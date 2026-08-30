# Der echte Browser

Kein Seitenlader. Ein Browser, der tatsächlich installiert ist — er führt
JavaScript aus, behält Cookies und kann sich anmelden.

---

## Was er verwendet

Chrome, Chromium, Edge oder Brave, je nachdem, was auf der Maschine
vorhanden ist. **Es wird nichts heruntergeladen.** Er startet einen in einem
eigenen Profil, das nirgendwo angemeldet ist, und schließt ihn, wenn die
Sitzung endet.

Ist keiner installiert, fällt `browse` auf einen Textbrowser zurück, der
dennoch die meisten Fragen zu einer Seite beantwortet. Beide heißen
`browse`, weil die Wahl zwischen zwei Dingen namens „browser" ein Zug wäre,
den das Modell nicht verbrauchen sollte.

---

## Was zurückkommt

Kein Screenshot. Der Titel, der lesbare Text und eine **nummerierte Liste
der Steuerelemente, die tatsächlich auf dem Bildschirm stehen**:

```
  Sign in — Example
  ─────────────────────────────────────────────
  Sign in to your account. New here? Create one.

  [1]  textbox   Email
  [2]  textbox   Password
  [3]  button    Sign in
  [4]  link      Forgot your password?
```

Das Modell bedient ein Element über seine Nummer. Diese Liste ist darauf
gefiltert, was sichtbar, benannt, auf dem Bildschirm und kein Duplikat ist —
was erheblich kleiner ist als der Accessibility-Baum und, gemessen, kleiner
als ein Screenshot derselben Seite.

Ein Screenshot nur, wenn die Frage eine visuelle ist — Layout, Gestaltung,
ein Diagramm —, denn ein Bild kostet jedes Mal dasselbe und lässt sich
nicht kürzen.

---

## Verben

| | |
|---|---|
| `open` | zu einer URL gehen |
| `click` | ein Steuerelement, über seine Nummer |
| `type` | in ein Feld, über seine Nummer |
| `scroll` | nach oben oder unten |
| `back` | die vorherige Seite |
| `read` | die Seite erneut, nachdem sich etwas geändert hat |
| `look` | ein Screenshot, wenn die Frage darzustellen geht, wie etwas aussieht |
| `script` | JavaScript ausführen und seinen Wert zurückbekommen |

---

## Bei der Arbeit zusehen

```json
{ "browser": { "headless": false } }
```

Ein sichtbares Fenster, damit du sehen kannst, was es tut.

> Diese Einstellung wurde früher ignoriert — `browser` war nicht als
> Konfigurationsabschnitt registriert, sodass jede `browser`-Einstellung
> stillschweigend nichts bewirkte. Behoben in 0.9.0.

---

## Eine Sitzung verwenden, in der du schon angemeldet bist

Statt dein Profil herzugeben, starte deinen eigenen Browser mit einem
DevTools-Port und verweise Comodor darauf:

```bash
chrome --remote-debugging-port=9222
```

```json
{ "browser": { "port": 9222 } }
```

Er hängt sich an diesen Browser an und verwendet die dort bereits
vorhandenen Tabs und Cookies. Schließe den Port, wenn du fertig bist —
alles auf deiner Maschine kann ihn benutzen.

---

## Alle Einstellungen

```json
{
  "browser": {
    "executable": "",
    "headless": true,
    "width": 1280,
    "height": 800,
    "port": 0
  }
}
```

| | |
|---|---|
| `executable` | ein bestimmter Browser. Leer bedeutet: an den üblichen Orten nachsehen |
| `headless` | unsichtbar standardmäßig, damit er nicht den Fokus stiehlt |
| `width`, `height` | das Fenster |
| `port` | sich an einen selbst gestarteten Browser anhängen, statt einen zu starten |

Ein Repository kann keine dieser Einstellungen vornehmen —
`browser.executable` benennt ein zu startendes Programm.
[Sicherheit](safety.md#what-a-repository-may-set).

---

## `browse` oder `web_fetch`?

| | |
|---|---|
| `web_fetch` | die Seite ist ein Dokument. Sie wird auf Text reduziert. Günstig |
| `browse` | die Seite ist eine Anwendung. Braucht JavaScript, eine Anmeldung oder einen Klick |

Dem Modell wird gesagt, es solle `web_fetch` bevorzugen und zu `browse`
greifen, wenn jenes nicht ausreicht.

---

## In einem Container

Das Docker-Image bringt Chromium und die Schriftarten mit, um es zu
rendern. Chromiums eigene Sandbox kann nicht in einem Container starten,
dessen seccomp-Profil User-Namespaces blockiert; Comodor erkennt das und
versucht es erneut ohne die innere Sandbox — und bewahrt damit die
Begrenzung des Containers, die die eigentliche Grenze ist. [Docker](docker.md).

---

## Unter der Haube

Das Chrome DevTools Protocol über eine handgeschriebene WebSocket. Keine
Abhängigkeit: Die RFC-6455-Rahmenbildung umfasst rund hundert Zeilen und ist
Teil des Pakets, auf dieselbe Weise wie der HTTP-Client und der SSE-Leser.

---

## Siehe auch

- [Was der Agent kann](tools.md) — die anderen Werkzeuge
- [Deinen Bildschirm benutzen](computer.md) — wenn die Arbeit keine Webseite ist
- [Kosten](cost.md) — warum er Text statt Bilder zurückgibt
