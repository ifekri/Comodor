# Costo

Cuánto cuesta una sesión, y cómo hacer que cueste menos sin empeorarla.

```
/cost
```

```
This session

- prompt tokens: 84,210
- output tokens: 3,180
- served from cache: 72,418 (86% of the prompt)
- cost: $0.1904
- saved by caching: $0.4126 (68%)
- context used: 87,390 / 1,000,000
- compactions: 0

Brain

- lessons: 812
- skills: 4
- episodes: 137 (83% succeeded)
```

---

## El caché del prompt, que es la mayor parte

Cada petición reenvía las partes que no cambian — el system prompt, los
esquemas de herramientas, la conversación hasta ahora. Los proveedores vuelven
a servir un prefijo idéntico byte a byte a cerca de una décima parte del
precio.

Comodor está construido en torno a esto, y viene activado por defecto:

```json
{ "agent": { "prompt_cache": true, "prompt_cache_ttl": "5m" } }
```

Medido en sesiones reales: **86% de los tokens de entrada servidos desde
caché**.

### Por qué nada dinámico va en el system prompt

El caché solo funciona sobre un prefijo idéntico byte a byte al de la última
vez. El system prompt *es* el prefijo. Cualquier cosa que cambia por turno —
las lecciones recordadas, la skill emparejada, la hora del día — lo invalida, y
pagas precio completo por todo, en cada turno.

Así que las lecciones recordadas viajan en el *turno*, como parte del mensaje
del usuario. Ese único cambio llevó la tasa medida de aciertos de caché de 72%
a 87%.

Si añades instrucciones permanentes propias, ponlas en
`agent.system_prompt_extra`, que es estable, en lugar de variarlas.

### El caché de una hora

```json
{ "agent": { "prompt_cache_ttl": "1h" } }
```

Cuesta alrededor de 25% más *escribir* una entrada y la conserva una hora en
lugar de cinco minutos. Vale la pena si vuelves a una sesión repetidamente; un
desperdicio para una sola ráfaga de trabajo.

---

## Techos

```json
{
  "agent": {
    "max_steps": 0,
    "max_seconds": 3600,
    "max_cost_usd": 2.0
  }
}
```

El que llegue primero detiene la tarea, y `0` significa sin límite. `stopped`
en `--json` dice cuál fue.

**No hay límite de pasos por defecto.** Veinticuatro pasos no son nada en una
base de código real — un refactoring de una docena de archivos se quedó sin
ellos a mitad de pensamiento — y un número de pasos no tiene relación con el
daño: diez pasos leyendo archivos cuestan casi nada. Los techos que sí se
corresponden con el daño son el tiempo y el dinero, y esos se quedan. Ponle un
número a `max_steps` si quieres una parada dura de vuelta.

Cuando uno de ellos detiene una tarea, el mensaje dice cómo pasarlo, y decir
"continue" sigue desde donde estaba.

### Cuando el límite no puede dispararse

**Un límite de gasto solo funciona para un modelo con tarifa publicada.**

La tabla de precios deja deliberadamente las tarifas sin fijar para los modelos
de los que no está segura — inventar un precio produce números equivocados, lo
cual es peor que ninguno. Para un modelo sin precio el medidor de costo lee
cero, así que `spent >= max_cost_usd` nunca es verdadero y el límite nunca se
dispara.

Comodor te lo dice en lugar de dejarte creer que estás protegido:

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Dicho al inicio de una sesión, y en `comodor doctor`:

```
  warn  spend limit    $2.00 per task cannot be enforced for gpt-4o
                       → No published rate is known for this model, so the
                         cost meter reads zero and the limit never fires.
                         The step and time limits still apply.
```

Para un modelo corriendo en tu propia máquina dice algo distinto, porque allí
no cuesta nada desde el principio.

---

## Lo que de verdad cuesta dinero

**Capturas de pantalla.** Unos 1,600 tokens visuales cada una con el
presupuesto por defecto — y otra vez eso en cada turno que permanecen en la
conversación. Comodor conserva las últimas dos y reemplaza el resto con una
línea que dice que hubo una. Sin eso, una tarea de escritorio de treinta pasos
carga cerca de cincuenta mil tokens de píxeles describiendo pantallas que ya
fueron cliqueadas.

```json
{ "agent":    { "keep_screenshots": 2 } }
{ "computer": { "screenshot_tokens": 1600 } }
```

No pongas `screenshot_tokens` demasiado bajo. Una imagen que el modelo no puede
leer es peor que ninguna imagen: adivina en lugar de preguntar. Ver
[Usar tu pantalla](computer.md#screenshots-and-what-they-cost).

**Salida grande de herramientas.** Acotada por `agent.max_tool_chars`. Lo que
no cabe se escribe en un archivo al que se le indica al modelo cómo leer, así
que paga solo si mira.

**Reflexión.** Una llamada al modelo al final de una tarea. Apúntala a un
modelo más barato:

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

O apágala. El carril gratis — correcciones, reglas, anuncios — sigue
funcionando de cualquier forma. [Cómo aprende](learning.md#the-two-lanes).

**El navegador, cuando mira.** `browse` devuelve texto por defecto y una
captura solo cuando se pide, porque la imagen de una página cuesta lo mismo
cada vez y no se puede recortar.

---

## Gastar nada

```bash
ollama pull qwen2.5-coder:14b
comodor setup       # choose Ollama
```

Todo en esta documentación funciona, sin costo, excepto donde dice lo
contrario. [Elegir un modelo](models.md#running-it-locally-for-nothing).

---

## Ver también

- [Elegir un modelo](models.md) — qué cobra cada proveedor
- [Configuración](configuration.md#agent--how-it-works) — cada perilla
