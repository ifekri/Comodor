# Modelle auf deiner eigenen Maschine

Comodor kann ein Modell herunterladen, auf deiner Platte behalten und dort
ausführen — kein Schlüssel, kein Konto, und es arbeitet weiter, auch mit
gezogenem Netzwerkkabel.

```bash
comodor local list                       # what you can run, and what is here
comodor local get qwen2.5-coder-7b-q4    # download it, with a progress bar
comodor local use qwen2.5-coder-7b-q4    # make it the one the agent talks to
```

Dieselbe Liste steht im Browser unter **Admin → Local LLM**, mit demselben
Herunterladen, demselben Fortschritt und denselben Knöpfen.

## Wie das aufgebaut ist und warum es nicht langsam ist

Alles, was glaubwürdig ist, tut dasselbe — Ollama, LM Studio, llama.cpp,
vLLM —, und Comodor tut es auch: **Die Inferenz läuft in einem getrennten
Prozess, der eine OpenAI-kompatible API spricht, und das Modell bleibt in
ihm zwischen Anfragen geladen.**

Drei Gründe, alle davon, dass der Agent ansprechbar bleibt:

**Die GIL.** Erzeugung ist eine lange, CPU-gebundene Schleife. Läuft sie in
Comodors eigenem Prozess, warten alle anderen Threads — die Oberfläche,
die sich neu zeichnet, ein Werkzeug, das fertig wird, der Ereignisbus —
hinter ihr. In einem anderen Prozess ist sie das Problem eines anderen
Kerns.

**Laden ist teuer und darf nur einmal geschehen.** Vier Gigabyte von der
Platte zu lesen und zu verteilen dauert Sekunden bis Zehner von Sekunden.
Pro Anfrage zu laden zahlt das bei jedem Zug; ein beständiger Server zahlt
es einmal und antwortet danach in Millisekunden.

**Ein Absturz bleibt drüben.** Ein Out-of-Memory-Tötung an einem 14B-Modell
beendet den Modellserver, nicht deine Sitzung. Der Agent meldet einen
Verbindungsfehler, und das Transkript überlebt.

Die erfreuliche Folge ist, dass es fast keinen neuen Code gibt: Ein lokaler
Server unter `http://127.0.0.1:PORT/v1` *ist* ein OpenAI-kompatibler
Endpunkt, also treibt der bestehende Anbieter ihn unverändert an. Der Port
wird gewählt, wenn der Server startet, weshalb der `local`-Anbieter keine
URL in der Konfiguration trägt — eine dort geschriebene wäre beim nächsten
Mal falsch.

Der Server startet bei deiner **ersten Nachricht**, nicht beim Start.
Vier Gigabyte bei jedem Ausführen von `comodor` zu laden — auch die Male,
in denen du das Modell nie etwas gefragt hast — wäre ein leerer Bildschirm
ohne Grund.

## Was du brauchst

Die Modelldatei, die Comodor herunterlädt, und etwas, um sie laufen zu
lassen. Comodor benutzt, was es findet:

```bash
brew install llama.cpp          # macOS
winget install llama.cpp        # Windows
                                # Linux: github.com/ggml-org/llama.cpp
```

Ollama oder LM Studio, falls eines davon bereits läuft, tun es ebenfalls.
`comodor local list` sagt klar und deutlich, wenn nichts verfügbar ist,
sodass du es erfährst, bevor du eine Stunde auf einen Download verwendest,
nicht danach.

## Der Download

Ein Modell sind ein bis neun Gigabyte über deine Heimleitung, und alles am
Download ist davon geprägt.

**Er setzt fort.** Bytes gehen in eine `.part`-Datei. Ihn stoppen, das
Notebook schließen, die Verbindung verlieren — das nächste `comodor local
get` bittet den Server, von dem Punkt fortzufahren, an dem diese Datei
endet. Der Browser zeigt `Resume (37%)` statt `Download`.

