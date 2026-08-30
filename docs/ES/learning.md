# Cómo aprende

La mayoría de los agentes olvida en el momento en que una sesión termina. Este
observa lo que cambias de su salida y lo conserva.

---

## La idea

El elogio es barato y las correcciones son caras, así que las correcciones son
de donde aprende.

Cuando editas un archivo que escribió, o le dices sin rodeos que estaba
equivocado, eso se convierte en una **lección**: una regla corta con una
confianza que sube cada vez que se cumple y decae cuando queda sin usar. Las
lecciones se recuerdan cuando la situación parece similar, y se inyectan en ese
turno — nunca en el system prompt, lo que costaría la caché del prompt.

Nada sale de tu máquina. El cerebro es un archivo SQLite bajo tu directorio de
configuración.

---

## Los dos carriles

### Reflejo — gratis, inmediato, siempre activo

Ninguna llamada al modelo, ningún token, ningún retraso.

- **Correcciones.** Editas `"` a `'` en un archivo que escribió. Eso es un
  diff, y un diff es un hecho.
- **Reglas.** Lee tu código existente una vez, al principio, y saca
  convenciones de él — la indentación, el estilo de comillas, cómo se nombran
  los tests.
- **Anuncios.** Cuando se aplica una regla, lo dice, en una línea. Una regla
  que no puedes ver es una regla que no puedes corregir.
- **Prefetch.** La recuperación empieza mientras aún estás escribiendo.

Este carril está activo incluso cuando la reflexión está apagada, porque no
cuesta nada.

### Reflexión — una llamada al modelo, tras una tarea

Al final de una tarea mira lo que sucedió y anota lo que debería recordar. Esta
cuesta una llamada. Usa un modelo más barato para ella si quieres:

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

O apágala, conservando el Reflejo:

```json
{ "learning": { "reflect": false } }
```

---

## Enseñarle, deliberadamente

| | |
|---|---|
| `/good` | esa respuesta fue correcta |
| `/bad` | esa respuesta fue incorrecta |
| `/teach we use pytest, never unittest` | recuerda esto |

`/good` y `/bad` toman una tecla y son lo más barato que puedes hacer por él.

Rechazar un aviso de permiso también le enseña. Un rechazo es la señal de
preferencia más clara que la interfaz recoge, y se trata como tal.

---

## Ver lo que sabe

```
/memory
```

Una lista con búsqueda — cada lección con qué la dispara, qué dice, su tipo y
su confianza actual:

```
┌─  Memory (23)  ────────────────────────────────────────────────────┐
│ ›  #41 writing Python strings                                      │
│      Use single quotes for string literals.  [style 91%]           │
│    #38 adding a test                                               │
│      Tests go in tests/, mirroring the src layout.  [layout 84%]   │
│    #29 adding a dependency                                         │
│      Ask before adding one; this project has exactly one.  [78%]   │
│    #12 parsing empty input                                         │
│      Raise, do not return an empty list.  [behaviour 62%]          │
└────────────────────────────────────────────────────────────────────┘
  ↑↓ move   enter open   type filter   esc close
```

`/memory <text>` busca. Abrir una te deja fijarla, para que deje de decaer, o
eliminarla si estaba mal.

```
/rules
```

Las reglas de la casa que sacó de tu código en lugar de que tú se las dijeras.

---

## Ver si funciona

```
/progress
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

**La línea de arriba es la que importa.** Si las correcciones por tarea no
bajan, el aprendizaje no funciona — y el panel encabeza con eso de cualquier
modo, en lugar de enterrarlo bajo actividad. Todo lo demás en la tabla es
esfuerzo; esa es resultado.

---

## La recuperación, y por qué no está en el system prompt

Las lecciones recordadas viajan en el turno, como parte del mensaje del
usuario, no en el system prompt.

Esto es una decisión de costo. El caching del prompt solo funciona en un
prefijo idéntico byte a byte, y el system prompt es el prefijo. Poner ahí algo
dependiente de la consulta invalida la caché en cada turno. Mover la
recuperación al turno llevó las tasas medidas de acierto de caché de 72% a 87%.
Véase [Costo](cost.md).

---

## Palabras que aprende de ti

También aprende cuáles de *tus* palabras van juntas, de tus propias tareas
terminadas — que "the parser" y "tokenise" pertenecen a la misma esquina de tu
codebase. Esto no cuesta tokens ni llamada al modelo; es contar.

Eso es lo que permite que una lección registrada sobre "the tokeniser" aflore
cuando preguntas por "the lexer".

```json
{ "learning": { "associative": true } }
```

---

## Alcance

```json
{ "learning": { "share_scope": "project" } }
```

`project` mantiene las lecciones en el repositorio donde se aprendieron — el
valor por defecto correcto, ya que una convención en un codebase está mal en
otro. `global` las comparte en todas partes.

---

## Olvidar

Una lección que queda sin usar decae. `half_life_days` (45 por defecto) pone
qué tan rápido, y `min_confidence` (0.15) es el suelo por debajo del cual deja
de recordarse.

Esto importa: un codebase cambia de opinión, y un agente que sostiene una
convención de hace dos años con total confianza es peor que uno que la olvidó.

---

## Apagarlo

```json
{ "learning": { "enabled": false } }
```

Todo sigue funcionando. Simplemente empieza cada sesión como un extraño.

---

## Dónde vive

```
~/.comodor/brain.db
```

SQLite. Tuyo. `comodor uninstall` lo elimina y dice cuánto era.

---

## Véase también

- [Habilidades](skills.md) — procedimientos que escribes tú, en lugar de lecciones que infiere él
- [Costo](cost.md) — por qué la recuperación va en el turno y no en el prefijo
