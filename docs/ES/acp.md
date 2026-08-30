# En tu editor

Comodor habla el [Agent Client Protocol](https://agentclientprotocol.com), de modo
que un editor que lo admita puede manejar Comodor directamente — con su propio
panel, sus propios avisos de permiso y su propia vista de archivos — con el mismo
agente, las mismas reglas aprendidas y las mismas transcripciones que la terminal.

```bash
comodor acp
```

Normalmente no escribirás eso. Lo lanza el editor.

---

## Configurarlo

Comodor imprime el bloque que tu editor está pidiendo:

```bash
comodor acp --print-config
```

```json
{
  "agent_servers": {
    "Comodor": {
      "command": "/home/you/.local/bin/comodor",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

Dónde va depende del editor. Tres que se configuraron y comprobaron en una
máquina real mientras se escribía esto:

**JetBrains** — PyCharm, IntelliJ, WebStorm y el resto, mediante el plugin AI
Assistant. Coloca el bloque en `~/.jetbrains/acp.json`, o usa *Add Custom
Agent* desde el menú de la ventana de AI Chat, que abre el mismo archivo.
Comodor aparece entonces en el selector de agentes de la parte inferior del
panel de chat. No se necesita una suscripción de JetBrains AI para esto —
los agentes ACP funcionan sin ella.

**VS Code** — instala una extensión cliente de ACP;
[ACP
Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client)
es la que se usó para comprobarlo. El bloque va bajo `acp.agents` en
`settings.json`, y Comodor aparece en la lista de agentes del panel ACP.

**Zed** — en `settings.json`, y Comodor aparece en el panel de agentes.

También se ha reportado que funcionan, aunque no se comprobó aquí: Neovim
(CodeCompanion, avante.nvim, agentic.nvim), Emacs (agent-shell.el), Qt Creator,
Obsidian y Visual Studio.

El protocolo es el mismo en todas partes; solo cambia el archivo de configuración.

Configura primero Comodor, en una terminal:

```bash
comodor setup
```

Un editor no tiene a dónde preguntar qué proveedor usar, así que un Comodor que
nunca se ha configurado se niega a iniciar una sesión e indica qué comando
ejecutar. Eso es un mensaje claro dentro del editor en lugar de un fallo en la
primera tarea.

---

## Qué obtiene el editor

| | |
|---|---|
| Respuestas en streaming | tal como las escribe el modelo |
| Llamadas a herramientas | cada una con su nombre, con lo que hizo, y marcada como lectura / edición / ejecución para que el editor pueda elegir un icono |
| Avisos de permiso | se preguntan en el editor, se responden en el editor |
| Planes | cuando Comodor escribe una lista de tareas, el editor la dibuja |
| Cancelación | el botón de detener del editor interrumpe el turno |
| Sesiones | se listan, se reanudan y se eliminan — las mismas transcripciones que reanuda `comodor` |

La carpeta de trabajo viene del editor: el proyecto que tengas abierto es donde
el agente lee y escribe, y queda confinado a ella.

---

## Lo que no hace

**Tomar un proveedor de modelo del editor.** El proveedor, el modelo, las reglas,
las habilidades y los permisos de Comodor son suyos, configurados con
`comodor setup` o en la interfaz del navegador. Un editor que también quisiera
configurar un modelo sería una segunda fuente de verdad para el mismo ajuste.

**Iniciar sesión.** Comodor se autentica ante un proveedor de modelo, no ante tu
editor, así que no anuncia métodos de autenticación y un cliente no te ofrecerá
un inicio de sesión.

---

## Cuando algo va mal

El protocolo reserva la salida estándar para los mensajes, así que los registros
de Comodor van a la salida de error estándar. Los editores suelen mostrarlos en
algún sitio — en Zed es el registro del servidor de agentes.

```
comodor acp — speaking ACP v2 on stdio
```

Uno común, y parece un agente roto en lugar de lo que es: el proveedor rechazando
tu clave. Llega al editor como `Error during prompt turn`, o con las palabras del
propio proveedor — `OpenRouter: User not found`, por ejemplo, lo que significa
que la clave fue revocada. `comodor doctor` dice qué proveedor está configurado;
la interfaz del navegador aceptará una clave nueva, o iniciará sesión por ti.

Si el agente se conecta y luego no hace nada, ejecuta primero `comodor doctor`
en una terminal: un proveedor inaccesible se ve igual desde un editor que un
agente roto.

---

## Véase también

- [Desde un navegador](web.md) — el mismo agente, en una pestaña del navegador
- [La interfaz](interface.md) — la versión de terminal
- [Seguridad](safety.md) — qué pregunta antes, y qué nunca hace
