# La interfaz

Lo que ves, lo que pulsas y los 29 comandos.

```bash
comodor          # start it
comodor --demo   # the whole interface, offline, no key
```

---

## El diseño

```
┌────────────────────────────────────────────────────────────────────────┐
│  Comodor                              Anthropic · claude-sonnet-5      │
│  ────────────────────────────────────────────────────────────────────  │
│                                                                        │
│  TASKS                    > fix the failing parser test                │
│  ● read the test          ▸ read_file  tests/test_parser.py     0.1s   │
│  ◐ find the cause         ▸ run_shell  pytest tests/test_pa…    2.3s   │
│  ○ fix it                                                              │
│                           The test expects `parse("")` to raise, but…  │
│                                                                        │
│  ────────────────────────────────────────────────────────────────────  │
│  ▌Type a task, or / for commands                                       │
│                                                                        │
│  act · loop on · 12% of 1M · $0.03      ⏎ send  ^O attach  F3 mode     │
└────────────────────────────────────────────────────────────────────────┘
```

**La barra lateral** es el plan, cuando lo hay. `F2` la oculta — vale la pena
hacerlo en una terminal estrecha.

**La línea de estado** muestra el modo, si está iterando, cuán lleno está el
contexto y cuánto ha costado esta sesión. La cifra del contexto es real: sigue
al modelo, así que cambiar de un modelo de un millón de tokens a uno de 128k la
cambia de inmediato.

Funciona desde unas 60 columnas hacia arriba. Por debajo, la barra lateral se
pliega sola. `comodor preview 80x24` la renderiza a cualquier tamaño sin
iniciar una sesión.

---

## Modos

| Modo | Lo que el agente puede hacer | |
|---|---|---|
| **act** | Todo, preguntando antes de escrituras y comandos | el predeterminado |
| **plan** | Solo lectura. Sin escrituras, sin comandos, sin red | para "¿qué harías?" |
| **chat** | Sin herramientas en absoluto | para una pregunta sobre código que pegas |

`F3` los rota. `/mode plan` fija uno directamente.

El modo plan es de verdad de solo lectura — se aplica en la capa de permisos,
no pidiéndole amablemente al modelo. Una herramienta con un riesgo superior a
"safe" se rechaza antes de ejecutarse.

---

## Teclas

| | |
|---|---|
| `Enter` | enviar |
| `Ctrl+J` | nueva línea dentro de un mensaje |
| `Esc` | detener lo que está haciendo |
| `Ctrl+C` | detener; dos veces para salir |
| `F1` | ayuda |
| `F2` | la barra lateral |
| `F3` | modo |
| `F4` | activar o desactivar el loop |
| `F5` | el gateway |
| `Ctrl+O` | adjuntar un archivo |
| `Ctrl+L` | limpiar la conversación |
| `PgUp` `PgDn` | desplazar |
| `Ctrl+↑` `Ctrl+↓` | mensajes anteriores y posteriores |
| `!command` | ejecutar un comando de shell directamente, sin preguntarle al modelo |

Vale la pena recordar `!`. `!git status` lo ejecuta y te muestra la salida; el
modelo nunca ve la pregunta. Más barato y más rápido que preguntar.

---

## Comandos

Escribe `/` y la lista se filtra mientras escribes.

### Pídele que cambie lo que está haciendo

| | |
|---|---|
| `/mode [act\|plan\|chat]` | lo que se le permite hacer |
| `/loop` | seguir trabajando hasta terminar, o responder una vez |
| `/model [id]` | elegir el modelo — una lista, o nómbralo |
| `/provider [name]` | elegir el proveedor |
| `/gw` | el gateway: enrutar entre proveedores por costo, velocidad o calidad |

### Enséñale

| | |
|---|---|
| `/good` | esa respuesta fue correcta |
| `/bad` | esa respuesta fue incorrecta |
| `/teach <text>` | recuerda esto |
| `/memory` | lo que ha aprendido |
| `/rules` | las reglas de la casa que sacó de tu código y tus ediciones |
| `/progress` | la evidencia de que está mejorando |
| `/skills` | procedimientos que sigue cuando el trabajo encaja |

`/good` y `/bad` son lo más barato que puedes hacer por él. Ver
[Cómo aprende](learning.md).

### Deshacer y mirar atrás

| | |
|---|---|
| `/undo` | restaurar el último archivo que cambió |
| `/clear` | empezar una conversación nueva |
| `/resume [id]` | reabrir una sesión anterior |
| `/search <text>` | buscar algo en una conversación anterior |
| `/export [path]` | escribir esta sesión a un archivo |

### Dejar que llegue más lejos

