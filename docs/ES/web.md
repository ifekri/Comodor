# Desde un navegador

El mismo agente, en una pestaña del navegador. En esta máquina, o en un servidor
al que llegas por SSH.

```bash
comodor web
```

```
   ______                          __
  / ____/___  ____ ___  ____  ____/ /___  _____
 / /   / __ \/ __ `__ \/ __ \/ __  / __ \/ ___/
/ /___/ /_/ / / / / / / /_/ / /_/ / /_/ / /
\____/\____/_/ /_/ /_/\____/\__,_/\____/_/

  it learns the way you correct it   0.9.0  ·  claude-sonnet-5

  Comodor is at  http://127.0.0.1:8765/?token=EYhO9St_VTy95k4gHtJytb
  Working in     /home/you/projects/api-server

  Only this machine can reach it. Ctrl-C to stop.
```

Abre el enlace. El token está en él.

---

## Opciones

```bash
comodor web --port 9000
comodor web --no-browser            # do not open one for me
comodor web --token mytoken         # a fixed token
comodor web --host 0.0.0.0          # reachable from elsewhere — read below
```

---

## El token

Uno nuevo en cada ejecución, así que una URL de ayer no es una forma de entrar
hoy. Llega en la URL, se intercambia por una cookie, y cada petición posterior
queda autorizada por la cookie.

Para mantenerlo estable entre reinicios:

```bash
export COMODOR_WEB_TOKEN=something-long-and-random
```

Cualquiera con el token tiene una shell en esa máquina. Trátalo como tal.

---

## Enlazar a algo más que loopback

`--host 0.0.0.0` pone la interfaz en todas las interfaces de la máquina. **Este
puerto es una shell.** Comodor lo dice en lugar de asumir que lo querías:

```
  Listening on every address on this machine.
  Anyone who can reach this port can run commands as you.
```

Mejor, cuando el agente está en un servidor: déjalo en loopback y usa un túnel.

```bash
ssh -N -L 8765:127.0.0.1:8765 you@server
```

Luego abre `http://127.0.0.1:8765` localmente. El puerto nunca queda expuesto y
SSH hace la autenticación.

---

## Verlo usar una pantalla

Si el agente está manejando un escritorio, el fotograma que miró aparece en la
interfaz con un marcador donde actuó:

```
┌────────────────────────────────────────────┐
│                                            │
│   [ the screen the model saw ]      ✛      │
│                                            │
│   clicking Save                            │
└────────────────────────────────────────────┘
```

Ese es su propósito. El overlay en pantalla se dibuja en la máquina que se está
manejando, lo que no sirve de nada cuando esa máquina es un servidor o un
contenedor — el panel es cómo lo ves desde otro lugar.

La imagen se obtiene una vez por fotograma desde `/api/screen`, no se lleva en
el flujo de eventos: una captura pesa cerca de un megabyte, y un navegador que
relea el registro de eventos descargaría cada fotograma que jamás hubiera
visto.

[Usar tu pantalla](computer.md).

---

## Lo que no hará

**Arrancar sin un proveedor.** Puede cambiar entre proveedores que ya estén
configurados, pero no hay ningún lugar donde escribir una clave, y una pestaña
del navegador sería un mal lugar para ello. En lugar de servir una URL que
falla en la primera tarea, dice qué falta y se detiene:

```
Comodor has no provider configured, and the browser interface has no way to
add one.

  In Docker, pass a key in as an environment variable:
    -e ANTHROPIC_API_KEY=...    -e OPENAI_API_KEY=...
  or mount a config file at ~/.comodor/config.json.
  Anywhere with a terminal, `comodor setup` asks a few questions.
```

En una terminal hace las preguntas de configuración en su lugar. En un
contenedor siempre imprime el mensaje — un contenedor tiene una terminal haya
o no alguien conectado, y uno desacoplado esperaría para siempre una pregunta
que nadie puede responder.

**Ampliar lo que el agente puede tocar.** La autoaprobación para escrituras y
para comandos se muestra en Admin y no puede cambiarse ahí. Los avisos de
permiso ya ofrecen esa elección por acción, delante de la persona que vivirá
con ella; una página alcanzable por cualquiera que tenga el enlace es el lugar
equivocado para convertirla en política permanente. Cámbialo donde se inició
Comodor — véase [Seguridad](safety.md).

---

## Lo que hay en la pantalla

