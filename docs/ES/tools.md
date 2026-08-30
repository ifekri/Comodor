# Lo que el agente puede hacer

Trece herramientas. Cada una declara un nivel de riesgo, lo que decide si
pregunta antes — ver [Seguridad](safety.md#risk-tiers).

---

## Archivos

| | Riesgo | |
|---|---|---|
| `read_file` | safe | Leer un archivo de texto. Hace streaming, así que un fragmento de un log grande es alcanzable |
| `list_dir` | safe | Las entradas de un directorio, con tamaños |
| `glob` | safe | Encontrar archivos por patrón de nombre — `src/**/*.py` |
| `grep` | safe | Buscar en contenidos con una expresión regular |
| `write_file` | write | Crear un archivo o reemplazarlo por completo |
| `edit_file` | write | Reemplazar una cadena exacta en un archivo |

Todo está confinado a la carpeta del proyecto a menos que apagues
`safety.workspace_only`.

Se prefiere `edit_file` sobre `write_file` para un cambio en un archivo
existente: es más pequeño, se revisa como un diff, y no puede perder en silencio
el resto del archivo.

---

## Ejecutar cosas

| | Riesgo | |
|---|---|---|
| `run_shell` | dangerous | Un comando de shell en el espacio de trabajo |
| `run_python` | dangerous | Un fragmento corto de Python, en un subprocess |

Ambos preguntan antes de ejecutarse, ambos están sujetos a
`safety.deny_commands`, y ambos tienen su salida acotada — ver [Cuando la
salida es demasiado grande](#when-output-is-too-big).

En la interfaz puedes saltarte al modelo por completo:

```
!git status
```

Lo ejecuta, te muestra la salida, y nunca se lo menciona al modelo. Más rápido
y más barato que preguntar.

---

## La web

| | Riesgo | |
|---|---|---|
| `web_fetch` | dangerous | Descargar una URL y devolver su texto legible |
| `web_search` | dangerous | Buscar, y devolver títulos, URLs y fragmentos |
| `browse` | dangerous | Un navegador real — JavaScript, cookies, inicios de sesión |

`web_fetch` es el barato: reduce la página a texto. Úsalo cuando la página es
un documento.

`browse` es para cuando es una aplicación — algo que necesita JavaScript, un
inicio de sesión o un clic. [Guía completa](browser.md).

---

## La máquina

| | Riesgo | |
|---|---|---|
| `computer` | dangerous | Ratón, teclado y pantalla, en cualquier aplicación |

Apagado a menos que lo actives, y aun así no permitido hasta que lo concedas.
[Guía completa](computer.md). Solo Windows por ahora.

---

## Llevar la cuenta

| | Riesgo | |
|---|---|---|
| `todo_write` | safe | La lista de tareas que ves en la barra lateral |

El agente escribe aquí su propio plan. No es decoración — es como una tarea
larga se mantiene coherente, y cómo puedes ver dónde está.

---

## A veces está, a veces no

Comodor solo ofrece una herramienta que el modelo podría usar de verdad. Una
herramienta que puede ver y que nunca puede usar con éxito invita a una llamada
desperdiciada en cada turno.

| | Aparece cuando |
|---|---|
| `read_skill_file` | una skill que instalaste incluye archivos |
| `search_history` | hay sesiones pasadas que buscar |
| `delegate` | se podría lanzar un sub-agente |
| `computer` | la plataforma tiene un backend **y** lo activaste |
| Herramientas MCP | hay un servidor configurado y habilitado |

`browse` tiene dos implementaciones: el navegador real cuando Chrome, Chromium,
Edge o Brave están instalados, y un navegador de texto cuando no hay ninguno.
Ambas se llaman `browse`, porque elegir entre dos cosas llamadas "browser" es un
turno que el modelo no debería tener que gastar.

---

## Cuando la salida es demasiado grande

Un comando que imprime cincuenta mil líneas no se trunca hasta la inutilidad ni
revienta el contexto.

Lo que cabe va al modelo — la cabeza y la cola, porque ahí suele estar la
respuesta. El resto se escribe en un archivo bajo `~/.comodor/output/`, y al
modelo se le dice la ruta y cómo leerlo. Así puede ir a mirar si lo necesita, y
no paga nada si no.

```json
{ "agent": { "max_tool_chars": 12000 } }
```

---

## Sub-agentes

`delegate` ejecuta un segundo agente en un **git worktree** — un checkout
aislado del mismo repositorio. Trabaja allí, y sus cambios vuelven como un
parche aplicado con una fusión de tres vías.

No tiene memoria, no puede delegar más, y no recibe la pantalla. Hereda la
cancelación del padre, así que `Esc` también lo detiene.

Útil para algo genuinamente separado — "porta este módulo a la nueva API
mientras sigo trabajando" — y un desperdicio para cualquier otra cosa.

---

## Herramientas MCP

Todo lo que provee un servidor de Model Context Protocol habilitado aparece
junto a las herramientas integradas y pasa por exactamente la misma compuerta de
permisos.

```bash
comodor mcp list
```

[Guía completa](mcp.md).

---

## Ver también

- [Seguridad y permisos](safety.md) — qué significa en la práctica cada nivel
- [La interfaz](interface.md) — ver correr las herramientas
- [Skills](skills.md) — enseñarle *cómo* usar estas para un trabajo concreto
