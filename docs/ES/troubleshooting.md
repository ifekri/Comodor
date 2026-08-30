# Solución de problemas

## Empieza aquí

```bash
comodor doctor
```

Comprueba el archivo de configuración y sus permisos, el proveedor, el modelo,
el límite de gasto, el cerebro, el índice de búsqueda, tus habilidades, los
archivos sobrantes, los servidores MCP, y si hay un lanzamiento más nuevo.

```bash
comodor doctor --fix
```

repara lo que es reparable. Nunca cambia nada que no haya reportado primero.

---

## No arranca

**`comodor: command not found`, justo después de instalar** — el instalador lo
puso en tu `PATH`, pero un proceso hijo no puede cambiar el entorno del shell
que lo inició. Toda terminal *nueva* ya funciona. Para la que estás, el
instalador imprimió la línea que hay que pegar; o:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`comodor: command not found`, en una terminal nueva** — ese es un problema
real. `python -m comodor` confirma si está instalado en absoluto, y
`ls ~/.local/bin/comodor` donde debería estar.

**`No provider is configured`** — ejecuta `comodor setup`, o exporta una clave:

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

**Python demasiado viejo.** Comodor necesita 3.11 o más nuevo. Comprueba con
`python --version`.

---

## Una opción parece no hacer nada

Comodor te avisa cuando rechaza una:

```
config: agent.max_steps must be a whole number; keeping 0
config: this project cannot set safety, computer — only your own can
```

Si no se dice nada y aún no tiene efecto, comprueba qué capa gana:

```
/settings          # what is actually loaded
```

```bash
comodor doctor     # the same, plus where every file is
```

Un `--model` en la línea de comandos le gana a tu archivo de configuración, y
una clave en tu entorno le gana a una en el archivo. Eso es deliberado —
[Configuración](configuration.md#what-wins).

---

## `/save` no guardó lo que esperaba

A propósito. Escribe **solo lo que elegiste** — no los ajustes de un
repositorio, no una clave que guardas en tu entorno, no una bandera que pasaste
para una ejecución.

Para volver tuyo un ajuste de un repositorio, establécelo tú primero
(`/model x`) y luego guarda.

---

## Las peticiones fallan

**`401` o `invalid api key`** — la clave está mal, expiró, o pertenece a otro
proveedor. `comodor doctor` muestra qué proveedor está activo.

**`404 model not found`** — ese proveedor no sirve ese id de modelo. `/model`
lista lo que realmente ofrece.

**Tiempos de espera agotados.** Un modelo local en una máquina modesta puede
genuinamente tardar minutos. Sube `providers.<name>.timeout`.

**Se detiene antes de tiempo.** Mira `stopped`. `max_steps` y `budget` son
techos haciendo su trabajo, no fallos. Súbelos para una ejecución con
`--max-steps`, o permanentemente bajo `agent`.

---

## El límite de gasto no funciona

Probablemente no puede ser, y Comodor lo dice. Véase
[Costo — cuándo el límite no puede dispararse](cost.md#when-the-limit-cannot-fire).

---

## La herramienta de navegador

**"no browser found"** — instala Chrome, Chromium, Edge o Brave, o establece
`browser.executable`. Sin uno, `browse` recurre a un navegador de texto que
sigue respondiendo la mayoría de las preguntas sobre una página.

**Quiero verlo trabajar** — `browser.headless: false`.

**Necesita un inicio de sesión que ya tengo** — abre tu propio navegador con un
puerto de DevTools y establece `browser.port`, para que use esa sesión en lugar
de que le entreguen tu perfil.

---

## La herramienta de pantalla

**No está en la lista de herramientas.** O esta plataforma no tiene backend —
solo Windows por ahora — o `computer.enabled` es false. Pregúntale:

```
/computer
```

**Los clics caen en el lugar equivocado.** Esto no debería suceder: la
conciencia de DPI se establece antes de leer cualquier métrica de pantalla. Si
sucede, por favor repórtalo con tu escala de pantalla y resolución. Ese es un
bug real.

**Se detuvo por sí solo.** El ratón fue a una esquina de la pantalla, lo que
termina la concesión a propósito. `/computer 15m` inicia otra.

**El texto que llegó no es el texto que escribió.** La aplicación lo reescribió
— el Bloc de notas de Windows 11 autocorrige mientras escribes. No es un bug de
Comodor, y lo dice en cada `type`.
[Más](computer.md#typed-is-not-the-same-as-arrived).

---

## La interfaz web

**Se niega a arrancar.** No hay proveedor configurado, y la interfaz del
navegador no tiene forma de añadir uno. El mensaje nombra qué establecer.

**"Unauthorised".** Un token nuevo se genera en cada ejecución — usa la URL de
*esta* ejecución, o establece `COMODOR_WEB_TOKEN` para mantenerlo estable.

**En Docker, nada en `localhost:8765`.** Comprueba que el puerto esté publicado
como `127.0.0.1:8765:8765`. [Docker](docker.md).

---

## Algo va lento

**La primera petición de una sesión.** Nada está en caché todavía; la segunda
es mucho más rápida.

**La reflexión tras cada tarea.** Una llamada al modelo. Usa
`learning.reflect_model` para una más barata, o `reflect: false`.

**Las capturas de pantalla.** Alrededor de 80 ms en tomarse, más el modelo
mirándolas. Baja `computer.screenshot_tokens` si aún puedes leer el resultado.

---

## Empezar de nuevo

```bash
comodor uninstall --dry-run     # what would go, named
comodor uninstall               # do it
```

O solo el cerebro, conservando tus ajustes:

```bash
rm ~/.comodor/brain.db
```

---

## Reportar un problema

Incluye:

```bash
comodor --version
comodor doctor
```

`doctor` enmascara tu clave. Aun así, por favor lee la salida antes de pegarla.

- Issues: <https://github.com/ifekri/Comodor/issues>
- Algo sensible: [SECURITY.md](../SECURITY.md)