| | |
|---|---|
| `/computer [15m\|1h this app\|stop]` | dejarle usar tu pantalla — [guía](computer.md) |
| `/mcp` | servidores MCP y sus herramientas — [guía](mcp.md) |
| `/attach <path>` | añadir un archivo al siguiente mensaje |

### Ponerlo a punto

| | |
|---|---|
| `/settings` | lo que está configurado ahora mismo |
| `/approve [writes\|shell\|all]` | dejar de preguntar antes de eso |
| `/theme [name]` | ember, midnight, matrix, mono |
| `/save` | escribir los ajustes actuales a tu archivo de configuración |
| `/cost` | tokens, gasto y lo que ahorró la caché |
| `/copy [all\|task]` | la última respuesta, o todo, al portapapeles |
| `/mouse [on\|off]` | seguimiento del ratón, para que puedas seleccionar texto tú mismo |
| `/help` | todo esto, dentro de la interfaz |
| `/quit` | salir |

**`/save` escribe solo lo que elegiste.** No los ajustes del repositorio, no una
clave que guardas en tu entorno, no un `--model` que pasaste para una sola
ejecución. Ver [Configuración](configuration.md#what-save-writes).

---

## Aprobaciones

Cuando el agente quiere escribir un archivo o ejecutar un comando:

```
  Write  src/parser.py
  ────────────────────────────────────────────
   - def parse(text):
   -     return text.split(",")
   + def parse(text):
   +     if not text:
   +         raise ValueError("nothing to parse")
   +     return text.split(",")

  [a] allow   [A] allow always this session   [d] deny
```

`A` lo recuerda por el resto de la sesión, por tipo de cosa — permitir
escrituras no permite comandos.

Negar no es en vano. Un rechazo es la señal de preferencia más clara que la
interfaz recoge, y va al motor de aprendizaje: el agente tiene menos
probabilidad de proponerlo de nuevo.

Para dejar de recibir preguntas del todo:

```
/approve writes      files, yes; commands, still ask
/approve all         everything
```

Todo sigue teniendo punto de control. `/undo` funciona igual.

---

## Copiar texto hacia fuera

Mientras se rastrea el ratón, un arrastre le pertenece a Comodor y la terminal
nunca lo ve — así que el habitual seleccionar y copiar no funciona. Tres
maneras de rodearlo:

```
/copy              the last answer
/copy all          the whole conversation
/copy task         the last thing you asked for
/mouse             mouse tracking off, so selection works as usual
```

`/copy` no necesita nada instalado en Windows ni macOS. En Linux usa
`wl-copy`, `xclip` o `xsel`, el que esté, y dice cuál falta si no hay ninguno.

Sobre SSH recurre a una secuencia de escape que le pide a *tu* terminal poner
el texto en *tu* portapapeles — así el texto de un agente en un servidor
aterriza donde puedes pegarlo, en lugar de quedarse en un servidor que no
tiene portapapeles.

La mayoría de las terminales también permiten seleccionar con **Shift**
pulsado, lo que esquiva el rastreo del ratón sin desactivarlo.

---

## Quién está hablando

Cada turno descansa sobre una banda discreta — un tono detrás de lo que
escribiste, otro detrás de la respuesta:

```
▌ › why does the parser drop the last field?              ← warm

▌   Because split is called with a maxsplit of 2 …        ← neutral
▌
▌   ┌─ python ────────────────────────┐
▌   │ return text.split(',', 2)       │
▌   └─────────────────────────────────┘
```

Deliberadamente discretas. Esto está detrás de un texto que lees durante
minutos seguidos, y un fondo con presencia propia compite con las palabras.
Cada tema tiene su propio par, a un pequeño porcentaje de su fondo; `mono` no
tiene ninguno, porque un tema cuya premisa es la ausencia de color no quiere
dos.

No cuestan espacio vertical — el cambio de color es la frontera.

---

## Texto de derecha a izquierda

El persa, el árabe y el hebreo se alinean a la derecha, donde sus líneas
comienzan, con una pila de fuentes que les conviene. Los párrafos mixtos — un
identificador en inglés dentro de una frase en persa — se tratan por línea en
lugar de por archivo, que es lo que de verdad pasa en una conversación
técnica.

---

## Temas

```
/theme midnight
```

`ember` (el predeterminado, ámbar cálido), `midnight` (azul frío), `matrix`
(verde), `mono` (sin color alguno).

`--ascii` cambia los caracteres de dibujo de cajas por ASCII, para terminales
sin ellos. `NO_COLOR` en tu entorno se respeta.

---

## Ver también

- [Desde la terminal](cli.md) — la misma potencia sin la interfaz
- [Lo que el agente puede hacer](tools.md) — las herramientas detrás de esas filas `▸`
- [Seguridad](safety.md) — lo que los avisos de aprobación protegen
