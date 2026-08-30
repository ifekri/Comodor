# Servidores MCP

El Model Context Protocol es una forma de que una herramienta se describa a sí
misma ante un agente. Comodor lo habla, así que cualquier cosa con un servidor
MCP se convierte en algo que el agente puede usar.

---

## Añadir uno

```bash
comodor mcp catalogue          # servers Comodor can set up for you
comodor mcp add filesystem     # one of them
comodor mcp list               # what you have, and what each offers
```

Algo que no está en el catálogo:

```bash
comodor mcp custom notes -- npx -y @some/mcp-notes
comodor mcp remote github https://mcp.example.com/sse
```

Luego comprueba que realmente funciona antes de confiar en él:

```bash
comodor mcp test notes
```

```
  notes            started in 0.8s
    create_note    Create a note with a title and body
    search_notes   Find notes by text
    delete_note    Delete a note by id
```

---

## Activarlos y desactivarlos

```bash
comodor mcp enable notes
comodor mcp disable notes
comodor mcp remove notes       # forget it entirely
```

```
/mcp                           # the same, in the interface
```

Un servidor desactivado no se inicia y sus herramientas no se ofrecen.

---

## Son herramientas como cualquier otra

Lo que un servidor proporciona aparece junto a las herramientas integradas y
pasa por **exactamente la misma puerta de permisos**. Una herramienta MCP que
escribe un archivo pregunta del mismo modo que pregunta `write_file`. Aquí no
hay puerta trasera.

---

## Un proyecto puede declarar, no activar

El `.comodor/config.json` de un repositorio puede listar los servidores que
usa:

```json
{
  "mcp": {
    "servers": {
      "project-db": { "command": "npx", "args": ["-y", "@acme/db-mcp"] }
    }
  }
}
```

Eso es útil: una persona nueva clona el repositorio y puede ver qué espera el
proyecto.

**Llegan desactivados.** Nombrar un servidor es una sugerencia; iniciar uno
ejecuta un comando en tu máquina, y esa es tu decisión. Actívalo una vez que
hayas mirado:

```bash
comodor mcp enable project-db
```

Un proyecto no puede establecer `mcp.enabled`, el interruptor maestro, en
absoluto. [Seguridad](safety.md#what-a-repository-may-set).

---

## Transportes

| | |
|---|---|
| **stdio** | un comando que Comodor inicia y con el que habla a través de pipes. Lo usual |
| **Streamable HTTP** | un servidor ya en ejecución en algún lugar, sobre HTTP |

Ambos están implementados en el paquete — sin dependencias para ninguno.

---

## Cuando uno se comporta mal

Un servidor que no arranca, o que tarda demasiado, se reporta y se omite. No se
lleva la sesión consigo.

```bash
comodor mcp test <name>        # start it and see
comodor doctor                 # includes every configured server
```

---

## Véase también

- [Lo que el agente puede hacer](tools.md) — las herramientas integradas a las que se suman
- [Seguridad](safety.md) — la puerta por la que pasan
