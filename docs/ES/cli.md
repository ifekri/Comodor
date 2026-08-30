# Desde la terminal

Todos los comandos y flags, con algo que puedes pegar.

```bash
comodor help              # the written help page
comodor help computer     # one topic in more detail
```

---

## Instalar y actualizar

```bash
curl -fsSL get.comodor.ai | sh     # macOS, Linux, BSD
```

```powershell
irm get.comodor.ai | iex          # Windows
```

`get.comodor.ai` no nombra ningún archivo: detecta qué cliente pregunta y
responde con el instalador que ese cliente puede ejecutar. La misma línea
actualiza una instalación existente. O, una vez que está en tu máquina:

```bash
comodor update --check    # what is out there
comodor update            # move to it
```

[Primeros pasos](getting-started.md#1-install) tiene el resto — los gestores de
paquetes y lo que aceptan los instaladores.

---

## Arrancarlo

```bash
comodor                              # the interface
comodor --demo                       # the interface, offline, no key needed
comodor --resume                     # reopen the last session
comodor --resume 2026-08-22-a4f1     # reopen one by id
comodor --cwd ~/projects/api         # work somewhere other than here
comodor --model claude-sonnet-5      # a different model, this run only
comodor --mode plan                  # start read-only
```

### Opciones

| | |
|---|---|
| `--provider NAME` | `openrouter`, `anthropic`, `openai`, `ollama`, … |
| `--model ID` | sobrescribir el modelo para esta ejecución |
| `--mode act\|plan\|chat` | plan es de solo lectura; chat no tiene herramientas |
| `--no-loop` | responder una vez en lugar de trabajar hasta terminar |
| `--cwd PATH` | la carpeta que puede tocar |
| `--theme NAME` | `ember`, `midnight`, `matrix`, `mono` |
| `--ascii` | bordes ASCII |
| `--no-mouse` | dejar el ratón a la terminal |
| `--resume [ID]` | la última sesión, o una por id |
| `--demo` | proveedor offline con guion |
| `--version` | qué versión es esta |
| `-h`, `--help` | la página de ayuda escrita |

Nada de esto se escribe en tu configuración. Se aplica solo a esa ejecución.
Para que un cambio permanezca, usa `/save` dentro de la interfaz o edita el
archivo de configuración — [Configuración](configuration.md).

---

## `comodor run` — una tarea, sin interfaz

```bash
comodor run "fix the failing test in tests/test_parser.py"
comodor run "add type hints to src/parser.py" --yes
comodor run "what does this project do?" --json
comodor run "refactor the parser" --max-steps 40
```

| | |
|---|---|
| `--yes` | aprobar escrituras y comandos automáticamente |
| `--json` | un resultado legible por máquina en stdout |
| `--max-steps N` | sobrescribir el límite de pasos para esta ejecución |

Sin `--yes` preguntará, por stderr, y se negará en lugar de asumir si nada
puede responder. Es deliberado: un script que se autoaprueba en silencio es un
script que hace algo que no esperabas a las tres de la madrugada.

`--json` te da:

```json
{
  "text": "Fixed. The parser raised on empty input rather than returning [\"\"] …",
  "ok": true,
  "stopped": "done",
  "steps": 6,
  "tool_calls": 11,
  "error": "",
  "usage": {
    "input_tokens": 18422,
    "output_tokens": 640,
    "cost_usd": 0.031
  },
  "elapsed": 24.71
}
```

`stopped` dice por qué terminó — uno de:

| | |
|---|---|
| `done` | decidió que había terminado |
| `max_steps` | alcanzó `agent.max_steps` |
| `budget` | alcanzó `agent.max_cost_usd` o `agent.max_seconds` |
| `cancelled` | lo interrumpiste |
| `error` | algo salió mal; `error` dice qué |

`ok` es verdadero para `done` y `max_steps` — quedarse sin pasos no es un
fallo, es un techo haciendo su trabajo — así que comprueba también `stopped`
si necesitas la diferencia:

```bash
comodor run "update the changelog for this release" --yes --json > result.json
jq -e '.stopped == "done"' result.json
```

También aprende de una ejecución sin interfaz. Una corrección que haces
después enseña la misma lección que enseñaría una interactiva.

---

## `comodor setup` — elegir un proveedor y un modelo

```bash
comodor setup
```

Seis preguntas, o siete si hay otro agente instalado y ofrece importar. Se
ejecuta automáticamente en la primera ejecución; usa esto para cambiar de
opinión después.

Las respuestas van a `~/.comodor/config.json`.

---

## `comodor import` — desde OpenClaw o Hermes

```bash
comodor import             # bring keys, model and skills across
comodor import --dry-run   # say what it would take, change nothing
comodor import --keys-only # leave the skills and the model
```

No se mueve nada y no se reemplaza nada de lo ya configurado aquí. Ver
[Vienes de otro agente](migrating.md).

---

## `comodor doctor` — ¿está todo bien?

```bash
comodor doctor
comodor doctor --fix
```

```
  ok    config file         ~/.comodor/config.json
  ok    config permissions  0o600
  ok    provider            Anthropic · claude-sonnet-5
  ok    model               claude-sonnet-5
  ok    spend limit         $2.00 per task
  ok    brain               ~/.comodor/brain.db
  ok    skills              4 loaded
  warn  version             0.8.9 installed; 0.9.0 is out
```

`--fix` repara lo reparable — un nombre de proveedor desactualizado, un
directorio que falta, un índice de búsqueda roto. Nunca cambia nada que no
haya reportado antes.

El código de salida es distinto de cero si algo falló, así que sirve en una
verificación de salud.

---

## `comodor web` — desde un navegador

```bash
comodor web                       # here, on 127.0.0.1:8765
comodor web --port 9000
comodor web --host 0.0.0.0        # reachable from elsewhere — read the warning
comodor web --no-browser          # do not open one
comodor web --token mytoken       # a fixed token instead of a fresh one
```

Guía completa: [Desde un navegador](web.md).

---

## `comodor telegram` — desde tu teléfono

```bash
comodor telegram connect <token>  # a bot from @BotFather
comodor telegram pair             # a one-time code that adds your account
comodor telegram start            # here, holding this terminal
comodor telegram start -b         # detached; survives closing the terminal
comodor telegram stop             # end a background one
comodor telegram service install  # start it at login, so a reboot brings it back
comodor telegram service show     # read the unit before trusting it
comodor telegram status           # what is configured, who may talk, is it up
comodor telegram writes on        # let a phone turn edit files
comodor telegram writes off
comodor telegram forget 12345     # revoke one account
comodor telegram forget all
comodor telegram off              # stop without forgetting anything
```

La configuración de la primera ejecución ofrece todo esto como su última
pregunta; estos comandos son para cambiarlo después, o para una máquina ya
configurada.

Guía completa: [Desde tu teléfono](telegram.md).

---

## `comodor slack` — desde un espacio de trabajo de Slack

```bash
comodor slack manifest            # the app definition to paste into Slack
comodor slack connect             # the two tokens, checked as you paste them
comodor slack pair                # a one-time code that adds your account
comodor slack start               # here, holding this terminal
comodor slack start -b            # detached
comodor slack stop
comodor slack service install     # start it at login
comodor slack status              # what is set, who may talk, is it running
comodor slack writes on           # let a Slack turn edit files
comodor slack forget U01234567
comodor slack off
```

Unos cinco minutos, y sin dirección pública: Socket Mode hace que la app abra
un websocket hacia fuera en lugar de que le publiquen.

Guía completa: [Desde Slack](slack.md).

---

## `comodor whatsapp` — desde un número de WhatsApp

```bash
comodor whatsapp connect          # guided: links each page, checks each value
comodor whatsapp connect --number-id … --token … --app-secret …
comodor whatsapp webhook          # what to paste into Meta's dashboard
comodor whatsapp pair             # a one-time code that adds your number
comodor whatsapp start            # here, holding this terminal
comodor whatsapp start --tunnel   # and bring a Cloudflare tunnel up with it
comodor whatsapp start -b         # detached
comodor whatsapp stop
comodor whatsapp service install  # start it at login
comodor whatsapp status           # what is set, who may talk, is it running
comodor whatsapp writes on        # let a phone turn edit files
comodor whatsapp forget 15551234567
comodor whatsapp off
```

Meta entrega los mensajes a una URL en lugar de dejarte sondearlos, así que
este necesita una dirección HTTPS pública. `connect` sin argumentos recorre
toda la configuración y levanta el túnel él mismo; unos veinte minutos la
primera vez, la mayoría dentro del panel de Meta. Sin número real, sin
tarjeta, sin verificación de negocio.

Guía completa: [Desde WhatsApp](whatsapp.md).

---

## `comodor skills` — procedimientos que sigue

```bash
comodor skills browse             # what is available
comodor skills list               # what you have
comodor skills add review taste   # install some
comodor skills update             # refresh installed ones
comodor skills remove review
```

Guía completa: [Skills](skills.md).

---

## `comodor mcp` — servidores de Model Context Protocol

```bash
comodor mcp list                  # what you have, and what it offers
comodor mcp catalogue             # what is available
comodor mcp add filesystem        # from the catalogue
comodor mcp custom NAME -- CMD    # a command of your own
comodor mcp remote NAME URL       # an HTTP server
comodor mcp enable NAME
comodor mcp disable NAME
comodor mcp remove NAME
comodor mcp test NAME             # connect and list its tools
```

Guía completa: [Servidores MCP](mcp.md).

---

## `comodor update` — pasar a la versión más nueva

```bash
comodor update --check     # what is out there, change nothing
comodor update             # do it
```

Averigua cómo se instaló esta copia — `uv`, `pipx`, `pip`, o un checkout del
código fuente — y usa lo correcto. Un checkout del código fuente se deja en
paz: ese es tuyo.

---

## `comodor uninstall` — eliminarlo por completo

```bash
comodor uninstall --dry-run    # list what would go
comodor uninstall              # ask, then do it
comodor uninstall --yes        # for scripts
```

```
Your data
  everything it has learned and everything you told it     4.2 MB
    ~/.comodor
    settings and your API key · 812 lessons · 47 sessions · 4 skills

In your projects
  api-server                                               128 KB
    ~/projects/api-server/.comodor
    checkpoints, project settings, project skills

The program
  the uv installation
    ~/.local/share/uv/tools/comodor

4.3 MB across 3 places. None of it can be undone.
```

Nombra todo antes de eliminar nada, y dice qué no puede encontrar — una
carpeta `.comodor` de un proyecto que usaste pero cuya historia de sesiones
fue limpiada no puede nombrarse, y te lo dice en lugar de fingir.

---

## `comodor preview` — la interfaz a un tamaño dado

```bash
comodor preview 80x24
comodor preview 200x50 --svg wide.svg
```

Renderiza un fotograma y sale. Útil para comprobar una terminal estrecha, o
para una captura de pantalla.

---

## Variables de entorno

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, … | una clave, por proveedor |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | forzar un proveedor o un modelo |
| `COMODOR_HOME` | dónde viven la configuración, el brain y las sesiones |
| `COMODOR_BANNER=0` | sin marca esta ejecución |
| `COMODOR_NO_IMPORT=1` | no ofrecer importar de otro agente |
| `COMODOR_WEB_TOKEN` | un token fijo para la interfaz web |
| `NO_COLOR` | sin color, respetado en todas partes |

Una clave en el entorno **nunca se escribe en tu archivo de configuración**.
Exportarla en lugar de guardarla es una decisión, y `/save` la respeta. Ver
[Configuración](configuration.md).

---

## Códigos de salida

| | |
|---|---|
| `0` | funcionó |
| `1` | no funcionó |
| `130` | lo interrumpiste |

---

## Ver también

- [La interfaz](interface.md) — la misma potencia, interactiva
- [Configuración](configuration.md) — hacer permanente un flag
- [Solución de problemas](troubleshooting.md) — cuando un comando no hace lo que dice