**Er wird verifiziert.** Jeder Katalogeintrag trägt eine exakte Bytezahl und
einen SHA-256, und die Datei wird nicht angenommen, bevor sie übereinstimmt.
Das ist nicht nur doppelter Boden: Ein abgeschnittenes GGUF ist *nicht*
offensichtlich defekt — es lädt, und dann erzeugt das Modell Unsinn, und du
verbringst einen Abend damit, zu ergründen, warum ein hochgelobtes Modell
nutzlos ist. Eine durchfallende Datei wird gelöscht, statt herumzuliegen und
später halb vertraut zu werden.

**Er ist mit anzusehen.** Im Terminal, ein Balken mit den vier Zahlen, die
die gestellte Frage beantworten:

```
qwen2.5-coder-7b-q4 ━━━━━━━━━━━━━━╸────────  38.2%  1.7/4.4 GB  8.9 MB/s  0:05:12
```

Im Browser dieselben Zahlen unter einem Balken auf der Karte des Modells,
aktualisiert aus dem Ereignisstrom statt durch Abfragen.

## Wohin die Dateien gehen

Ein Verzeichnis, geteilt von jedem Projekt auf der Maschine — dasselbe
Modell in drei Checkouts wäre sonst dreimal dieselben Bytes.

```bash
comodor local where
```

`comodor local remove <id>` löscht eines und sagt, wie viel zurückkam.

## Ein Modell zur Liste hinzufügen

Die Liste ist eine JSON-Datei, also ist ein neues Modell eine Bearbeitung
statt einer Veröffentlichung. Sowohl das Terminal als auch der Browser
nehmen es auf.

```json
{
  "id": "my-model-q4",
  "name": "My Model 7B",
  "description": "One sentence on what it is good at, and what it is not.",
  "url": "https://huggingface.co/OWNER/REPO/resolve/main/file.gguf",
  "size": 4683074336,
  "sha256": "1664fccab734674a...",
  "context": 32768,
  "parameters": "7B",
  "quantization": "Q4_K_M",
  "needs_ram_gb": 8,
  "license": "apache-2.0",
  "good_at": ["code"],
  "tools": true,
  "vision": false
}
```

`id`, `name`, `url` und `size` sind erforderlich — alles andere ist
optional, und was du weglässt, wird als unbekannt berichtet statt geraten.
Eine falsche Zahl hier kostet jemanden einen Download und einen Absturz.

Nimm die Größe und die Prüfsumme aus der API, statt sie zu tippen:

```bash
curl -s 'https://huggingface.co/api/models/OWNER/REPO?blobs=true' | python -c \
  "import json,sys;[print(f['rfilename'], f['size'], f.get('lfs',{}).get('sha256')) \
   for f in json.load(sys.stdin)['siblings'] if f['rfilename'].endswith('.gguf')]"
```

Zwei Regeln, die der Lader durchsetzt:

- **Nur `https`.** Eine Modelldatei ist ein ausführbares Artefakt in jeder
  Hinsicht, die zählt, und eine, die über einen Kanal geholt wurde, den
  jemand unterwegs umschreiben kann, ist nichts, was man erlaubt, weil ein
  Katalog darum bat.
- **Ein schlechter Eintrag kostet nicht die Liste.** Ein missgebildetes
  Modell wird übersprungen und der Rest lädt, denn die Alternative ist eine
  leere Auswahl.

Comodor bringt eine Kopie der Liste mit und sucht einmal am Tag nach einer
frischeren, wobei es das Gefundene zwischenspeichert. Ohne Netz benutzt es
den Zwischenspeicher, und schlägt das fehl, die mitgelieferte Kopie — was
der ganze Sinn davon ist, eine mitzuliefern.

## Was es nicht tut

`needs_ram_gb` wird gegen deine Maschine geprüft, bevor der Download
beginnt, und ein Modell, das nicht passt, sagt es, statt dich eine Stunde
herausfinden zu lassen. `comodor local get --yes` übergeht es, wenn du
anderer Meinung bist.

Die Platte wird genauso geprüft, mit einem Zehntel als Reserve: Ein
Download, der das letzte Byte einer Platte füllt, scheitert nicht nur, er
nimmt den Rest der Maschine mit.
