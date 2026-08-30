# Seguridad y permisos

Lo que Comodor puede hacerle a tu máquina, lo que pregunta antes, y lo que no
hará digas lo que digas.

---

## La versión corta

- **Leer es silencioso.** Listar archivos, leerlos, buscar — sin aviso.
- **Escribir pregunta.** Ves el diff antes de que ocurra.
- **Ejecutar un comando pregunta más fuerte**, y también llegar a la red o
  manejar tu pantalla.
- **Todo lo reversible lo revierte `/undo`.**
- **No puede salir de la carpeta del proyecto** a menos que apagues eso.
- **Un repositorio no puede cambiar nada de lo anterior.**

---

## Niveles de riesgo

Cada herramienta declara uno. El nivel decide qué pasa antes de que se
ejecute.

| Nivel | Herramientas | Lo que pasa |
|---|---|---|
| **safe** | `read_file`, `list_dir`, `grep`, `glob`, `todo_write` | se ejecuta |
| **write** | `write_file`, `edit_file` | pregunta, con un diff |
| **dangerous** | `run_shell`, `run_python`, `web_fetch`, `web_search`, `browse`, `computer` | pregunta |

En **modo plan**, cualquier cosa por encima de `safe` se rechaza antes de
ejecutarse. Eso se aplica en la capa de permisos, no pidiéndole al modelo que
se porte bien.

En **modo chat** no hay herramientas en absoluto.

---

## El aviso

```
  Run  pytest tests/ -x
  ────────────────────────────────────────────
  in ~/projects/api-server

  [a] allow   [A] allow always this session   [d] deny
```

`A` lo recuerda por el resto de la sesión, por tipo de cosa — permitir
escrituras no permite comandos, y permitir `pytest` no permite `rm`.

Para dejar de recibir preguntas:

```
/approve writes      files yes, commands still ask
/approve shell       commands yes, files still ask
/approve all         everything
```

O permanentemente, en tu configuración:

```json
{
  "safety": {
    "auto_approve_writes": true,
    "auto_approve_shell": false
  }
}
```

### Negar le enseña

Un rechazo es la señal de preferencia más clara que la interfaz recoge. Va al
motor de aprendizaje, así que el agente tiene menos probabilidad de proponer lo
mismo otra vez. Negar no es esfuerzo desperdiciado.

---

## Puntos de control y `/undo`

Cada archivo que el agente escribe tiene punto de control antes — el contenido
anterior, guardado bajo `.comodor/checkpoints/` en el proyecto.

```
/undo
```

restaura el último archivo que cambió. Funciona tanto si aprobaste la escritura
como si no, y tanto si la autoaprobación está activada como si no. Es la razón
por la que `/approve all` es algo razonable de hacer.

Apágalo si debes:

```json
{ "safety": { "checkpoints": false } }
```

No hay una buena razón para hacerlo.

---

## El límite del espacio de trabajo

El agente puede leer y escribir **dentro de la carpeta del proyecto y en
ningún otro lugar**.

La raíz del proyecto se encuentra subiendo desde donde empezaste hasta que algo
diga "esto es un proyecto" — un `.git`, un `pyproject.toml`, un
`package.json`. Se te muestra y se te pregunta, una vez por carpeta:

```
  Work in  /home/you/projects/api-server ?
```

Las carpetas aprobadas se recuerdan. `--cwd` nombra una directamente y no
pregunta.

```json
{ "safety": { "workspace_only": true } }
```

Apagar esto deja que el agente toque todo tu sistema de archivos. Está vetado
en la configuración de un repositorio precisamente por esa razón.

---

## Comandos que no ejecutará

Algunas cosas se rechazan antes de que aparezca cualquier aviso, porque ningún
aviso debería poder convencer a una persona de hacerlas al final de una sesión
larga:

```
rm -rf /     rm -rf ~     mkfs        dd if=      shutdown
reboot       format c:    del /f /s /q c:         :(){
> /dev/sda   chmod -R 777 /
```

La lista completa es `safety.deny_commands`. Añade las tuyas:

