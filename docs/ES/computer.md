# Usar tu pantalla

Comodor puede manejar la máquina como lo hace una persona — mirar la pantalla,
mover el ratón, hacer clic y escribir — en cualquier aplicación, no solo en un
navegador.

Esto es lo más poderoso que puede hacer y lo más peligroso. Lee el
[modelo de permisos](#permission) antes de activarlo.

> **Solo Windows por ahora.** Los backends de macOS y Linux no están escritos.
> En esas plataformas la herramienta no se ofrece en absoluto, en lugar de
> ofrecerse y fallar — véase [Por qué no está](#why-it-is-not-there).

---

## Cómo se ve

Lo ves suceder. Antes de que el puntero se mueva, aparece un halo donde está a
punto de hacer clic:

```
   ┌─────────────────────────────────────────┐
   │   Comodor · 14m 32s left, anywhere      │   ← the panel, top centre
   │   move the mouse to a corner to stop    │
   └─────────────────────────────────────────┘


               ╭──────────╮
               │   Save   │      ◎  ← the halo, drawn before it moves
               ╰──────────╯
                               clicking (842, 517)
```

El puntero luego viaja hasta ahí durante alrededor de un tercio de segundo en
lugar de teletransportarse, y una onda marca dónde aterrizó el clic.

**La pausa no es decoración.** Es el momento en el que aún puedes detenerlo.
Un cursor que salta y hace clic en el mismo instante no te da nada.

Si el agente se está ejecutando en otro lugar — un servidor, un contenedor —
lo mismo aparece en la [interfaz web](web.md): el fotograma que miró, con un
marcador donde actuó.

---

## Activarlo

Dos pasos, a propósito. Ninguno sucede por sí solo.

**1. Permitir que la herramienta exista**, en `~/.comodor/config.json`:

```json
{
  "computer": {
    "enabled": true
  }
}
```

Mientras esto no esté establecido, al modelo no se le ofrece la herramienta en
absoluto. No está en la lista de herramientas, así que no puede pedirla ni
pueden convencerlo de usarla.

**2. Permitirle actuar**, en el momento en que importa:

```
/computer 15m              fifteen minutes, anywhere on screen
/computer 1h this app      one hour, only while the current window is in front
/computer                  how things stand
/computer stop             end it now
```

O deja que el modelo pregunte. La primera vez que necesite la pantalla verás
esto:

```
  Let Comodor use your screen, mouse and keyboard?

  It will be able to see everything on your screen and to click and type
  anywhere, in any application.

  Screenshots go to the model. Whatever is on screen goes with them - open
  messages, tokens, anything visible. Redaction works on text and cannot
  read pixels.

  It will never touch a password manager, a window asking for a password,
  a locked screen, or Comodor's own window.

  To stop it at any moment: move your mouse into a corner of the screen.

  [15 minutes]  [15 minutes, this app only]  [1 hour]  [no]
```

---

## Detenerlo

**Mueve el ratón a una esquina de la pantalla.** Eso es todo.

Funciona mientras el agente tiene el control del puntero, lo que ningún atajo
de teclado puede prometer — el agente puede estar escribiendo en una ventana
en ese momento. También es lo que la gente realmente hace cuando su pantalla
empieza a moverse por sí sola.

Tocar una esquina termina la ejecución y quita el permiso. Pedirlo de nuevo es
una concesión nueva.

El agente aún puede hacer clic en una esquina por sí mismo — el botón Inicio,
un cuadro de cerrar. Recuerda dónde dejó el puntero, así que solo un puntero
que se movió a un lugar donde nadie lo puso cuenta como tú.

Otras formas de detenerlo, cuando tus manos están en el teclado:

```
/computer stop       ends the permission
Esc                  stops the current task
```

---

## Permiso

Una concesión son tres cosas a la vez, y ninguna de ellas es una casilla.

| | |
|---|---|
| **Un alcance** | todas partes, o una aplicación por el título de su ventana |
| **Un reloj** | expira, y el tiempo restante está en pantalla todo el tiempo |
| **Una salida** | la esquina, que funciona mientras el puntero está siendo manejado |

Se comprueba **antes de cada acción**, no una sola vez al principio. Una
ventana que aparece a mitad de una ejecución concedida es atrapada.

### Rechazado sea lo que hayas permitido

- Un gestor de contraseñas — 1Password, Bitwarden, KeePass, LastPass, Dashlane,
  NordPass y los almacenes de credenciales del sistema.
- Cualquier ventana cuyo título mencione una contraseña, una frase de
  contraseña, 2FA o un código de un solo uso.
- Una aplicación de billetera o de billetera de hardware — MetaMask, Ledger
  Live, Trezor.
- Cualquier cosa que parezca banca en línea.
- Una pantalla bloqueada.
- **La propia ventana de Comodor.** Un agente que hace clic en la terminal que
  lo maneja escribe en su propio prompt.

Añade las tuyas:

```json
{
  "computer": {
    "never": ["Internal HR", "Payroll"]
  }
}
```

Se compara en cualquier parte del título de la ventana, sin distinguir
mayúsculas.

### Lo que una concesión no es

Nunca se **escribe en tu archivo de configuración**. Cerrar Comodor la termina.
No existe un "permitir siempre" para la pantalla y esa omisión es deliberada.

Un repositorio no puede activar esto. `computer` no está en la lista de cosas
que el `.comodor/config.json` de un proyecto puede establecer, y un repositorio
que lo intenta es rechazado en voz alta. Véase
[Seguridad](safety.md#what-a-repository-may-set).

---

## Lo que va al modelo

**Capturas de pantalla, y todo lo visible en ellas.** Merece la pena detenerse
en esto.

Si un gestor de contraseñas está abierto detrás de tu editor, si una ventana de
chat tiene un mensaje, si una clave de API está impresa en una terminal — eso
está en la imagen, y la imagen va al proveedor que hayas configurado.

La anonimización de Comodor funciona sobre texto y no puede leer píxeles. No
hay forma de evitarlo: la función es "dejar que el modelo vea tu pantalla".

Consejos prácticos:

- Cierra lo que no pegarías en una ventana de chat.
- Usa `/computer 1h this app` para que solo actúe mientras una ventana esté al
  frente — aunque todavía *ve* lo que haya en la captura.
- Prefiere la [herramienta de navegador](browser.md) cuando el trabajo es una
  página web. Devuelve texto, no píxeles, y cuesta una fracción de lo que
  cuesta esto.

---

## Lo que puede hacer

Diecisiete acciones, detrás de una herramienta. Los nombres son de Anthropic,
porque los modelos se entrenan con ese vocabulario.

### Mirar

| Acción | Lo que hace |
|---|---|
| `screenshot` | El monitor activo. `whole_desktop: true` para todos los monitores. |
| `zoom` | Una región, a resolución completa — así lee el texto pequeño |
| `cursor_position` | Dónde está el puntero |

### Apuntar

| Acción | |
|---|---|
| `mouse_move` | Moverse a algún lugar sin hacer clic |
| `left_click` `right_click` `middle_click` | Con teclas modificadoras opcionales |
| `double_click` `triple_click` | El triple selecciona una línea en la mayoría de los editores |
| `left_click_drag` | De un punto a otro |
| `left_mouse_down` `left_mouse_up` | Para cualquier cosa que un arrastre no pueda expresar |
| `scroll` | Arriba, abajo, izquierda, derecha, por clics de rueda |

### Escribir

| Acción | |
|---|---|
| `type` | Texto, por carácter — correcto en cualquier distribución de teclado |
| `key` | `Return`, `ctrl+s`, `alt+Tab`, `F5`, `Page_Down`, … |
| `hold_key` | Mantener una tecla o combinación durante un tiempo |
| `wait` | Dejar que algo en pantalla termine |

El texto se escribe **por carácter, no por posición de tecla**. Pulsar la tecla
donde está `@` en un teclado estadounidense produce otra cosa en uno francés;
nombrar el carácter produce `@` en todas partes, incluso en distribuciones sin
tecla para él.

---

## Escrito no es lo mismo que llegado

Las aplicaciones reescriben lo que se escribe en ellas.

El Bloc de notas de Windows 11 tiene el autocorrector activado por defecto.
Escribir `ümlaut` en él produce `umlaut`. Nada se perdió en el camino — cada
uno de los treinta caracteres acentuados y no latinos llega intacto cuando se
envía solo, y `üxqzv` en la misma posición queda intacto. La aplicación lo
cambió.

Comodor lo dice en cada `type`:

```
Typed 29 characters. Applications can autocorrect or reformat what is
typed into them - take a screenshot if what arrived matters.
```

Si el texto exacto importa — un campo de contraseña, un valor de configuración,
un mensaje de commit — haz que mire de nuevo.

---

## Capturas de pantalla y lo que cuestan

Una captura de pantalla es lo más caro que esta herramienta envía.

El tamaño se ajusta a lo que el modelo aceptará: un borde largo de 2,576
píxeles y un presupuesto de tokens. El presupuesto por defecto es de 1,600
tokens visuales, lo que da una imagen legible en cada pantalla probada.

| Tu pantalla | Con el presupuesto por defecto | Costo |
|---|---|---|
| 1920 × 1080 | 1480 × 833 | ~1,590 tokens |
| 3840 × 1080 | 2068 × 582 | ~1,554 tokens |
| 3840 × 2160 | 1064 × 599 | ~836 tokens |

**No pongas esto demasiado bajo.** El consejo común de "capturar a 1280 de
ancho" asume una pantalla 16:9. En una pantalla de 3840 × 1080 significa una
reducción de tres veces, y a ese tamaño al modelo se le entrega texto que no
puede leer — así que adivina en lugar de preguntar. Medido en esa pantalla: las
etiquetas de los menús ilegibles a 1280 de ancho, perfectamente claras a 2068.

```json
{
  "computer": {
    "screenshot_tokens": 1600
  }
}
```

700 es barato y sigue siendo legible en una laptop. 4784 es lo máximo que el
modelo acepta.

**Las capturas antiguas se descartan automáticamente.** Solo las últimas dos
permanecen en la conversación; el resto se convierten en una línea que dice que
hubo una. Sin esto, una tarea de treinta pasos cargaría cerca de cincuenta mil
tokens de píxeles, casi todos describiendo una pantalla que desde entonces ha
sido clicada. Cámbialo con `agent.keep_screenshots` si tienes una razón.

---

## Todas las opciones

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

| Opción | Por defecto | |
|---|---|---|
| `enabled` | `false` | Si al modelo se le ofrece la herramienta en absoluto |
| `screenshot_tokens` | `1600` | Legibilidad frente a precio. Máximo 4784 |
| `grant_seconds` | `900` | Cuánto dura una concesión simple |
| `travel_seconds` | `0.32` | Cuánto tarda el puntero en viajar. `0` funcionaría y sería insoportable de ver |
| `overlay` | `true` | Dibujar el halo y el panel. Desactivado para una máquina donde nadie está sentado |
| `never` | `[]` | Títulos de ventana adicionales que nunca tocar |

---

## Por qué no está

Si `computer` no está entre las herramientas, una de estas es cierta:

**La plataforma no tiene backend.** Solo Windows por ahora. La herramienta no
se ofrece en lugar de ofrecerse y fallar cada vez — una herramienta que el
modelo puede ver y nunca usar invita a una llamada desperdiciada en cada turno.

**Está apagada.** `computer.enabled` por defecto es `false`.

Pregúntalo directamente:

```
/computer
```

```
no screen control: it is switched off. Set computer.enabled in your config.
```

---

## Bajo el capó

Para los curiosos, y para quien quiera portarlo a otra plataforma.

**Sin dependencias.** La captura de pantalla es GDI a través de `ctypes`; el
reescalado es `StretchBlt` en modo `HALFTONE`, que promedia en lugar de
descartar píxeles — la diferencia entre texto pequeño legible y motas. La
codificación PNG es `zlib` y `struct`, unas cuarenta líneas. La entrada es
`SendInput`.

**La conciencia de DPI se establece antes de que nada lea una métrica de
pantalla.** En una pantalla escalada al 125% — el valor por defecto en la
mayoría de las laptops Windows — a un proceso que no se ha declarado consciente
de DPI se le dice que la pantalla es más pequeña de lo que es, y cada clic cae
corto por exactamente el factor de escala. La causa es invisible; parece que el
modelo no puede apuntar.

**Las coordenadas se convierten en un solo lugar.** El modelo responde en los
píxeles de la imagen que se le mostró, que es un recorte reducido de una
pantalla que comienza en un origen del que nunca se le habló. `Shot.to_screen`
es el único código que sabe esto, porque una segunda copia es una segunda
oportunidad de equivocarse.

**El overlay es una ventana que deja pasar los clics y nunca toma el foco.**
`WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`, de modo que el puntero
alcanza lo que está debajo y el teclado se queda donde estaba. Se ejecuta en su
propio hilo con su propio bucle de eventos, y un fallo al dibujar es una imagen
faltante, no una función faltante — el agente funciona sin ninguna pantalla.

Portarlo a macOS o Linux significa escribir un archivo junto a `win32.py` con
la misma docena de funciones. Nada por encima de esa capa importa `ctypes`.

---

## Véase también

- [Seguridad y permisos](safety.md) — el resto del modelo de permisos
- [Un navegador de verdad](browser.md) — más barato, cuando el trabajo es una página web
- [Desde un navegador](web.md) — verlo trabajar desde otro lugar
- [Costo](cost.md) — lo que cuesta realmente una sesión larga de escritorio
