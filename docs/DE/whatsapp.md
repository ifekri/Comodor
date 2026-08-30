# Von WhatsApp aus

Derselbe Agent, erreicht über eine WhatsApp-Geschäftnummer: ihm eine Aufgabe
schicken, bei der Arbeit zusehen, seine Fragen beantworten — ohne ein
Terminal zu öffnen.

> **Lies das zuerst.** [Telegram](telegram.md) tut dasselbe und braucht
> etwa eine Minute: @BotFather anschreiben, ein Token einfügen. WhatsApp
> braucht etwa zwanzig, ist technisch, und das meiste davon spielt sich in
> Metas Dashboard ab — du brauchst eine Meta-App, ein App-Geheimnis und
> eine öffentliche HTTPS-Adresse. **Wenn es nicht WhatsApp sein muss,
> nimm Telegram.**
>
> [Slack](slack.md) ist der mittlere Weg: etwa fünf Minuten, und auch keine
> öffentliche Adresse.
>
> Daran führt kein Weg vorbei. WhatsApp hat kein Äquivalent zu einem
> Bot-Token, und Meta liefert Nachrichten an eine URL, statt irgendetwas
> nach ihnen abfragen zu lassen. Die einzige echte
> Ein-Klick-Version würde jede Nachricht über den Server von jemand
> anderem leiten, was kein Kompromiss ist, den dieses Werkzeug eingeht.

```bash
comodor whatsapp connect              # walks you through all of it
comodor whatsapp pair                 # add your number
comodor whatsapp start --background   # run it
```

`connect` ohne Argumente ist eine geführte Einrichtung: Sie verlinkt jede
Seite, nimmt einen Wert nach dem anderen und prüft jeden, sobald er
ankommt — das Token gegen Meta, die id darauf, eine id zu sein, das
Geheimnis darauf, ein Geheimnis zu sein. Sie startet den Tunnel für dich
und wartet darauf, dass Metas Verifizierungs-Callback tatsächlich eintrifft,
statt anzunehmen, dass es das tat.

Er führt dieselbe Agentensitzung, die das Terminal, der Browser und der
Telegram-Bot führen. Eine hier begonnene Aufgabe lernt dieselben Lektionen
und erscheint im selben Verlauf.

## Warum das mehr Einrichtung braucht als Telegram

Telegram gibt dir ein Token und lässt dich Nachrichten abfragen. WhatsApp
ist Metas **Cloud API**, und zwei ihrer Entwurfsentscheidungen prägen hier
alles.

**Nachrichten werden zugestellt, nicht geholt.** Es gibt keinen langen
Poll. Meta schickt jede eingehende Nachricht an eine URL, was bedeutet,
dass etwas von dir über das Internet per HTTPS erreichbar sein muss. Das
ist die Mehrarbeit, und daran führt kein Weg vorbei.

**Meta will eine App.** Ein Geschäftskonto, eine Nummer, ein
Zugriffstoken und ein App-Geheimnis — vier Dinge, die in einem Browser
leben, weshalb der Einrichtungsassistent auf diese Seite zeigt, statt zu
versuchen, sie einzusammeln.

Die Alternative, nach der die meisten Projekte greifen, ist eine Bibliothek,
die WhatsApp Web über einen kopflosen Browser antreibt. Die brauchen Node,
sie brechen, wann immer WhatsApp seinen Web-Client ändert, und sie sind
gegen die Bedingungen, an die das Konto gehalten ist: Der Fehlermodus ist
die gesperrte Nummer. Nicht etwas, das ein Programmierwerkzeug seinen
Anwendern in die Hand geben darf.

## Wie lange das dauert

Etwa zwanzig Minuten beim ersten Mal, gegen eine Minute für Telegram, und
das meiste davon spielt sich in Metas Dashboard ab statt hier.

Was du **nicht** brauchst: eine echte Telefonnummer, eine
Zahlungsmethode oder eine Geschäftsverifizierung. Das Hinzufügen des
WhatsApp-Produkts erzeugt eine **Testnummer**, die bis zu fünf Empfänger
kostenlos anschreibt, was vier mehr ist, als ein Mensch braucht, der mit
seinem eigenen Agenten spricht.

## Einrichtung

Die Kurzversion ist `comodor whatsapp connect`, was das Ganze durchgeht.
Was folgt, ist das, was es durchgeht, für jeden, der es lieber vorher
sieht.

### 1. Eine Meta-App mit WhatsApp