**La conversación**, en streaming a medida que llega, con el código en bloques
conservado como código y cada llamada a herramienta como una fila que puedes
abrir para ver lo que realmente hizo.

**La lista de chats**, a la izquierda. Cada conversación se escribe en
`~/.comodor/sessions` — la misma carpeta que usa la terminal, así que un chat
comenzado en el prompt se puede abrir en el navegador y al revés. La búsqueda
mira dentro de ellos, no solo en sus títulos.

**Admin**, la segunda pestaña, que es la respuesta a "qué está a punto de hacer
esta cosa con mi máquina":

| | |
|---|---|
| Modelo | qué proveedor y modelo responde, y cambiar entre los que tienes claves |
| Cómo funciona | el modo, si sigue por su cuenta, y los cuatro techos — contexto, pasos, tiempo, gasto |
| Permisos | lo que puede hacer sin preguntar, lo que preguntará, y lo que se ha concedido esta sesión |
| Lo que ha aprendido | reglas, lecciones, habilidades, tareas, y cuántas tuvieron éxito |
| Herramientas | cada herramienta que puede alcanzar, con código de color por riesgo, más tus habilidades y cualquier servidor MCP |
| Esta máquina | versión, Python, y dónde viven los ajustes, los chats y el cerebro |

**La franja de estado** en la parte inferior: si la página está conectada, la
carpeta de trabajo, cuán lleno está el contexto, lo que ha costado la sesión, y
cuántas reglas aprendidas están en vigor.

**El panel de pantalla**, cuando el agente maneja una — el último fotograma que
miró, con un marcador donde está a punto de hacer clic. Véase
[Usar tu pantalla](computer.md).

---

## Teclado

| | |
|---|---|
| `Enter` | enviar |
| `Shift`+`Enter` | nueva línea |
| `Esc` | detener la tarea actual, o cerrar la barra lateral |
| `Ctrl`/`⌘`+`K` | buscar en los chats |
| `Ctrl`/`⌘`+`B` | mostrar u ocultar la barra lateral |
| `/` | saltar al cuadro de mensaje |

---

## En un teléfono

La misma página. Por debajo de 900 píxeles la lista de chats se convierte en un
cajón sobre la conversación en lugar de una columna al lado, porque 292 píxeles
de barra lateral en una pantalla de 390 píxeles no dejan nada lo bastante ancho
para leer código. Toca fuera de él, pulsa `Esc`, o usa el botón de cerrar para
guardarlo.

Llega a él desde tu teléfono como llegarías a cualquier otra cosa de tu
máquina — un túnel SSH, no una exposición pública. [Enlazar a algo más que
loopback](#binding-to-more-than-loopback) explica por qué.

---

## Escribir en cualquier idioma

Escribe en persa, árabe o hebreo y el cuadro de mensaje se da la vuelta mientras
escribes; las respuestas en esos idiomas se muestran de derecha a izquierda
cuando llegan. No hay nada configurado ni ajuste de idioma: cada mensaje se
juzga por sí solo, así que una conversación que se mueve entre idiomas se mueve
con ellos.

El juicio es por conteo más que por primera letra, lo que hace que los dos
casos incómodos salgan bien — una frase en persa que abre con un nombre de
paquete sigue siendo persa, y una frase en inglés que cita una palabra persa
sigue siendo inglés. El código, las rutas y las URLs se muestran de izquierda a
derecha dentro de un párrafo de derecha a izquierda, que es donde pertenecen.

El texto en escritura árabe se muestra en Vazirmatn, que viaja dentro del
paquete en lugar de descargarse de un servidor de fuentes: esto tiene que
funcionar en una máquina que no puede alcanzar internet. Se aplica a los
caracteres de escritura árabe y a nada más, así que una línea que mezcla persa
con un identificador en inglés recibe la tipografía correcta para cada uno.

---

## Claro y oscuro

Sigue al sistema por defecto; el sol en la esquina superior derecha lo cambia y
la elección se recuerda en ese navegador.

---

## En Docker

```bash
docker compose up
```

y abre la dirección que imprime. [Docker](docker.md).

---

## Véase también

- [Docker](docker.md) — lo mismo en un contenedor
- [La interfaz](interface.md) — la versión de terminal
- [Seguridad](safety.md) — los permisos que reporta la pestaña Admin
- [Usar tu pantalla](computer.md) — lo que te muestra el panel de fotogramas
