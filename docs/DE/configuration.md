# Konfiguration

Eine JSON-Datei, die Sie nie von Hand bearbeiten müssen — aber hier ist alles,
was in ihr steht.

---

## Wo die Dinge liegen

| | |
|---|---|
| `~/.comodor/config.json` | Ihres. Der Assistent schreibt es; nur-besitzer-Berechtigungen |
| `~/.comodor/brain.db` | was es gelernt hat |
| `~/.comodor/sessions/` | jede Konversation |
| `~/.comodor/skills/` | Skills, die Sie installiert oder geschrieben haben |
| `./.comodor/config.json` | das des Projekts. Unbedenklich einzupflegen — siehe [was es setzen darf](safety.md#what-a-repository-may-set) |
| `./.comodor/checkpoints/` | der vorherige Inhalt jeder Datei, die es geändert hat |

Unter Windows ist `~/.comodor` `%APPDATA%\Comodor`. `COMODOR_HOME` überschreibt
es überall.

```bash
comodor doctor      # tells you exactly where all of these are
```

---

## Was sich durchsetzt

Vier Schichten. Die spätere schlägt die frühere.

```
1. built-in defaults
2. ~/.comodor/config.json         yours
3. ./.comodor/config.json         the project's — restricted
4. environment variables          ANTHROPIC_API_KEY, COMODOR_MODEL, …
5. the command line               --model, --mode, … for one run
```

### Was `/save` schreibt

**Nur was Sie gewählt haben.** Das ist wichtiger, als es klingt.

Die Konfiguration, auf der der Agent läuft, ist die Verschmelzung aller vier
Schichten. Das in Ihre Datei zurückzuschreiben würde die Ausgabendeckelung eines
geklonten Repositorys zu Ihrem dauerhaften globalen Standard machen und einen
API-Schlüssel, den Sie bewusst in Ihrer Umgebung gehalten haben, auf die Platte
kopieren.

Deshalb merkt sich `/save`, woher jeder Wert kam. Ein Wert, der immer noch das
hält, was eine geliehene Schicht geliefert hat, kehrt zu dem zurück, was *Ihre*
Datei sagte; ein Wert, den Sie während der Sitzung geändert haben, ist Ihrer und
wird geschrieben.

- `/model x` gefolgt von `/save` → hält `x` fest
- `/save` in einem Repository, das `max_cost_usd: 500` festnagelt → hält nichts
  dergleichen fest
- `/save` mit exportiertem `ANTHROPIC_API_KEY` → der Schlüssel bleibt in Ihrer
  Umgebung

---

## Jede Einstellung

### `provider` und `model`

```json
{ "provider": "anthropic", "model": "claude-sonnet-5" }
```

Siehe [Ein Modell wählen](models.md).

### `agent` — wie es arbeitet

```json
{
  "agent": {
    "mode": "act",
    "loop": true,
    "max_steps": 0,
    "max_seconds": 3600.0,
    "max_cost_usd": 2.0,
    "context_limit": 1000000,
    "compact_at": 0.75,
    "temperature": 0.3,
    "max_output_tokens": 8192,
    "max_tool_chars": 12000,
    "keep_screenshots": 2,
    "system_prompt_extra": "",
    "prompt_cache": true,
    "prompt_cache_ttl": "5m"
  }
}
```

| | |
|---|---|
| `mode` | `act`, `plan` (nur lesend), `chat` (keine Werkzeuge) |
| `loop` | weiterarbeiten, bis es fertig ist, oder einmal antworten |
| `max_steps` | **`0` — kein Limit, und das ist der Standard.** Ein Refactor über ein Dutzend Dateien hinweg brach mitten im Gedanken nach vierundzwanzig Schritten ab, und eine Schrittanzahl hat keine Beziehung zu Schaden. Eine Zahl setzen, um es zurückzuholen |
| `max_seconds` | eine Stunde. `0` für kein Limit |
| `max_cost_usd` | die Decke, die auf das abbildet, was ein Fehlschlagen kostet — [wo das Modell einen veröffentlichten Tarif hat](cost.md#when-the-limit-cannot-fire). `0` für kein Limit |
| `context_limit` | die Anzeige. Folgt dem Modell automatisch beim Wechsel |
| `compact_at` | den Verlauf zusammenfassen, sobald dieser Anteil des Limits überschritten ist |
| `max_tool_chars` | wie viel von einem Werkzeugergebnis das Modell erreicht. Der Rest wird in eine Datei geschrieben, der gesagt wird, wie sie zu lesen ist — nicht abgeschnitten |
| `keep_screenshots` | wie viele in der Konversation bleiben. [Warum](computer.md#screenshots-and-what-they-cost) |
| `system_prompt_extra` | Ihre eigenen stehenden Anweisungen |
| `prompt_cache` | den Anbieter den unveränderten Präfix neu ausliefern lassen. [Kosten](cost.md) |
| `prompt_cache_ttl` | `5m` oder `1h`. Die Stunde kostet beim Schreiben mehr |

### `safety` — was es tun darf

```json
{
  "safety": {
    "auto_approve_safe": true,
    "auto_approve_writes": false,
    "auto_approve_shell": false,
    "checkpoints": true,
    "workspace_only": true,
    "allow_commands": [],
    "deny_commands": ["rm -rf /", "..."],
    "max_file_read_bytes": 512000,
    "max_file_scan_bytes": 64000000,
    "trusted_folders": []
  }
}
```

Vollständige Erklärung: [Sicherheit und Berechtigungen](safety.md).

### `learning` — was es sich merkt

```json
{
  "learning": {
    "enabled": true,
    "top_k": 6,
    "max_playbook_tokens": 800,
    "reflect": true,
    "reflect_model": "",
    "min_confidence": 0.15,
    "half_life_days": 45.0,
    "share_scope": "project",
    "associative": true,
    "corrections": true,
    "rules": true,
    "announce": true,
    "prefetch": true
  }
}
```

| | |
|---|---|
| `top_k` | Lektionen, pro Zug abgerufen |
| `max_playbook_tokens` | harte Grenze dessen, was der Abruf injizieren darf |
| `reflect` | nach einer Aufgabe Lektionen destillieren — das kostet einen Modellaufruf |
| `reflect_model` | ein billigeres Modell dafür, wenn Sie mögen |
| `half_life_days` | wie schnell eine ungenutzte Lektion verblasst |
| `share_scope` | `project` oder `global` |
| `corrections`, `rules`, `announce`, `prefetch` | die schnelle Spur — kostenlos, kein Modellaufruf, auch an, wenn `reflect` aus ist |

Vollständige Erklärung: [Wie er lernt](learning.md).

### `ui` — wie es aussieht

```json
{
  "ui": {
    "theme": "ember",
    "ascii_borders": false,
    "mouse": true,
    "max_fps": 20,
    "show_timestamps": false,
    "sidebar": true,
    "banner": true,
    "syntax_theme": ""
  }
}
```

`banner: false` schaltet die Wortmarke für immer ab; `COMODOR_BANNER=0` tut es
für einen Lauf.

### `skills` — Abläufe

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000,
    "install_examples": true
  }
}
```

Vollständige Erklärung: [Skills](skills.md).

### `telegram` — vom Handy aus

```json
{
  "telegram": {
    "enabled": false,
    "token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300
  }
}
```

| | |
|---|---|
| `enabled` | ob `comodor telegram start` den Bot laufen lässt |
| `token` | von [@BotFather](https://t.me/botfather). Die Ersteinrichtung fragt danach, oder `comodor telegram connect` |
| `allowed` | die numerischen Telegram-Benutzer-ids, denen es antwortet, und niemand sonst. Gefüllt durch `comodor telegram pair`, niemals von Telegram selbst |
| `allow_writes` | ob ein vom Handy begonnener Zug Dateien bearbeiten und Befehle ausführen darf. Aus hält es im Plan-Modus, wie auch immer das Terminal gesetzt ist |
| `pair_window` | Sekunden, die ein Kopplungscode gut bleibt |

**Die `.comodor/config.json` eines Projekts darf hiervon nichts setzen.** Ein
Repository, das ein Konto zu `allowed` hinzufügen könnte, wäre eine Hintertür,
und anders als beim Browser oder Bildschirm gäbe es nichts Sichtbares, während
es passiert.

Vollständige Erklärung: [Vom Handy aus](telegram.md).

### `slack` — aus einem Slack-Workspace

```json
{
  "slack": {
    "enabled": false,
    "bot_token": "",
    "app_token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300,
    "team": ""
  }
}
```

| | |
|---|---|
| `bot_token` | `xoxb-…` aus OAuth & Permissions. Tut alles, was der Bot tut |
| `app_token` | `xapp-…` aus Basic Information, Scope `connections:write`. Öffnet den Socket-Mode-Websocket, und nichts sonst |
| `allowed` | Die Slack-Benutzer-ids, denen es antwortet. Keine Anzeigenamen: ein Anzeigename kann von der Person geändert werden, die ihn hält |
| `allow_writes` | Ob ein Slack-Zug Dateien bearbeiten und Befehle ausführen darf |
| `pair_window` | Sekunden, die ein Kopplungscode gut bleibt |
| `team` | Der Workspace, mit dem es verbunden wurde, gemerkt, damit `status` ihn ohne Rundreise nennen kann |

**Die `.comodor/config.json` eines Projekts darf hiervon nichts setzen**, aus
demselben Grund wie bei den anderen: ein Repository, das ein Konto zu `allowed`
hinzufügen könnte, wäre eine Hintertür.

Vollständige Erklärung: [Aus Slack](slack.md).

### `whatsapp` — von einer WhatsApp-Nummer

```json
{
  "whatsapp": {
    "enabled": false,
    "token": "",
    "phone_number_id": "",
    "app_secret": "",
    "verify_token": "",
    "allowed": [],
    "allow_writes": false,
    "host": "127.0.0.1",
    "port": 8770,
    "path": "/whatsapp",
    "public_url": "",
    "api_version": "v21.0"
  }
}
```

| | |
|---|---|
| `token` | Ein Meta-Zugriffs-Token. Ein System-User-Token läuft nicht ab; das des Dashboards selbst hält 24 Stunden |
| `phone_number_id` | Die numerische id, die Meta neben der Nummer zeigt, nicht die Nummer |
| `app_secret` | Jeder Webhook ist damit signiert. Ohne eines wird nichts verifiziert |
| `verify_token` | Während Metas einmaligem Handshake zurückgeechot. Generiert, nicht gewählt |
| `allowed` | Die Nummern, denen es antwortet, als Ziffern verglichen. Alle anderen erhalten Schweigen |
| `allow_writes` | Ob ein WhatsApp-Zug Dateien bearbeiten und Befehle ausführen darf |
| `host`, `port`, `path` | Wo der Webhook lauscht. Localhost, hinter etwas, das TLS terminiert |
| `public_url` | Die Adresse, an die Meta ausliefert, gemerkt, damit `whatsapp webhook` sie ausgeben kann |
| `api_version` | Festgenagelt, denn Meta veraltet Versionen nach ihrem Kalender, nicht nach Ihrem |

**Die `.comodor/config.json` eines Projekts darf hiervon nichts setzen**, aus
demselben Grund wie `telegram`: ein Repository, das eine Nummer zu `allowed`
hinzufügen könnte, wäre eine Hintertür ohne etwas auf dem Bildschirm, das zeigt,
dass es passiert.

Vollständige Erklärung: [Aus WhatsApp](whatsapp.md).

### `browser` — der echte Browser

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

`headless: false` ist die Art, bei der Arbeit zuzusehen. `port` verbindet sich
mit einem Browser, den Sie selbst gestartet haben, sodass er eine Sitzung
benutzen kann, in der Sie bereits angemeldet sind, statt Ihr Profil überreicht
zu bekommen.

Vollständige Erklärung: [Der echte Browser](browser.md).

### `computer` — Ihr Bildschirm

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

Vollständige Erklärung: [Den Bildschirm benutzen](computer.md).

### `gateway` — Routing über Anbieter hinweg

```json
{
  "gateway": {
    "enabled": false,
    "policy": "quality",
    "chain": [],
    "failure_threshold": 3,
    "cooldown_seconds": 60.0
  }
}
```

`policy` ist `cost`, `speed` oder `quality`. Mit `enabled: true` wählt es aus
`chain` und geht über einen Anbieter hinweg, der ständig fehlschlägt. `F5` oder
`/gw` in der Oberfläche.

### `mcp` — Model Context Protocol Server

```json
{
  "mcp": {
    "enabled": true,
    "servers": { }
  }
}
```

Verwaltet mit `comodor mcp`, nicht von Hand. [MCP-Server](mcp.md).

---

## Umgebungsvariablen

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, … | eine je Anbieter |
| `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODEL` | einen Endpunkt oder ein Modell überschreiben |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | eines von beiden erzwingen |
| `COMODOR_HOME` | wo alles lebt |
| `COMODOR_BANNER=0` | keine Wortmarke |
| `COMODOR_NO_IMPORT=1` | keinen Import aus einem anderen Agenten anbieten |
| `COMODOR_WEB_TOKEN` | ein fester Token für die Weboberfläche |
| `NO_COLOR` | keine Farbe |

---

## Wenn eine Einstellung nicht greift

Comodor sagt es, statt Sie zu ignorieren:

```
config: agent.max_steps must be a whole number; keeping 24
config: this project cannot set safety, computer — only your own can
```

Ein Wert vom falschen Typ wird dort umgewandelt, wo das eindeutig ist,
verweigert, wo es das nicht ist, und die Verweigerung nennt den Schlüssel und
was erwartet wurde. `null` ersetzt nicht stillschweigend eine Zeichenkette
durch `None`.

Wenn eine Einstellung immer noch nichts zu tun scheint:

```bash
comodor doctor          # what it actually loaded
```

```
/settings               # the same, in the interface
```