Erstelle auf [developers.facebook.com](https://developers.facebook.com)
eine App und füge das Produkt **WhatsApp** hinzu. Meta gibt dir eine
Testnummer zum Anfangen; eine echte wird später unter dem Geschäftskonto
hinzugefügt.

Du brauchst von dort vier Dinge:

| | |
|---|---|
| **Phone number id** | Die numerische id neben der Nummer — *nicht* die Nummer |
| **Access token** | Das eigene des Dashboards hält 24 Stunden. Ein **System User**-Token unter Business Settings läuft nicht ab, und ist das zu benutzende |
| **App secret** | Settings → Basic. Jeder Webhook ist damit signiert |
| **Eine öffentliche HTTPS-Adresse** | Wohin Meta zustellt. Siehe unten |

```bash
comodor whatsapp connect \
    --number-id 123456789012345 \
    --token EAAG… \
    --app-secret 0a1b2c…
```

Das prüft das Token gegen Meta, bevor irgendetwas gespeichert wird, sodass
ein Tippfehler heute eine Meldung ist statt nächster Woche ein Mysterium.

### 2. Einen Ort, an den Meta zustellen kann

Der Bot lauscht auf `127.0.0.1:8770`. Meta stellt nur an **HTTPS** zu und
akzeptiert kein selbstsigniertes Zertifikat, also muss etwas ein echtes
vor ihn stellen. Ein Tunnel ist die übliche Antwort: kein offener Port,
kein DNS, keine Domain.

**`comodor whatsapp connect` macht das für dich**, wenn `cloudflared`
installiert ist — er startet den Tunnel, liest die Adresse daraus und
zeigt dir, was einzufügen ist. Einen selbst zu fahren:

```bash
cloudflared tunnel --url http://127.0.0.1:8770
comodor whatsapp connect --url https://something.trycloudflare.com/whatsapp
comodor whatsapp webhook
```

**Ein Schnelltunnel bekommt bei jedem Start eine neue Adresse.** Das ist
beim Einrichten in Ordnung und falsch für einen Bot, der weiterlaufen
soll: Meta fährt fort, an die Adresse zuzustellen, die du ihm gegeben
hast, sodass nach einem Neustart nichts ankommt und nichts sagt, warum.
`comodor whatsapp start --tunnel` warnt, wenn die Adresse sich verschoben
hat.

Für eine Adresse, die bleibt, lege einmal einen benannten Tunnel an — er
braucht ein kostenloses Cloudflare-Konto:

```bash
cloudflared tunnel login
cloudflared tunnel create comodor
cloudflared tunnel route dns comodor comodor-hooks.example.com
```

Alles andere, das TLS terminiert und an `127.0.0.1:8770` weiterleitet,
funktioniert auf dieselbe Weise.

```
  Callback URL   https://something.trycloudflare.com/whatsapp
  Verify token   Kq3nP…
```

Füge beides in **WhatsApp → Configuration** im Dashboard ein, und abonniere
dann die App auf das Feld **messages**. Meta ruft die URL sofort einmal
auf, um sie zu prüfen; der Bot beantwortet diesen Handshake selbst.

Ein Reverse-Proxy, den du ohnehin fährst, funktioniert auf dieselbe Weise —
alles, was TLS terminiert und an `127.0.0.1:8770` weiterleitet.

### 3. Verknüpfe deine Nummer

```bash
comodor whatsapp pair
```

Das gibt einen sechsstelligen Code aus. Schicke ihn der
Geschäftsnummer aus WhatsApp, und deine Nummer wird hinzugefügt. Der Code
funktioniert einmal und läuft nach fünf Minuten ab.

**Eine Geschäftnummer ist eine Telefonnummer**, und Fremde schreiben
Telefonnummern selbstverständlich an. Er antwortet daher einer festen
Liste, und alle anderen bekommen **Stille** — keine Ablehnung. Eine
Nummer, die „du bist nicht erlaubt" sagt, hat einem Fremden mitgeteilt,
dass es sich lohnt, es erneut zu versuchen.

```bash
comodor whatsapp status         # who may talk to it
comodor whatsapp forget 15551234567
comodor whatsapp forget all
```

Die Liste wird als Ziffern verglichen, sodass `+1 555…`, `001 555…` und
`1555…` ein Mensch sind statt drei.

## Was er kann und was er nicht kann

**Standardmäßig liest und plant er und ändert nichts.** Eine
WhatsApp-Sitzung bleibt im Plan-Modus, ganz gleich, worauf das Terminal
eingestellt ist, aus demselben Grund wie bei Telegram: Einen Shell-Befehl
mit dem Daumen freigeben, in einer Warteschlange, ist eine Entscheidung
mit weniger Aufmerksamkeit als dieselbe Freigabe an einer Tastatur.

```bash
comodor whatsapp writes on
comodor whatsapp writes off
```

Das ist mit Absicht ein Terminal-Befehl. Ein Bot, der seine eigenen
Berechtigungen erweitern könnte, bräuchte nur noch das Telefon von
irgendeinem Menschen.

## Die Knöpfe

WhatsApp erlaubt **drei** Antwortknöpfe mit zwanzig Zeichen, oder einen
Knopf, der eine Liste von **zehn** Zeilen öffnet. Das sind harte Grenzen —
Meta verwirft die ganze Nachricht, statt sie zu kürzen —, daher ist das
Menü eine Liste, und sie ist genau zehn Zeilen lang:

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

Während eine Aufgabe läuft, ist das Einzige, was angeboten wird, **Stop**:
Auf einem Bildschirm so schmal bleibt kein Platz, ein Steuerelement
herumstehen zu haben, grau ausgegraut.

Längere Listen — Modelle, Skills, Verlauf — werden
achtaufeinanderfolgend geblättert, denn die zwei Navigationszeilen zählen
gegen die zehn.

## Zwei Dinge, die dich überraschen werden

**Er kann eine Nachricht nicht bearbeiten.** Telegram streamt eine Antwort,
indem es eine Nachricht umschreibt, während die Antwort eintrifft. WhatsApp
hat kein Bearbeiten, und eine Nachricht pro Token wären hundert
Benachrichtigungen für eine Frage. Also sagt ein Zug eine Zeile, wenn er
beginnt, spricht gelegentlich, während er arbeitet, und sendet die Antwort,
wenn es eine gibt.

**Es gibt ein tageslanges Fenster.** Meta erlaubt freie Nachrichten nur
innerhalb von vierundzwanzig Stunden nach *deiner* letzten Nachricht.
Endet eine lange Aufgabe danach, kann der Bot es dir nicht sagen — er
schreibt es in sein Protokoll, und ihm erneut zu schreiben öffnet das
Fenster wieder.

## Betreiben

Genau wie bei Telegram:

```bash
comodor whatsapp start                # here, holding this terminal
comodor whatsapp start --tunnel       # and bring a tunnel up with it
comodor whatsapp start --background   # detached; survives closing it
comodor whatsapp stop
comodor whatsapp service install      # starts at login, survives a reboot
comodor whatsapp service show         # read the unit before trusting it
```

Das Protokoll ist `whatsapp.log` neben deiner Konfiguration, angehängt
statt ersetzt.

Ein **User**-Dienst auf jeder Plattform — systemd, launchd, Task Scheduler
— niemals ein System-Dienst. Dies ist ein Agent, der deine Dateien mit
deinen Zugangsdaten liest und schreibt, und mehr Autorität als der Mensch,
dem diese Dateien gehören, kauft nichts.

## Wie er gebaut ist

Keine neue Abhängigkeit. Die Cloud API ist `POST /messages` über den
HTTP-Client, den dieses Projekt bereits hat, und der Webhook ist
`http.server` aus der Standardbibliothek.

Der Endpunkt antwortet Meta **bevor** er die Arbeit tut. Meta wiederholt
alles, wofür es nicht innerhalb von Sekunden ein 200 bekommt, und ein
Agentenzug dauert Minuten — ein Webhook, der wartet, bekommt dieselbe
Nachricht fünfmal zugestellt.

Nachrichten-Ids werden gemerkt, sodass eine Zustellung, die dennoch
eintrifft, nicht zu einem zweiten Zug wird.

## Was er nicht tut

- Jedem antworten, der nicht verknüpft ist, oder sagen, warum.
- Einen Webhook annehmen, den er nicht verifizieren kann. Ohne ein
  App-Geheimnis wird nichts verifiziert, und `comodor whatsapp status`
  sagt es in Gelb.
- Ein Token, eine Nummer oder ein erlaubtes Konto aus der
  `.comodor/config.json` eines Projekts übernehmen. Ein Repository, das
  seinen Autor auf diese Liste bringen könnte, wäre eine Hintertür.
- Irgendetwas bearbeiten, bevor `whatsapp writes on`.
- Das Token ausgeben. Es ist aus jedem aufgeworfenen Fehler geschwärzt.
