# Documentación de Comodor

Un agente de programación en la terminal que aprende de la forma en que lo corriges.

¿Nuevo aquí? **[Primeros pasos](getting-started.md)** toma unos cinco minutos y
termina con el agente haciendo algo útil.

---

## Según lo que intentas hacer

### Empezar

| | |
|---|---|
| [Primeros pasos](getting-started.md) | Instalar, elegir un modelo, primera tarea |
| [Vienes de otro agente](migrating.md) | Traer claves y skills desde OpenClaw o Hermes |
| [Elegir un modelo](models.md) | Qué proveedor, qué modelo, cuánto cuesta |

### Usarlo

| | |
|---|---|
| [La interfaz](interface.md) | Paneles, teclas, modos y los 29 comandos |
| [Desde la terminal](cli.md) | Todos los comandos y flags, con ejemplos |
| [Lo que el agente puede hacer](tools.md) | Las 13 herramientas que tiene y cuándo usa cada una |
| [Skills](skills.md) | Procedimientos que escribes una vez y él sigue |

### Dejar que llegue más lejos

| | |
|---|---|
| [El navegador real](browser.md) | Un navegador que ejecuta JavaScript y puede iniciar sesión |
| [Usar tu pantalla](computer.md) | Ratón y teclado, en cualquier aplicación |
| [Desde un navegador](web.md) | La interfaz web, localmente o en un servidor |
| [En tu editor](acp.md) | Manejar Comodor desde Zed o cualquier cliente de Agent Client Protocol |
| [En Docker](docker.md) | Un comando, en un contenedor |
| [Servidores MCP](mcp.md) | Herramientas del Model Context Protocol |

### Entenderlo

| | |
|---|---|
| [Desde tu teléfono](telegram.md) | El bot de Telegram: emparejamiento, los botones y a quién responde |
| [Desde Slack](slack.md) | Socket Mode — cinco minutos, sin dirección pública, y responde en hilos |
| [Desde WhatsApp](whatsapp.md) | La Cloud API — unos veinte minutos y técnico. Telegram hace lo mismo en uno |
| [Modelos en tu máquina](local-models.md) | Descargar uno, ejecutarlo sin conexión, añadirlo a la lista |
| [Preguntas](questions.md) | El formulario que muestra cuando una petición se lee de dos maneras |
| [Cómo aprende](learning.md) | Correcciones, lecciones, reglas y la prueba |
| [Seguridad y permisos](safety.md) | Qué puede hacer, qué pregunta, qué nunca hace |
| [Costo](cost.md) | Caché, presupuestos y pagar menos por el mismo trabajo |
| [Configuración](configuration.md) | Cada ajuste, dónde viven los archivos, qué manda |

### Cuando algo falla

| | |
|---|---|
| [Solución de problemas](troubleshooting.md) | `doctor`, problemas comunes y cómo reportar uno |

---

## La versión más corta posible

```bash
curl -fsSL get.comodor.ai | sh      # macOS, Linux
irm get.comodor.ai | iex           # Windows

comodor                  # it asks a few questions, once
```

Luego escribe lo que quieras. Corrígelo cuando se equivoque — edita el archivo,
o simplemente díselo — y aprende. `/progress` te muestra si eso realmente está
funcionando.

```bash
comodor run "fix the failing test in tests/test_parser.py"   # one task, no interface
comodor web                                                  # from a browser
comodor doctor                                               # is everything alright?
comodor help                                                 # the written help page
```

## Lo que lo hace diferente

**Aprende de las correcciones, no de los elogios.** La mayoría de los agentes
olvidan en cuanto termina la sesión. Comodor observa qué cambias de su salida y
lo convierte en una lección con una confianza que sube cuando se cumple y baja
cuando no. [Cómo aprende](learning.md) explica el mecanismo; `/progress` muestra
la evidencia.

**Pregunta antes de actuar, y todo es reversible.** Leer es silencioso.
Escribir pregunta. Ejecutar un comando pregunta más fuerte. Cada escritura tiene
un punto de control, y `/undo` revierte la última. [Seguridad y
permisos](safety.md).

**Una sola dependencia.** El cliente HTTP, el lector de SSE, el WebSocket para
el navegador, el codificador PNG para las capturas de pantalla — todo parte del
paquete. Instalar Comodor trae `rich` y nada más.

**Puede usar un navegador real y un escritorio real.** No un simple descargador
de texto: un navegador que ejecuta JavaScript y conserva cookies, y — en
Windows — el ratón y el teclado, con un halo en pantalla que te muestra dónde va
a hacer clic. [Navegador](browser.md), [pantalla](computer.md).

---

## También en el repositorio

| | |
|---|---|
| [CHANGELOG](../CHANGELOG.md) | Qué cambió, y por qué |
| [CONTRIBUTING](../CONTRIBUTING.md) | Trabajar en el propio Comodor |
| [SECURITY](../SECURITY.md) | Reportar algo delicado |
| [RELEASING](../RELEASING.md) | Cómo se corta una versión |
