# Rückfragen

Zweideutigkeit hat zwei schlechte Enden. Der Agent wählt eine Lesart, baut das
Falsche, und kostet Sie einen Review-Zyklus. Oder er fragt in Prosa, eine Frage
nach der anderen, und Sie verbringen vier Züge damit, festzunageln, was in
einem Bildschirm festgenagelt sein könnte.

Comodor nimmt einen dritten Weg. Wenn eine Anfrage auf mehr als eine Weise
gelesen werden kann, arbeitet der Agent zuerst *alles* aus, worüber er unsicher
ist, und legt es Ihnen dann als kurzes Multiple-Choice-Formular vor — drei oder
vier Fragen, in etwa fünfzehn Sekunden beantwortet, bevor eine Zeile geschrieben
wird.

Gefragt nach „add rate limiting to the web server", las es zehn Dateien und
stellte dann dies:

```
┏━  3 questions  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                          ┃
┃    ☐  Client identity   ☐  Over-limit   ☐  Scope                         ┃
┃                                                                          ┃
┃  How should clients be identified for rate limiting?                     ┃
┃                                                                          ┃
┃   › ☐ By IP address (recommended)                                        ┃
┃        The server already reads client_address for the loopback check.   ┃
┃     ☐ By token                                                           ┃
┃     ☐ Something else                                                     ┃
┃                                                                          ┃
┃    0 of 3 answered                                                       ┃
┃                                                                          ┃
┗━━━━━━━━━━━━━━  ↑↓ move · ←→ question · space pick · enter next · esc  ━━┛
```

Beachten Sie die zweite Zeile der ersten Option. Es hatte `web/server.py`
gelesen, bevor es fragte, und die Frage dreht sich um die Entscheidung, die
dieses Lesen nicht festnageln konnte.

## Im Terminal

```
left / right      previous and next question
up / down         move within the options
space             pick — and toggle, when several answers may apply
enter             pick, then jump to the next unanswered question;
                  on the last one, send
ctrl+s            send from anywhere
escape            close without answering
```

Der Tab-Streifen trägt eine Markierung je Frage, sodass Sie auf einen Blick
sehen, welche noch ausstehen, ohne jede zu besuchen.

## Im Browser

Dasselbe Formular als Dialog. Klicken Sie auf die Tabs oder benutzen Sie die
Pfeiltasten, klicken Sie auf eine Option, und drücken Sie **Send**. `Escape`
schließt es.

## Die letzte Zeile

Jede Frage endet mit **Something else** und einer Box zum Eintippen. Sie wird
von Comodor hinzugefügt, nicht vom Modell, und das Modell kann sie nicht
entfernen — der ganze Sinn der Zeile ist, dass sie abdeckt, was das Modell
nicht zu bedenken wusste. Eintippen ersetzt die jeweils gewählte Option, und
das Wählen einer Option löscht Eingegebenes, sodass eine Frage nie mit zwei
widersprüchlichen Antworten zurückkommt.

## Überspringen

Ein Formular mit unbeantworteten Fragen abzuschicken ist in Ordnung, und es ist
nicht dasselbe wie es zu verwerfen. Dem Agenten wird exakt gesagt, welche Sie
unberührt ließen, und dass Sie sie deshalb nicht eingeschränkt haben — es
entscheidet also diese selbst und sagt, welchen Weg es genommen hat.

Das Formular ganz zu verwerfen (**Not now**, oder `escape`) sagt dem Agenten,
mit vernünftigen Standards weiterzumachen und **nicht wieder zu fragen**. Ein
zweites Formular an jemanden, der gerade das erste geschlossen hat, ist das
Verhalten, das eine solche Funktion verhasst macht.

## Wenn es nicht fragt

Aus Design, nicht aus Versehen:

- Alles, was es durch Lesen des Projekts herausfinden könnte. Es liest zuerst.
- Erlaubnis fortzufahren. Dafür ist der Genehmigungsdialog da.
- Seinen Plan an Sie zurück zu bestätigen.
- Eine Entscheidung mit einem offensichtlichen Standard. Es nimmt den Standard
  und sagt Ihnen, dass es das tat.

## Grenzen

Höchstens vier Fragen, und je höchstens vier Optionen — plus die
Schreiben-Sie-Selbst-Zeile, die keine der vier verbraucht. Mehr davon hört auf,
ein schnelles Formular zu sein, und wird ein Interview, und ein Agent, der sechs
Antworten braucht, sollte nach den vier fragen, die zählen, und den Rest
ausarbeiten.

Das Formular wartet dreißig Minuten. Danach kommt es unbeantwortet zurück, und
der Agent macht weiter, sodass ein Formular, das auf einer Maschine offen bleibt,
an der niemand ist, einen Lauf nicht unbegrenzt offenhalten kann.

## Für andere Modelle

Das Werkzeug heißt `ask` und ist `SAFE`, was bedeutet, dass es auch im
Plan-Modus verfügbar ist — Planen ist, wenn Zweideutigkeit am härtesten zubeißt.

Wie bereitwillig ein Modell danach greift, variiert. Jedes getestete Modell
fragt, wenn die Anfrage es klar braucht, und bleibt still, wenn nicht, aber
wenn Ihres auf einer Vermutung aufbaut, behebt ein
*„ask me about anything you need to decide first"* in Ihrer eigenen Nachricht
das sofort.
