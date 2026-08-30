# Ein Modell wählen

Comodor arbeitet mit allem, was die OpenAI- oder Anthropic-API spricht —
siebzehn Anbieter ab Werk, plus alles andere mit einer URL.

---

## Die kurze Antwort

| Sie möchten | Wählen |
|---|---|
| Den einfachsten Einstieg, ein Schlüssel, alles | **OpenRouter** |
| Die stärkste agentische Arbeit | **Anthropic**, `claude-sonnet-5` |
| Nichts zahlen und offline bleiben | **Ollama** oder **LM Studio** |
| Sehr günstig, gut in Code | **DeepSeek** |
| Sehr schnell | **Groq** oder **Cerebras** |

```bash
comodor setup        # pick one, once
```

---

## Jeder Anbieter

**Gehostet, ein Schlüssel:** OpenRouter · Anthropic · OpenAI · Google Gemini ·
DeepSeek · xAI · Mistral · Groq · Cerebras · Moonshot (Kimi) · Z.AI (GLM) ·
Qwen · Together · Fireworks · Xiaomi MiMo

**Auf Ihrem Rechner, kein Schlüssel:** Ollama · LM Studio

**Alles andere:** *Something else* wählen und eine Basis-URL angeben. Jeder
OpenAI-kompatible Endpunkt funktioniert.

---

## Es lokal betreiben, umsonst

```bash
ollama pull qwen2.5-coder:14b
comodor setup           # choose Ollama
```

Kein Schlüssel, keine Kosten, kein Netzwerk. Ein 14B-Coder-Modell ist wirklich
brauchbar für die tägliche Arbeit; der Unterschied zeigt sich bei langen
Mehrstufig-Aufgaben.

---

## Wechseln

```bash
comodor --model claude-haiku-4-5      # this run only
```

```
/model                  # a list of what the provider offers
/model gpt-4o           # by name
/provider               # a different provider entirely
```

Die Kontextanzeige folgt dem Modell. Der Wechsel von einem Million-Token-Modell
auf ein 128k-Modell ändert das Limit sofort — das ist wichtig, denn der Agent
kompaktiert die Konversation bei einem Bruchteil davon, und ein veraltetes Limit
bedeutet, dass er nie kompaktiert und dann an der echten Decke des Anbieters
scheitert.

Um einen Wechsel dauerhaft zu machen: `/save`, oder
`~/.comodor/config.json` bearbeiten.

---

## Schlüssel

Beide Orte funktionieren, und keiner wird auf den anderen kopiert:

```json
{ "providers": { "anthropic": { "api_key": "sk-ant-…" } } }
```

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

Ein Schlüssel in Ihrer Umgebung **bleibt dort** — `/save` schreibt ihn nicht
auf die Platte. Exportieren statt Speichern ist eine Entscheidung, und sie wird
respektiert.

Comodors eigene Konfigurationsdatei wird mit nur-besitzer-Berechtigungen
geschrieben, und Ihr Schlüssel erscheint nie in einem Log, einer Mitschrift,
einem Export oder einem Traceback.
[Sicherheit](safety.md#your-keys).

---

## Das Gateway

Über mehrere Anbieter hinweg routen, statt einen festzunageln.

```
/gw                    # or F5
```

```json
{
  "gateway": {
    "enabled": true,
    "policy": "quality",
    "chain": ["anthropic", "openrouter", "deepseek"],
    "failure_threshold": 3
  }
}
```

`policy` ist `cost`, `speed` oder `quality`. Ein Anbieter, der dreimal in Folge
scheitert, wird für eine Minute übersprungen. Die Statuszeile zeigt
`GW: Quality`, wenn es an ist, `GW: Disable`, wenn nicht.

---

## Vision

Manche Werkzeuge geben Bilder zurück — `browse look`, und jeder `computer`-
Screenshot. Die brauchen ein Modell, das sehen kann. Die gesamte aktuelle
Claude- und GPT-4o-Familie kann es; die meisten offenen Modelle nicht.

Wenn Sie vorhaben, [den Bildschirm](computer.md) zu benutzen, prüfen Sie
zuerst, ob das Modell Augen hat, sonst bekommt es ein Bild überreicht, das es
nicht lesen kann, und rät.

---

## Was es kostet

```
/cost
```

Siehe [Kosten](cost.md) für Caching, Budgets und warum eine Ausgabenbegrenzung
manchmal nicht erzwungen werden kann.
