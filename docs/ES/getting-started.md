# Primeros pasos

Cinco minutos, terminando con el agente haciendo algo útil.

---

## 1. Instalar

Una línea. El resto lo resuelve él.

**macOS · Linux · BSD**

```bash
curl -fsSL get.comodor.ai | sh
```

**Windows** — PowerShell

```powershell
irm get.comodor.ai | iex
```

```
Comodor — it learns the way you correct it.

  Linux x86_64
> Installing uv, a package manager Comodor needs (about 15 MB)
  from https://astral.sh/uv — it fetches a Python too, if one is missing
> Installing with uv

✓ comodor 0.9.0

  Linked into /usr/local/bin, which is on your PATH.

  comodor              start the interface
  comodor --demo       try it offline, no API key needed
  comodor doctor       check what is configured
```

**Una sola dirección para ambos.** `get.comodor.ai` no nombra ningún archivo.
Detecta qué cliente pregunta y envía `curl` y `wget` al instalador de shell,
PowerShell al instalador de Windows, y un navegador a esta página — así la línea
que pegas es la misma en todos los sistemas, y nunca tienes que elegir.

**Termina el trabajo.** Alguien que ejecuta una línea desde una página web no ha
aceptado depurar nada, así que el script instala lo que necesita — un entorno
aislado, un gestor de paquetes, un Python — en lugar de detenerse a explicarte
lo que ya deberías tener. Verificado en un `debian:bookworm-slim` limpio, sin
ningún Python.

### Nada que teclear después, casi siempre

Donde puede, coloca `comodor` en algún lugar que tu shell ya esté mirando, así
que funciona en la terminal desde la que lo ejecutaste — sin `export`, sin
ventana nueva. Eso cubre root, los contenedores, CI y cualquier Mac con
Homebrew.

Donde no puede — una cuenta Linux ordinaria, donde nada en `PATH` es escribible
— ningún instalador puede ayudar, porque un proceso hijo no puede cambiar el
entorno del shell que lo ejecutó. Así que lo dice:

```
  Every new terminal can run comodor already.
  This one started before the install, and no installer
  can reach back into the shell that ran it. For this
  terminal only:

    export PATH="/home/you/.local/bin:$PATH"
```

Abre una terminal nueva y simplemente funciona. La línea va tanto al archivo rc
de tu shell como a tu perfil de inicio de sesión, así que la encuentra cualquier
tipo de shell — interactiva, de login, no interactiva y una sesión de escritorio.

### Si prefieres no canalizar un script a un shell

Totalmente razonable. Ambos scripts son texto plano que puedes leer primero —
nombrados directamente, porque la dirección corta manda a la página cualquier
cosa que no sea un fetcher:

```bash
curl -fsSL https://comodor.ai/install.sh  | less
curl -fsSL https://comodor.ai/install.ps1 | less
```

O usa un gestor de paquetes que ya tengas:

```bash
uv tool install comodor      # isolated, and the fastest
pipx install comodor         # isolated
pip install comodor          # into whatever environment you are in
```

Comodor necesita **Python 3.11 o más nuevo** y nada más.

### Comprueba que llegó

```bash
comodor --version
```

Si el shell no lo encuentra, el instalador añadió un directorio a tu `PATH` que
esta terminal todavía no conoce. Abre una nueva, o ejecuta la línea `export` que
el instalador imprimió.

### Opciones que los instaladores entienden

| | |
|---|---|
| `COMODOR_FORCE_TOOL` | fijar el método: `uv`, `pipx`, `venv` o `pip` |
| `COMODOR_NO_BOOTSTRAP` | nunca descargar una herramienta; fallar en su lugar |
| `COMODOR_NO_MODIFY_PATH` | no tocar el perfil de tu shell |
| `COMODOR_INSTALL_REF` | instalar desde un git ref o una ruta local en lugar de PyPI |

```bash
COMODOR_NO_MODIFY_PATH=1 curl -fsSL get.comodor.ai | sh
```

> **¿Aún no estás seguro de querer instalarlo?** `comodor --demo` ejecuta toda
> la interfaz contra un proveedor offline con guion. Sin clave, sin cuenta, sin
> red.

---

## 2. Elegir un modelo

Ejecútalo. La primera vez hace seis preguntas y no vuelve a preguntar.

```bash
comodor
```

```
 1/6  Which model provider?
┌─  Providers  ───────────────────────────────────────────┐
│ ›  OpenRouter        One key, hundreds of models         │
│    Anthropic         Claude, direct from the source      │
│    OpenAI            GPT models, direct                  │
│    Ollama (local)    Runs on your machine. No key        │
└──────────────────────────────────────────────────────────┘
  ↑↓ move   enter choose   tab more   esc cancel
```

Flechas, o escribe para filtrar. **Tab** abre la descripción completa de lo que
esté señalando la flecha, en el mismo cuadro — las listas muestran una línea por
fila para que quepan en la pantalla, y algunas de esas descripciones son un
párrafo.

Con tubería o en un script, las mismas preguntas llegan como una lista
numerada, así que se puede automatizar.

**¿Sin clave y sin dinero?** Elige **Ollama** o **LM Studio**. Se ejecutan en tu
máquina, no necesitan clave y no cuestan nada. Todo en esta documentación
funciona con ellos excepto las partes que digan lo contrario.

**¿Ya usas OpenClaw o Hermes?** La primera pantalla ofrece traer tus claves, tu
modelo y tus skills. No se mueve nada y no se reemplaza nada de lo ya
configurado aquí. Ver [Vienes de otro agente](migrating.md).

