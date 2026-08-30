# Vom Telefon aus

Comodor lässt sich über einen Telegram-Bot steuern: ihm eine Aufgabe
schicken, bei der Arbeit zusehen, seine Fragen beantworten und ihn stoppen
— ohne ein Terminal zu öffnen.

**Die Ersteinrichtung fragt danach.** Die letzte von sechs Fragen bietet
an, einen Bot zu verbinden, prüft das Token direkt und dort bei Telegram
und verknüpft dein Konto, bevor der Assistent fertig ist. Wenn du *Not now*
gesagt hast oder eine bereits konfigurierte Maschine einrichtest:

```bash
comodor telegram connect <token>   # a bot from @BotFather
comodor telegram pair              # add your account
comodor telegram start             # run it
```

Er führt dieselbe Agentensitzung, die die Browser-Oberfläche führt.
Alles ist ein Knopf; Tippen ist für die Aufgabe selbst da.

## Einen Bot bekommen

Schreibe [@BotFather](https://t.me/botfather) auf Telegram an, sende
`/newbot`, gib ihm einen Namen und einen Benutzernamen, der auf `bot`
endet. Er antwortet mit einem Token:

```
1234567890:AAF…
```

```bash
comodor telegram connect 1234567890:AAF…
```

## Verknüpfen

**Der Benutzername eines Bots ist öffentlich.** Jeder, der ihn findet, kann
ihm eine Nachricht schicken, und dieser kann deine Dateien lesen. Er
antwortet daher einer festen Liste numerischer Telegram-Benutzer-IDs und
niemandem sonst.

```bash
comodor telegram pair
```

Das gibt einen sechsstelligen Code aus. Schicke ihn deinem Bot auf
Telegram, und dein Konto wird hinzugefügt. Der Code funktioniert einmal und
läuft nach fünf Minuten ab.

Alle anderen bekommen **Stille** — keine Ablehnung. Ein Bot, der „du bist
nicht erlaubt" sagt, hat einem Fremden mitgeteilt, dass er existiert, dass
er ein Comodor ist und dass es eine Liste gibt, auf die es sich zu bringen
lohnt.

```bash
comodor telegram status         # who may talk to it
comodor telegram forget 12345   # revoke one account
comodor telegram forget all     # revoke everybody
```

## Was er kann und was er nicht kann

**Standardmäßig liest und plant er und ändert nichts.** Eine
Telegram-Sitzung bleibt im Plan-Modus, ganz gleich, worauf das Terminal
eingestellt ist.

Das ist mit Absicht so. Einen Shell-Befehl mit dem Daumen freigeben, auf
einem Telefon, in einer Warteschlange, ist eine Entscheidung mit weniger
Aufmerksamkeit als dieselbe Freigabe an einer Tastatur — und die Folgen
sind identisch.

```bash
comodor telegram writes on      # let it edit files and run commands
comodor telegram writes off
```

Mit eingeschalteten Schreibvorgängen fragt er trotzdem zuerst, und die
Freigabe ist ein Knopf im Chat:

```
Comodor wants to run
  npm test

  ✓  Yes, once
  ✓✓ Yes, and stop asking this session
  ✗  No
```

Das weitreichendste Versprechen ist nie der erste Knopf unter deinem Daumen
— auf einem Telefon liegen sie nahe beieinander, und „immer" lässt sich
nicht rückgängig machen.

## Die Knöpfe

`/start` antwortet mit dem Modell, dem Ordner und dem, was es tun darf, und
den Einstellungen darunter. Sie stehen auf dem ersten Bildschirm statt
hinter einem *Settings*-Knopf, denn worauf ein Bot gerichtet ist, ist das
Erste, was jeder wissen will, und das Erste, was er ändern will.

| | |
|---|---|
| **New chat** | Das Gespräch bisher vergessen |
| **History** | Ein früheres Gespräch erneut öffnen, ganz |
| **Stop** | Unterbrechen, was läuft — ersetzt *New chat*, solange es läuft |
| **Mode** | Handeln, planen oder chatten, jeweils ausgeschrieben |
| **Status** | Modell, Ordner, Kontext, Ausgaben |
| **Model** | Jedes Modell, das der Anbieter anbietet; antippen zum Wechseln |
| **Folder** | Auf welches Projekt es beschränkt ist |
| **Skills** | Einen aus der Bibliothek installieren oder entfernen |
| **Rules** | Was es aus deinen Korrekturen gelernt hat, und wie viel |
| **Settings** | Der Rest — Kosten und was es darf |
| **Help** | Was alles tut, ohne den Chat zu verlassen |

Wenn der Agent eine Entscheidung braucht, fragt er ebenfalls mit Knöpfen —
dieselben Fragen, die er im Terminal stellen würde, eine pro Bildschirm,
mit **Write my own** für alles, woran er nicht gedacht hat.

Listen länger als ein Bildschirm — Modelle, Skills, Verlauf — werden
sechsaufeinanderfolgend geblättert, mit **Previous** und **Next**. Telegram
rendert achtzig Knöpfe gern, aber niemand scrollt sie durch.

## Betreiben

Drei Wege, geordnet nach der Dauer, für die du ihn willst.

```bash
comodor telegram start                # here, holding this terminal
comodor telegram start --background   # detached; survives closing the terminal
comodor telegram service install      # starts at every login, survives a reboot
```

**Im Vordergrund** hält er das Terminal und zeigt, was er tut. Das ist der
Weg zum Einrichten und der, zu dem du zurückkommst, wenn etwas nicht
funktioniert.

**Im Hintergrund** ist es derselbe Prozess, vom Terminal abgelöst, das ihn
startete, und schreibt in ein Protokoll statt auf einen Bildschirm. Das
Terminal schließen, sich abmelden, die Sitzung beenden — nichts davon
nimmt ihn mit.

```bash
comodor telegram stop        # end it
comodor telegram status      # is it running, since when, and as which pid
```

Das Protokoll ist `telegram.log` neben deiner Konfiguration, und es wird
angehängt statt ersetzt — der Grund, warum ein Bot gestern Nacht
aufgehört hat, steht in den Zeilen, die ein Neustart sonst löschen würde.

**Bei der Anmeldung** ist die Sache des Betriebssystems, nicht unsere:
Nichts, was ein Programm für sich selbst startet, überlebt einen Neustart
der Maschine.

```bash
comodor telegram service show        # read the unit before trusting it
comodor telegram service install
comodor telegram service uninstall
```

| | |
|---|---|
| Linux | eine systemd-**User**-Einheit in `~/.config/systemd/user` |
| macOS | ein LaunchAgent in `~/Library/LaunchAgents` |
| Windows | eine Task-Scheduler-Aufgabe, die bei Anmeldung läuft |

Ein Benutzer-Dienst auf allen dreien, niemals ein System-Dienst. Ein
Systemdienst läuft als root oder als SYSTEM, und dies ist ein Agent, der
deine Dateien mit deinen Zugangsdaten liest und schreibt — mehr Autorität
als der Mensch, dem diese Dateien gehören, kauft nichts und kostet alles,
falls er je falsch liegt.

`service show` gibt die Einheit aus, bevor `service install` sie schreibt.
Niemand sollte gebeten werden, einer Daemon-Definition zu vertrauen, die
ihm nicht gezeigt wurde.

Der Ordner zählt auf allen dreien: Der Agent liest und schreibt nur
innerhalb des Verzeichnisses, in dem er gestartet wurde, und das ist das
eine, in dem der Bot arbeiten wird.

## Wie er gebaut ist

Keine neue Abhängigkeit. Die Bot-API ist `getUpdates` in einer Schleife und
`sendMessage`, über den HTTP-Client, den dieses Projekt bereits hat —
`python-telegram-bot` wäre das Größte im Rad gewesen, nur dafür.

Die Antwort wird per Timer bearbeitet statt pro Token. Telegram berechnet
eine Hin- und Rückfahrt pro Bearbeitung und begrenzt deren Rate, sodass
Bearbeiten pro Token eine Nachricht ergibt, die gedrosselt am Ende alles
auf einmal ankommt.

Der Bot hält einen Update-Offset und schiebt ihn weiter, während er geht.
Ohne einen spielt ein Neustart jede Nachricht wieder, die der Bot je
empfangen hat — was für einen Agenten, der Befehle ausführt, nicht bloß
laut ist.

## Was er nicht tut

- Jedem antworten, der nicht verknüpft ist, oder sagen, warum.
- Ein Token oder ein erlaubtes Konto aus der `.comodor/config.json` eines
  Projekts übernehmen. Ein Repository, das seinen Autor auf diese Liste
  bringen könnte, wäre eine Hintertür, und anders als beim Browser oder
  Bildschirm gäbe es nichts auf dem Bildschirm, das es beim Geschehen
  zeigte.
- Irgendetwas bearbeiten, bevor `telegram writes on`.
- Das Token ausgeben. Es steht in jeder Bot-API-URL, also wird es aus
  jedem aufgeworfenen Fehler herausgestrichen.