```json
{
  "safety": {
    "deny_commands": ["terraform destroy", "kubectl delete namespace"]
  }
}
```

`safety.allow_commands` es la otra dirección — comandos que nunca preguntan:

```json
{ "safety": { "allow_commands": ["git status", "pytest", "ls"] } }
```

---

## Tus claves

**Dónde viven.** Tu propio `~/.comodor/config.json`, escrito con permisos solo
para el propietario, o tu entorno. En ningún otro lugar.

**Dónde nunca van.** No a la configuración de un repositorio. No a la interfaz.
No a un log. No a un `repr` — ese fue un bug real, encontrado y corregido:
cualquier traceback que nombrara un Config solía imprimir la clave, y pytest
imprime tracebacks constantemente.

**Una clave en tu entorno se queda ahí.** Si exportas `ANTHROPIC_API_KEY` en
lugar de guardarla, `/save` no la copiará a tu archivo de configuración.
Exportarla en lugar de guardarla es una decisión y se respeta.

**Redacción.** Cualquier cosa que parezca una de tus claves se enmascara en la
salida de herramientas, en la transcripción y en las exportaciones. Funciona
sobre texto. No puede leer píxeles — ver
[Usar tu pantalla](computer.md#what-goes-to-the-model).

---

## Lo que un repositorio puede fijar

Un `.comodor/config.json` en un proyecto se lee desde el directorio en el que
empezaste — lo que para un agente de programación significa *desde un
repositorio que escribió otra persona, justo después de clonarlo*.

Así que está restringido a cosas que no pueden volverse contra ti:

| Un proyecto puede fijar | |
|---|---|
| `provider`, `model` | qué modelo usar |
| `agent` | modo, loop, los presupuestos, temperatura, tamaño de salida |
| `ui` | tema, bordes, marca |
| `learning`, `skills` | si están activados, y sus límites |
| `mcp.servers` | qué servidores usa — **llegando apagados** |

| Un proyecto **no** puede fijar | porque |
|---|---|
| `providers.*.base_url` | tu clave iría a su servidor en la primera petición |
| `safety.*` | podría hacer que el agente dejara de preguntar, o vaciar la lista de denegación |
| `agent.system_prompt_extra` | instrucciones inyectadas con tu autoridad |
| `browser.executable` | nombra un binario para que el agente lo lance |
| `computer.*` | le pide a la máquina a la que acaba de ser clonado tu ratón |
| `mcp.enabled` | declarar un servidor es una sugerencia; arrancar uno es una decisión |

Esta es una **allow-list**, no una deny-list, así que un ajuste añadido el
próximo año no es de confianza hasta que alguien decida lo contrario — la
manera correcta de estar equivocado.

Los rechazos se dicen en voz alta:

```
config: this project cannot set safety, computer — only your own can
```

Ignorar en silencio el archivo de alguien es como un archivo de configuración
se gana la reputación de no funcionar.

---

## Techos

Tres, y se aplican a cada tarea:

```json
{
  "agent": {
    "max_steps": 24,
    "max_seconds": 900,
    "max_cost_usd": 2.0
  }
}
```

**El de dinero solo funciona para un modelo con tarifa publicada.** Para un
modelo que la tabla de precios no conoce, el medidor de costo lee cero y el
límite nunca se dispara. Comodor te lo dice en lugar de dejarte creer que
tienes un techo:

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Dicho al inicio de una sesión y en `comodor doctor`. Ver [Costo](cost.md).

---

## Sub-agentes

`delegate` ejecuta un sub-agente en un git worktree — una copia aislada del
repositorio. No tiene memoria, no puede delegar más, y **no recibe la
pantalla**: un sub-agente trabajando en un worktree no tiene por qué tomar tu
ratón.

---

## Reportar algo

Si encuentras un problema de seguridad, por favor no abras un issue público.
Ver [SECURITY.md](../SECURITY.md).

---

## Ver también

- [Usar tu pantalla](computer.md) — el modelo de permisos más estricto de aquí
- [Configuración](configuration.md) — dónde vive cada ajuste
- [La interfaz](interface.md#approvals) — cómo se ven los avisos