Tus respuestas van a `~/.comodor/config.json`, legible solo por ti. Cambia de
opinión después con `comodor setup`, o de un ajuste a la vez — ver
[Configuración](configuration.md).

### La última pregunta es tu teléfono

```
 6/6  Run it from your phone?
┌─  From your phone  ─────────────────────────────────────────────┐
│ ›  Not now    you can set any of them up later                   │
│    Telegram   one token from @BotFather — about a minute         │
│    Slack      an app from a manifest, two tokens — five minutes  │
│    WhatsApp   a Meta app and a public address — twenty minutes   │
└──────────────────────────────────────────────────────────────────┘
```

**Telegram** toma un token de [@BotFather](https://t.me/botfather), lo verifica
contra Telegram allí mismo, y muestra un código para enviarle al bot y que sepa
a qué cuenta responder — un minuto, de principio a fin.
Ver [Desde tu teléfono](telegram.md).

**Slack** toma unos cinco. La app se crea a partir de un manifiesto que Comodor
imprime, así que es un pegado en lugar de una página de casillas, y Socket Mode
significa que no hace falta ninguna dirección pública — ver [Desde
Slack](slack.md).

**WhatsApp** hace lo mismo y toma unos veinte minutos: una app de Meta, un
número de negocio, un secreto de app y una dirección HTTPS pública, ninguno de
los cuales se puede crear desde una terminal. Vale la pena solo si tiene que ser
WhatsApp — ver [Desde WhatsApp](whatsapp.md).

En cualquier caso solo lee y planifica hasta que digas lo contrario, y rechazar
cuesta una tecla.

### Y luego ofrece arrancar

```
 What now?
   1  Start Comodor          — the interface, here in this terminal
   2  Start the Telegram bot — in the background, answers while this is closed
   3  Both
   4  Nothing yet            — `comodor` starts it whenever you want
```

La configuración terminaba aquí, de vuelta en el prompt del shell con nada
ejecutándose. Aparece una línea de teléfono por cada canal conectado y
emparejado, con nombre — alguien que configuró WhatsApp no recibe la oferta de
"el bot de Telegram".

---

## 3. Pregunta en qué carpeta

```
  Work in  /home/you/projects/api-server ?
```

Se pregunta una vez por carpeta. Todo lo que el agente puede tocar está dentro
de ella — no puede leer ni escribir fuera sin que tú desactives eso
deliberadamente. Las carpetas aprobadas se recuerdan.

---

## 4. Pide algo

Escríbelo y pulsa Enter.

```
> the tests in tests/test_parser.py are failing, work out why and fix it
```

Leerá archivos, ejecutará los tests y cambiará algo. Antes de escribir un
archivo recibes un diff y una elección:

```
  Write  src/parser.py
    - 12 lines removed, 8 added
  [a] allow   [A] allow always this session   [d] deny
```

Responde `a` una vez, o `A` si prefieres que deje de preguntar por el resto de
la sesión. En cualquier caso, cada escritura tiene punto de control: `/undo`
revierte la última.

---

## 5. Corrígelo — esta es la parte que importa

Cuando se equivoca en algo, díselo. Hay dos formas, y ambas le enseñan lo
mismo:

**Edita el archivo tú mismo.** Comodor nota qué cambiaste de su salida.

**Díselo.**

```
> no — we use single quotes in this codebase, not double
```

En cualquier caso se convierte en una lección: se recuerda la próxima vez que
la situación parezca similar, con una confianza que sube cuando se cumple y
decae cuando no.

Después de unas sesiones:

```
> /progress
```

```
◈ Corrections per task down 100% since the first tasks in this project.

metric                trend                       now  vs first
Steps per task        ▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇    6.1      ↑10%
Corrections per task  ████████▅▅▅▅▅▅▅▅▁▁▁▁▁▁▁▁    0.0     ↓100%
Approvals asked       ▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅    2.0         —
Tokens per task       ▁▁▁▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▇▇▇███  12.0K      ↑40%
First-try success     ▁██████▁██████▁██████▁██    86%         —

brain    7 rules · 812 lessons · 24 corrections learned from
history  24 tasks over 8 days
success  83% overall
```

Eso es evidencia, no una afirmación. Si la tasa de correcciones no baja, el
aprendizaje no está funcionando, y el panel lo dice en lugar de ocultarlo.

[Cómo aprende](learning.md) explica el mecanismo.

---

## 6. Lo que vale la pena saber el primer día

```
/help          every command
/mode          act · plan (read-only) · chat (no tools)     F3 cycles
/undo          restore the last file it changed
/cost          tokens, spend, what the cache saved
Esc            stop it, mid-thought
Ctrl-C twice   leave
```

---

## Dónde ir después

| Quieres | Lee |
|---|---|
| Usarlo sin la interfaz, en un script | [Desde la terminal](cli.md) |
| Saber exactamente qué puede hacerle a tu máquina | [Seguridad y permisos](safety.md) |
| Pagar menos | [Costo](cost.md) |
| Dejarle usar un navegador | [El navegador real](browser.md) |
| Dejarle usar tu ratón y teclado | [Usar tu pantalla](computer.md) |
| Escribir un procedimiento que él siga cada vez | [Skills](skills.md) |
| Ejecutarlo en un servidor, o en Docker | [Desde un navegador](web.md), [En Docker](docker.md) |

---

## Si algo salió mal

```bash
comodor doctor
```

Comprueba todo lo que puede y te dice qué hacer con cualquier cosa que
encuentre. `comodor doctor --fix` repara lo reparable. Ver
[Solución de problemas](troubleshooting.md).
