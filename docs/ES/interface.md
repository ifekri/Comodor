# La interfaz

Lo que ves, lo que pulsas, y de dónde sale todo lo que hay en pantalla.

```bash
comodor          # iniciarla
comodor --demo   # toda la interfaz, sin conexión, sin clave
```

La interfaz corre sobre [Bun](https://bun.sh) — `comodor doctor` dice si está.
Sin él, `comodor run "..."` hace una tarea sin interfaz y `comodor web` sirve
una en el navegador.

Cómo está construida — el núcleo que dirige, el protocolo entre ambos, y por
qué cada dato en pantalla es del núcleo y no de la pantalla — está en
[tui-v2.md](../tui-v2.md). Esta página es la versión corta para quien la usa.

---

## La pantalla

```
┌──────────────────────────────────────────┬───────────────────────┐
│ Comodor   ~/work/my-project  fake-1      │ Agents         1 live │
│                                          │  ● d1 running    12.3s│
│  You                                     │    survey the retries │
│  fix the failing parser test             │ Tasks            2/5  │
│                                          │  ◐ write the tests    │
│  Comodor                                 │  ● read the code      │
│  The test expects parse("") to raise, …  │  ○ run the suite      │
│  ✓ read_file  tests/test_parser.py  0.2s │                       │
│  ● run_shell  pytest tests/…     running…│                       │
│      collected 12 items                  │                       │
│                                          │                       │
├──────────────────────────────────────────┴───────────────────────┤
│ ▌ask for anything                                                │
├──────────────────────────────────────────────────────────────────┤
│  [ACT]   PLAN    ASK    Reads, writes and runs commands…         │
│ ● 1 agent  tab Mode  ctrl+b Work  ctrl+k Commands      42% ctx  │
└──────────────────────────────────────────────────────────────────┘
```

**La cabecera** nombra el proyecto y el proveedor y modelo que responden. Es lo
que informa el núcleo, no lo que dice un archivo de configuración: cuando el
modelo cambia — desde aquí, desde otro cliente, o por el propio núcleo — la
cabecera lo sigue.

**La conversación** lleva dentro la línea de tiempo de las herramientas. Cada
llamada a una herramienta está donde ocurrió, como una fila: una marca (`●` en
ejecución, `✓` terminada, `×` fallida), el nombre, un resumen de una línea, y
cuánto tardó. Una herramienta en ejecución muestra las últimas líneas de su
salida; una terminada se pliega, y hacer clic en ella abre lo que el núcleo aún
conserva.

**El banco de trabajo** — `Ctrl+B` — es el trabajo fuera de la conversación:
la lista de tareas que el agente lleva para sí, y cualquier agente en segundo
plano que haya iniciado, cada uno con su estado. En una terminal estrecha se
abre sobre la conversación en lugar de al lado, y la misma tecla lo cierra.

**El pie** imprime lo que puedes pulsar, de la misma lista de la que se leen
las teclas, y lo que ha costado esta sesión donde el proveedor lo mide.

---

## Teclas

| Tecla | Hace |
|---|---|
| `Enter` | envía lo que escribiste |
| `Tab` / `Shift+Tab` | modo siguiente / anterior |
| `Ctrl+K` | la paleta de comandos — cada acción, con búsqueda |
| `Ctrl+B` | abrir o cerrar el banco de trabajo |
| `End` | volver a la salida más reciente tras subir |
| `PageUp` / `PageDown` | desplazar la conversación |
| `Ctrl+R` | reenviar un mensaje que el núcleo rechazó |
| `Ctrl+C` | detener lo que está haciendo; salir cuando está inactivo |
| `Ctrl+D` | salir |
| `Esc` | cerrar la paleta, salir de un campo, o tomar la opción segura de una tarjeta |

Cada atajo que muestra el pie existe; no se puede imprimir una pista para una
tecla que no está asignada.

---

## Modos

```
ACT    lee, escribe y ejecuta comandos, preguntando antes de cambiar cosas
PLAN   lee y planifica; no puede escribir, ejecutar ni cambiar nada
ASK    lo conversa; sin herramientas en absoluto
```

`Tab` los recorre. La etiqueta se mueve cuando el núcleo confirma, no cuando
baja la tecla: las pulsaciones dentro de un mismo viaje de ida y vuelta se
acumulan — tres Tab preguntan una vez, por donde apuntaba el tercero — y un
cambio rechazado lo dice con palabras en lugar de mover la etiqueta.

---

## Cuando te pregunta algo

Una tarjeta de permiso o un formulario de preguntas toma el teclado mientras
está abierto, para que una tecla destinada a una decisión no pueda también
enviar un mensaje.

- **Las flechas** se mueven entre las opciones o las preguntas; **Enter** envía.
- **Esc** toma la opción segura propia de la petición — para un permiso es
  *denegar*, para un cambio de modo propuesto es *sin cambio* — y la tarjeta
  dice cuál. Nunca permite nada.
- No hay atajo de una sola tecla para *permitir*. Permitir cuesta un movimiento
  hasta la opción y otro para confirmarla, para que una tecla pulsada por
  cualquier otro motivo no pueda autorizar un comando.
- Una pregunta que ofrece una fila de escribe-lo-tuyo abre un campo para ello
  con `Space`; `Esc` sale del campo antes de cancelar el formulario.

Dos cosas pueden estar esperando a la vez — dos herramientas paralelas pueden
preguntar cada una — y se muestran en el orden en que llegaron, sin perder
ninguna.

Las teclas de modo siguen funcionando mientras hay una tarjeta. La paleta no:
un lanzador sobre una decisión ocultaría lo que hay que responder.

---

## Seguir el hilo

Una respuesta larga mantiene la línea más reciente a la vista. Sube y deja de
seguir; la salida nueva no te arrastra hacia abajo, y un marcador dice que hay
más debajo. `End` vuelve a la cola en vivo, y enviar un mensaje nuevo hace lo
mismo.

---

## Sesiones

`Ctrl+K` → *Abrir una conversación anterior* lista lo que el núcleo ha
conservado, y abre una en el sitio. El mismo almacén sirve al navegador, así que
una conversación empezada aquí puede reabrirse allí.

`comodor --resume` reabre la más reciente al arrancar; `--resume ID` nombra una.

---

## Copiar texto

Selecciona con el ratón como tu terminal lo permita. Las opciones `--theme` y
`--ascii` se aplican a lo que imprimen los comandos — `setup`, `doctor`,
`help` — no a la interfaz, que dibuja desde sus propios tokens de diseño.

---

## Texto de derecha a izquierda

El persa, el árabe y las líneas mixtas se pasan a la terminal tal como se
escribieron, nunca invertidas por el programa. Lo bien que se conforma una línea
mixta es cosa de la terminal, y las que lo hacen bien lo hacen bien aquí.

---

## Ver también

- [tui-v2.md](../tui-v2.md) — cómo está construida la interfaz, y qué puede y
  qué no puede hacer aún
- [questions.md](questions.md) — los formularios que el agente te presenta
- [safety.md](safety.md) — qué pregunta, qué no, y por qué
- [computer.md](computer.md) — dejarle usar tu pantalla
