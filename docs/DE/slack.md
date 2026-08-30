# Von Slack aus

Derselbe Agent, in deinem Workspace: ihm eine Aufgabe schicken, bei der
Arbeit zusehen, seine Fragen beantworten — ohne ein Terminal zu öffnen.

```bash
comodor slack manifest              # the app definition to paste into Slack
comodor slack connect               # the two tokens, checked as you paste them
comodor slack pair                  # add your account
comodor slack start --background    # run it
```

Etwa fünf Minuten, und es gibt **keine öffentliche Adresse zu organisieren**
— was dies von [WhatsApp](whatsapp.md) unterscheidet.

Er führt dieselbe Agentensitzung, die das Terminal, der Browser und der
Telegram-Bot führen. Eine hier begonnene Aufgabe lernt dieselben Lektionen
und landet im selben Verlauf.

## Warum das einfach ist

Slack hat zwei Arten, Ereignisse zuzustellen. Die Events-API sendet an eine
URL, was eine öffentliche HTTPS-Adresse, ein Zertifikat und einen Tunnel
bedeutet — all die Arbeit, die WhatsApp schwer macht.

**Socket Mode** dreht es um: Die App fragt Slack nach einer
WebSocket-Adresse und verbindet sich *nach außen*. Nichts muss aus dem
Internet erreichbar sein, und es gibt keine Adresse, die aktuell zu halten
wäre. Das ist der ganze Trick, und es ist der Grund, warum Slack neben
Telegram steht statt neben WhatsApp.

Das Zweite, das hilft, ist das **App-Manifest**. Slack lässt eine App in
einem YAML-Dokument beschreiben, sodass statt elf Ankreuzfeldern über vier
Einstellungsseiten hinweg die ganze App — Name, Bereiche, Ereignisse, Socket
Mode bereits eingeschaltet — ein Einfügen ist.

## Einrichtung

### 1. Die App erstellen

```bash
comodor slack manifest
```

