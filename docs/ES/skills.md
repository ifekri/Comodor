# Skills

Una skill es un procedimiento escrito que el agente sigue cuando el trabajo lo
pide.

No un prompt que pegas cada vez — un archivo que él mismo carga cuando la
situación encaja.

---

## Conseguir algunas

`comodor setup` ofrece la biblioteca una vez, al final. Muévete con las flechas,
pulsa **espacio** para marcar cuantas quieras, y **enter** instala todas. Nada
está marcado al principio, y enter sin nada marcado no toma ninguna — nunca te
dan algo que no pediste.

```
┌─ Skills ──────────────────────────────────────────────────┐
│    ☑ review        Review a change before it is committed │
│ ›  ☐ commit-style  Match the commit messages already here │
│    ☑ python-tests  Write tests the way this project does  │
└───────────────────────────────────── 2 selected ──────────┘
  ↑↓ move   space select   enter install 2   tab more   esc cancel
```

**Una línea por skill**, así toda la lista cabe en una pantalla por más que
crezca la biblioteca, y la ventana sigue a la flecha en lugar de quedarse
atrás. Algunas de estas descripciones llegan a un párrafo — **tab** abre la
completa de lo que esté señalando la flecha, en el mismo cuadro, y tab otra
vez la cierra.

Escribir filtra la lista, lo que es más rápido que desplazarse en cuanto hay
más de unas pocas. Las marcas se conservan mientras filtras, así que puedes
acortar la lista, marcar algo, limpiar el filtro y marcar otra cosa.

Cuando no hay una terminal que pueda controlar — una tubería, un script,
`curl | sh` — la misma pregunta se hace como una lista numerada, una página a
la vez:

| | |
|---|---|
| `1,3` o `1 3` | tomar estos |
| `m` / `b` | página siguiente, página anterior |
| `/word` | mostrar solo lo que coincide |
| `?7` | leer toda la descripción del número 7 |
| enter | hecho |

Los números son absolutos: el número 92 es la skill noventa y dos sin importar
qué página o búsqueda estés viendo, así que un número que anotaste sigue siendo
el número que tecleas.

---

## Usar una

```bash
comodor skills browse            # what is available
comodor skills add review        # install it
comodor skills list              # what you have
```

```
/skills                          # the same, in the interface
```

Desde entonces, cuando pides algo que una skill cubre, se carga y el agente la
sigue. Se te avisa cuando pasa:

```
  ▸ skill: review — Review a change for correctness before it is committed
```

Una skill que no ves aplicarse es una skill que no puedes corregir.

---

## Escribir una

Una carpeta con un `SKILL.md` dentro:

```
~/.comodor/skills/our-tests/SKILL.md
```

```markdown
---
name: our-tests
description: How tests are written and run in this project.
---

# Tests in this project

- pytest, never unittest.
- One file per module, mirroring `src/`.
- Name the test after the behaviour, not the function:
  `test_an_empty_input_raises`, not `test_parse_2`.
- Never mock what you can construct.

## Running them

    uv run pytest -x -q

Not `python -m pytest` — the project needs the venv's own interpreter.
```

La **description** es lo que más importa. Es con lo que Comodor compara tu
petición para decidir si cargar la skill, así que escríbela como la situación,
no como un título.

Reinicia, o `/skills`, y ya está.

### Incluir archivos

Una skill puede llevar archivos junto a `SKILL.md`:

```
~/.comodor/skills/our-tests/
  SKILL.md
  references/
    fixtures.md
    conventions.md
```

`SKILL.md` apunta a ellos; el agente lee uno solo cuando lo necesita. Eso
mantiene corta la skill misma — lo que importa, porque la skill se carga en el
turno y una larga cuesta tokens aunque el detalle no hiciera falta.

---

## Por proyecto

```
./.comodor/skills/<name>/SKILL.md
```

Se commitea con el repositorio, así todos los que trabajan en él tienen los
mismos procedimientos. Las skills de un proyecto se cargan junto a las tuyas.

---

## El presupuesto

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000
  }
}
```

`top_k` es cuántas pueden cargarse para un turno; `max_tokens` es el techo de
lo que pueden costar juntas. Una skill demasiado grande para caber se salta, y
se te dice cuál — el silencio aquí fue una vez un bug real, en el que una skill
sobredimensionada desplazaba en silencio a las más pequeñas.

---

## Gestionarlas

```bash
comodor skills add review taste output    # several at once
comodor skills update                     # refresh installed ones
comodor skills remove review
comodor skills list                       # with versions
```

---

## Ver también

- [Cómo aprende](learning.md) — lecciones que infiere, en lugar de procedimientos que escribes
- [Lo que el agente puede hacer](tools.md) — las herramientas que una skill le enseña a usar
