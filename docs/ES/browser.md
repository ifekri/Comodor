# Un navegador de verdad

No es un descargador de páginas. Es un navegador realmente instalado — ejecuta
JavaScript, conserva cookies y puede iniciar sesión.

---

## Qué usa

Chrome, Chromium, Edge o Brave, el que esté en la máquina. **No se descarga
nada.** Abre uno en un perfil propio que no ha iniciado sesión en nada, y lo
cierra cuando termina la sesión.

Si no hay ninguno instalado, `browse` recurre a un navegador de texto que sigue
respondiendo a la mayoría de las preguntas sobre una página. Ambos se llaman
`browse`, porque elegir entre dos cosas llamadas "browser" es un turno que el
modelo no debería tener que gastar.

---

## Qué devuelve

No una captura de pantalla. El título, el texto legible y una **lista numerada
de los controles realmente en pantalla**:

```
  Sign in — Example
  ─────────────────────────────────────────────
  Sign in to your account. New here? Create one.

  [1]  textbox   Email
  [2]  textbox   Password
  [3]  button    Sign in
  [4]  link      Forgot your password?
```

El modelo actúa sobre uno por su número. Esa lista se filtra a lo que es
visible, tiene nombre, está en pantalla y no es duplicado — lo cual es mucho más
pequeño que el árbol de accesibilidad y, medido, más pequeño que una captura de
la misma página.

Una captura solo cuando la pregunta es visual — diseño, estilos, un gráfico —
porque una imagen cuesta lo mismo cada vez y no se puede recortar.

---

## Verbos

| | |
|---|---|
| `open` | ir a una URL |
| `click` | un control, por su número |
| `type` | en un campo, por su número |
| `scroll` | hacia arriba o hacia abajo |
| `back` | la página anterior |
| `read` | la página de nuevo, después de que algo cambie |
| `look` | una captura, cuando la pregunta va sobre el aspecto |
| `script` | ejecutar JavaScript y recuperar su valor |

---

## Verlo trabajar

```json
{ "browser": { "headless": false } }
```

Una ventana visible, para que puedas ver lo que hace.

> Esta opción antes se ignoraba — `browser` no estaba registrado como sección
> de configuración, así que cada opción de `browser` en silencio no hacía nada.
> Corregido en 0.9.0.

---

## Usar una sesión en la que ya iniciaste sesión

En lugar de entregar tu perfil, abre tu propio navegador con un puerto de
DevTools y apunta Comodor hacia él:

```bash
chrome --remote-debugging-port=9222
```

```json
{ "browser": { "port": 9222 } }
```

Se conecta a ese navegador y usa las pestañas y cookies que ya están ahí.
Cierra el puerto al terminar — cualquier cosa en tu máquina puede usarlo.

---

## Todas las opciones

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

| | |
|---|---|
| `executable` | un navegador concreto. Vacío significa buscar en los lugares habituales |
| `headless` | invisible por defecto, para que no robe el foco |
| `width`, `height` | la ventana |
| `port` | conectarse a un navegador que abriste tú, en lugar de lanzar uno |

Un repositorio no puede establecer ninguna de estas opciones —
`browser.executable` nombra un binario que lanzar.
[Seguridad](safety.md#what-a-repository-may-set).

---

## ¿`browse` o `web_fetch`?

| | |
|---|---|
| `web_fetch` | la página es un documento. La reduce a texto. Barato |
| `browse` | la página es una aplicación. Necesita JavaScript, inicio de sesión o un clic |

Al modelo se le indica que prefiera `web_fetch` y que recurra a `browse`
cuando aquél no baste.

---

## En un contenedor

La imagen de Docker trae Chromium y las fuentes para renderizar con él. El
sandbox propio de Chromium no puede iniciarse dentro de un contenedor cuyo
perfil seccomp bloquea los espacios de nombres de usuario, así que Comodor lo
detecta y reintenta sin el sandbox interior — conservando el aislamiento del
contenedor, que es la frontera real. [Docker](docker.md).

---

## Bajo el capó

El Chrome DevTools Protocol sobre un WebSocket hecho a mano. Sin dependencias:
el encuadre de RFC 6455 son unas cien líneas y forma parte del paquete, igual
que el cliente HTTP y el lector de SSE.

---

## Véase también

- [Lo que el agente puede hacer](tools.md) — las demás herramientas
- [Usar tu pantalla](computer.md) — cuando el trabajo no es una página web
- [Costo](cost.md) — por qué devuelve texto en lugar de imágenes
