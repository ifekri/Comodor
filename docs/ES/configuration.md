# Configuración

Un archivo JSON que nunca tienes que editar a mano — pero aquí está todo lo que
contiene.

---

## Dónde viven las cosas

| | |
|---|---|
| `~/.comodor/config.json` | tuyo. Lo escribe el asistente; permisos solo para el propietario |
| `~/.comodor/brain.db` | lo que ha aprendido |
| `~/.comodor/sessions/` | cada conversación |
| `~/.comodor/skills/` | skills que instalaste o escribiste |
| `./.comodor/config.json` | del proyecto. Seguro de commitear — ver [lo que puede fijar](safety.md#what-a-repository-may-set) |
| `./.comodor/checkpoints/` | el contenido anterior de cada archivo que cambió |

En Windows, `~/.comodor` es `%APPDATA%\Comodor`. `COMODOR_HOME` lo sobrescribe
en todas partes.

```bash
comodor doctor      # tells you exactly where all of these are
```

---

## Qué manda

Cuatro capas. La posterior vence a la anterior.

```
1. built-in defaults
2. ~/.comodor/config.json         yours
3. ./.comodor/config.json         the project's — restricted
4. environment variables          ANTHROPIC_API_KEY, COMODOR_MODEL, …
5. the command line               --model, --mode, … for one run
```

### Qué escribe `/save`

**Solo lo que elegiste.** Esto importa más de lo que suena.

La configuración sobre la que corre el agente son las cuatro capas fusionadas.
Escribir eso de vuelta en tu archivo convertiría el techo de gasto de un
repositorio clonado en tu valor global permanente, y copiaría al disco una clave
de API que deliberadamente mantuviste en tu entorno.

Así que `/save` recuerda de dónde vino cada valor. Un valor que siga sosteniendo
lo que aportó una capa prestada vuelve a lo que decía *tu* archivo; un valor que
cambiaste durante la sesión es tuyo y se escribe.

- `/model x` y luego `/save` → persiste `x`
- `/save` en un repositorio que fija `max_cost_usd: 500` → no persiste nada de
  eso
- `/save` con `ANTHROPIC_API_KEY` exportada → la clave se queda en tu entorno

---

## Cada ajuste

### `provider` y `model`

```json
{ "provider": "anthropic", "model": "claude-sonnet-5" }
```

Ver [Elegir un modelo](models.md).

### `agent` — cómo funciona

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
| `mode` | `act`, `plan` (solo lectura), `chat` (sin herramientas) |
| `loop` | seguir trabajando hasta terminar, o responder una vez |
| `max_steps` | **`0` — sin límite, y ese es el valor por defecto.** Un refactoring de una docena de archivos se quedó sin veinticuatro pasos a mitad de pensamiento, y un número de pasos no tiene relación con el daño. Pon un número para devolverlo |
| `max_seconds` | una hora. `0` para sin límite |
| `max_cost_usd` | el techo que se corresponde con lo que cuesta que algo salga mal — [donde el modelo tiene tarifa publicada](cost.md#when-the-limit-cannot-fire). `0` para sin límite |
| `context_limit` | el medidor. Sigue al modelo automáticamente al cambiar |
| `compact_at` | resume el historial a partir de esta fracción del límite |
| `max_tool_chars` | cuánto de un resultado de una herramienta llega al modelo. El resto se escribe en un archivo que se le indica cómo leer — no se trunca |
| `keep_screenshots` | cuántas se quedan en la conversación. [Por qué](computer.md#screenshots-and-what-they-cost) |
| `system_prompt_extra` | tus propias instrucciones permanentes |
| `prompt_cache` | dejar que el proveedor vuelva a servir el prefijo invariable. [Costo](cost.md) |
| `prompt_cache_ttl` | `5m` o `1h`. La hora cuesta más escribirse |

### `safety` — lo que puede hacer

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

Explicación completa: [Seguridad y permisos](safety.md).

### `learning` — lo que recuerda

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
| `top_k` | lecciones recordadas por turno |
| `max_playbook_tokens` | tope duro de lo que el recall puede inyectar |
| `reflect` | destila lecciones tras una tarea — esta cuesta una llamada al modelo |
| `reflect_model` | un modelo más barato para eso, si quieres |
| `half_life_days` | qué tan rápido se desvanece una lección sin usar |
| `share_scope` | `project` o `global` |
| `corrections`, `rules`, `announce`, `prefetch` | el carril rápido — gratis, sin llamada al modelo, activo incluso con `reflect` apagado |

Explicación completa: [Cómo aprende](learning.md).

### `ui` — cómo se ve

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

`banner: false` apaga la marca para siempre; `COMODOR_BANNER=0` lo hace por una
sola ejecución.

### `skills` — procedimientos

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

Explicación completa: [Skills](skills.md).

### `telegram` — desde tu teléfono

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
| `enabled` | si `comodor telegram start` ejecuta el bot |
| `token` | de [@BotFather](https://t.me/botfather). La configuración de la primera ejecución lo pide, o `comodor telegram connect` |
| `allowed` | los ids numéricos de usuario de Telegram a los que responde, y nadie más. Los llena `comodor telegram pair`, nunca Telegram mismo |
| `allow_writes` | si un turno iniciado desde un teléfono puede editar archivos y ejecutar comandos. Apagado lo mantiene en modo plan sin importar cómo esté configurada la terminal |
| `pair_window` | segundos que un código de emparejamiento sigue siendo válido |

**El `.comodor/config.json` de un proyecto no puede fijar nada de esto.** Un
repositorio que pudiera añadir una cuenta a `allowed` sería una puerta trasera,
y a diferencia del navegador o la pantalla no habría nada visible mientras
ocurre.

Explicación completa: [Desde tu teléfono](telegram.md).

### `slack` — desde un espacio de trabajo de Slack

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
| `bot_token` | `xoxb-…` de OAuth & Permissions. Hace todo lo que hace el bot |
| `app_token` | `xapp-…` de Basic Information, con el scope `connections:write`. Abre el websocket de Socket Mode, y nada más |
| `allowed` | Los ids de usuario de Slack a los que responde. No nombres visibles: un nombre visible lo puede cambiar la persona que lo tiene |
| `allow_writes` | Si un turno de Slack puede editar archivos y ejecutar comandos |
| `pair_window` | Segundos que un código de emparejamiento sigue siendo válido |
| `team` | El espacio de trabajo al que se conectó, recordado para que `status` pueda nombrarlo sin un viaje de ida y vuelta |

**El `.comodor/config.json` de un proyecto no puede fijar nada de esto**, por la
misma razón que los demás: un repositorio que pudiera añadir una cuenta a
`allowed` sería una puerta trasera.

Explicación completa: [Desde Slack](slack.md).

### `whatsapp` — desde un número de WhatsApp

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
| `token` | Un token de acceso de Meta. Un token de System User no expira; el propio del panel dura 24 horas |
| `phone_number_id` | El id numérico que Meta muestra junto al número, no el número |
| `app_secret` | Cada webhook se firma con él. Sin uno, nada se verifica |
| `verify_token` | Se devuelve como eco durante el apretón de manos único de Meta. Generado, no elegido |
| `allowed` | Los números a los que responde, comparados como dígitos. Todos los demás reciben silencio |
| `allow_writes` | Si un turno de WhatsApp puede editar archivos y ejecutar comandos |
| `host`, `port`, `path` | Dónde escucha el webhook. Localhost, detrás de algo que termina TLS |
| `public_url` | La dirección a la que Meta entrega, recordada para que `whatsapp webhook` pueda imprimirla |
| `api_version` | Fijado, porque Meta deprecia versiones según su calendario, no el tuyo |

**El `.comodor/config.json` de un proyecto no puede fijar nada de esto**, por la
misma razón que `telegram`: un repositorio que pudiera añadir un número a
`allowed` sería una puerta trasera sin nada en pantalla que muestre que ocurre.

Explicación completa: [Desde WhatsApp](whatsapp.md).

### `browser` — el navegador real

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

`headless: false` es como lo ves trabajar. `port` se conecta a un navegador que
arrancaste tú, así puede usar una sesión en la que ya iniciaste sesión en lugar
de que le entreguen tu perfil.

Explicación completa: [El navegador real](browser.md).

### `computer` — tu pantalla

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

Explicación completa: [Usar tu pantalla](computer.md).

### `gateway` — enrutamiento entre proveedores

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

`policy` es `cost`, `speed` o `quality`. Con `enabled: true` elige de la `chain`
y salta un proveedor que sigue fallando. `F5` o `/gw` en la interfaz.

### `mcp` — servidores de Model Context Protocol

```json
{
  "mcp": {
    "enabled": true,
    "servers": { }
  }
}
```

Se gestiona con `comodor mcp`, no a mano. [Servidores MCP](mcp.md).

---

## Variables de entorno

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, … | una por proveedor |
| `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODEL` | sobrescribir un endpoint o un modelo |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | forzar cualquiera de los dos |
| `COMODOR_HOME` | dónde vive todo |
| `COMODOR_BANNER=0` | sin marca |
| `COMODOR_NO_IMPORT=1` | no ofrecer importar de otro agente |
| `COMODOR_WEB_TOKEN` | un token fijo para la interfaz web |
| `NO_COLOR` | sin color |

---

## Cuando un ajuste no surte efecto

Comodor te lo dice en lugar de ignorarte:

```
config: agent.max_steps must be a whole number; keeping 24
config: this project cannot set safety, computer — only your own can
```

Un valor del tipo equivocado se convierte donde eso no es ambiguo, se rechaza
donde sí lo es, y el rechazo nombra la clave y lo que se esperaba. `null` no
reemplaza en silencio una cadena con `None`.

Si un ajuste todavía parece no hacer nada:

```bash
comodor doctor          # what it actually loaded
```

```
/settings               # the same, in the interface
```