Das gibt das Manifest und den Link aus. Auf
[api.slack.com/apps](https://api.slack.com/apps?new_app=1), wähle **From a
manifest**, wähle deinen Workspace, füge es ein, erstelle — dann **Install
to Workspace**.

### 2. Die zwei Tokens

Sie sind nicht austauschbar, und sie zu vertauschen ist die häufigste Art,
an der dies scheitert. Comodor weist jedes am jeweils anderen Ort mit Namen
ab, statt Slack eine Stunde später `invalid_auth` beantworten zu lassen.

| | | |
|---|---|---|
| `xoxb-…` | **Bot token** | OAuth & Permissions. Tut alles, was der Bot tut |
| `xapp-…` | **App-level token** | Basic Information → App-Level Tokens, Bereich `connections:write`. Öffnet den Socket, und nichts anderes |

```bash
comodor slack connect
```

Ohne Argumente führt es dich durch beide und prüft jeden, sobald er
ankommt — das Bot-Token gegen `auth.test`, das App-Token, indem es damit
tatsächlich einen Socket öffnet. Ein falscher ist heute ein Satz statt
nächster Woche ein Mysterium.

### 3. Verknüpfe dein Konto

```bash
comodor slack pair
```

Das gibt einen sechsstelligen Code aus. Schicke ihn Comodor als
Direktnachricht, und dein Konto wird hinzugefügt. Der Code funktioniert
einmal und läuft nach fünf Minuten ab.

**In einem Workspace können hunderte Menschen sein**, und dies ist ein
Agent, der deine Dateien liest und schreibt. Er antwortet daher einer
festen Liste von Slack-Benutzer-Ids und ignoriert alle anderen.

```bash
comodor slack status
comodor slack forget U01234567
comodor slack forget all
```

## Wo er antwortet

**In einer Direktnachricht**, immer.

**In einem Kanal, nur wenn erwähnt.** Ein Bot, der auf jede Nachricht in
einem geteilten Kanal antwortet, ist ein Bot, den jemand an diesem
Nachmittag entfernt.

**In dem Thread, in dem er angesprochen wurde.** Eine in einem Thread
gestellte Frage wird in diesem Thread beantwortet, nicht im Kanal vor
allen anderen.

Seine eigenen Nachrichten werden nie beantwortet — ein Bot, der sich
selbst antwortet, ist eine Schleife mit einer Ratenbegrenzung darauf.

## Was er kann und was er nicht kann

**Standardmäßig liest und plant er und ändert nichts.** Eine
Slack-Sitzung bleibt im Plan-Modus, ganz gleich, worauf das Terminal
eingestellt ist, aus demselben Grund wie in den anderen Kanälen: Einen
Shell-Befehl vom Telefon aus freigeben, in einer Warteschlange, ist eine
Entscheidung mit weniger Aufmerksamkeit als dieselbe Freigabe an einer
Tastatur.

```bash
comodor slack writes on
comodor slack writes off
```

Ein Terminal-Befehl mit Absicht. Ein Bot, der seine eigenen Berechtigungen
erweitern könnte, bräuchte nur noch das Slack-Konto von irgendeinem
Menschen.

## Die Knöpfe

Slack ist der geräumigste der drei Kanäle — Nachrichten lassen sich
bearbeiten, und Knöpfe gibt es reichlich —, also ist eine Antwort eine
Nachricht, die wächst, während die Antwort eintrifft, und das ganze Menü
passt auf einen Bildschirm.

| | |
|---|---|
| **New chat** | Das Gespräch bisher vergessen |
| **History** | Ein früheres Gespräch erneut öffnen |
| **Mode** | Handeln, planen oder chatten |
| **Status** | Modell, Ordner, Kontext, Ausgaben |
| **Model** | Zu einem anderen wechseln |
| **Folder** | In welchem Projekt es arbeitet |
| **Skills** | Einen installieren oder entfernen |
| **Rules** | Was es aus deinen Korrekturen gelernt hat |
| **What it may do** | Ob es bearbeiten und ausführen kann |
| **Help** | Was alles tut |

Während eine Aufgabe läuft, ist das Einzige, was angeboten wird, **Stop**.

## Betreiben

```bash
comodor slack start                # here, holding this terminal
comodor slack start --background   # detached; survives closing it
comodor slack stop
comodor slack service install      # starts at login, survives a reboot
comodor slack service show         # read the unit before trusting it
```

Das Protokoll ist `slack.log` neben deiner Konfiguration, angehängt statt
ersetzt.

Ein **User**-Dienst auf jeder Plattform — systemd, launchd, Task Scheduler
— niemals ein System-Dienst. Dies ist ein Agent, der deine Dateien mit
deinen Zugangsdaten liest und schreibt, und mehr Autorität als der Mensch,
dem diese Dateien gehören, kauft nichts.

## Aus dem Browser-Panel

`comodor web` → **Admin** → **From your phone** verbindet, verknüpft,
startet und stoppt all dies ohne ein Terminal. Diese Steuerelemente
beantworten nur Anfragen von der Maschine, auf der Comodor läuft: Ein
Bot-Token übergibt die Fernsteuerung darüber an jeden, der das Token hält.

## Wie er gebaut ist

Keine neue Abhängigkeit. Die Web-API ist `POST /api/chat.postMessage` über
den HTTP-Client, den dieses Projekt bereits hat, und Socket Mode läuft über
den WebSocket-Client, der für die Steuerung von Chrome geschrieben wurde —
weshalb das Hinzufügen von Slack keine Pakete hinzufügte.

Drei Dinge, auf die die Socket-Schleife achtet, von denen jedes eine Art
ist, wie ein Bot still wird, ohne dass jemand es bemerkt:

- **Jeder Umschlag wird bestätigt.** Slack stellt erneut zu, wovon es
  nichts hört, und für einen Agenten, der Befehle ausführt, ist eine
  Nachricht zu drei Zügen werdend nicht bloß laut.
- **`disconnect` ist Routine.** Slack rotiert Verbindungen nach einem
  Zeitplan. Das als Fehler zu behandeln ergibt einen Bot, der alle paar
  Stunden stirbt.
- **Ein stiller Workspace bekommt trotzdem Pings.** Der wichtigste Fall —
  niemand hat ihm eine Stunde lang geschrieben — ist genau der, den ein
  verlorener Socket verdirbt.

## Was er nicht tut

- Jedem antworten, der nicht verknüpft ist.
- Auf alles in einem Kanal antworten, zu dem er hinzugefügt wurde.
- Ein Token oder ein erlaubtes Konto aus der `.comodor/config.json` eines
  Projekts übernehmen. Ein Repository, das seinen Autor auf diese Liste
  bringen könnte, wäre eine Hintertür.
- Irgendetwas bearbeiten, bevor `slack writes on`.
- Eines der beiden Token ausgeben. Beide sind aus jedem aufgeworfenen
  Fehler geschwärzt.
