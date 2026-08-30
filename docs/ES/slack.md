# Desde Slack

El mismo agente, en tu espacio de trabajo: envíale una tarea, mira cómo
trabaja, responde sus preguntas — sin abrir una terminal.

```bash
comodor slack manifest              # the app definition to paste into Slack
comodor slack connect               # the two tokens, checked as you paste them
comodor slack pair                  # add your account
comodor slack start --background    # run it
```

Alrededor de cinco minutos, y **no hay dirección pública que arreglar** — lo
que separa esto de [WhatsApp](whatsapp.md).

Ejecuta la misma sesión de agente que ejecutan la terminal, el navegador y el
bot de Telegram. Una tarea iniciada aquí aprende las mismas lecciones y
aterriza en el mismo historial.

## Por qué esto es fácil

Slack tiene dos maneras de entregar eventos. La Events API publica a una URL,
lo que significa una dirección HTTPS pública, un certificado y un túnel — todo
el trabajo que hace difícil a WhatsApp.

**Socket Mode** lo invierte: la app le pide a Slack una dirección de websocket
y se conecta *hacia afuera*. Nada tiene que ser alcanzable desde internet, y no
hay dirección que mantener al día. Ese es todo el truco, y es la razón por la
que Slack se sienta al lado de Telegram en lugar de al lado de WhatsApp.

Lo segundo que ayuda es el **app manifest**. Slack permite describir una app en
un documento YAML, así que en lugar de encontrar once casillas repartidas por
cuatro páginas de configuración, toda la app — nombre, scopes, eventos, Socket
Mode ya activado — es un solo pegado.

## Configurarlo

### 1. Crea la app

```bash
comodor slack manifest
```

Eso imprime el manifest y el enlace. En
[api.slack.com/apps](https://api.slack.com/apps?new_app=1), elige **From a
manifest**, elige tu espacio de trabajo, pégalo, crea — luego **Install to
Workspace**.

### 2. Los dos tokens

No son intercambiables, y confundirlos es la manera más común de que esto
falle. Comodor rechaza cada uno en el lugar del otro por nombre en lugar de
dejar que Slack responda `invalid_auth` una hora después.

| | | |
|---|---|---|
| `xoxb-…` | **Bot token** | OAuth & Permissions. Hace todo lo que hace el bot |
| `xapp-…` | **App-level token** | Basic Information → App-Level Tokens, scope `connections:write`. Abre el socket, y nada más |

```bash
comodor slack connect
```

Sin argumentos te guía por ambos y comprueba cada uno a medida que llega — el
token de bot contra `auth.test`, el token de app abriendo realmente un socket
con él. Uno equivocado es una frase ahora en lugar de un misterio la próxima
semana.

### 3. Empareja tu cuenta

```bash
comodor slack pair
```

Eso imprime un código de seis dígitos. Envíalo a Comodor como mensaje directo y
tu cuenta queda añadida. El código funciona una vez y expira en cinco minutos.

**Un espacio de trabajo puede tener cientos de personas**, y este es un agente
que lee y escribe tus archivos. Así que responde a una lista fija de ids de
usuarios de Slack e ignora a todos los demás.

```bash
comodor slack status
comodor slack forget U01234567
comodor slack forget all
```

## Dónde responde

**En un mensaje directo**, siempre.

**En un canal, solo cuando se le menciona.** Un bot que responde a cada mensaje
en un canal compartido es un bot que alguien elimina esa tarde.

**En el hilo donde se le habló.** Una pregunta hecha en un hilo se responde en
ese hilo, no en el canal delante de todos.

Sus propios mensajes nunca se responden — un bot que se responde a sí mismo es
un bucle con un límite de frecuencia encima.

## Lo que puede hacer, y lo que no

**Por defecto lee y planifica, y no cambia nada.** Una sesión de Slack se
mantiene en modo planificación sin importar lo que tenga configurada la
terminal, por la misma razón que los otros canales: aprobar un comando de shell
desde un teléfono, en una fila, es una decisión tomada con menos atención que
la misma aprobación en un teclado.

```bash
comodor slack writes on
comodor slack writes off
```

Un comando de terminal a propósito. Un bot que pudiera ampliar sus propios
permisos solo necesitaría la cuenta de Slack de alguien.

## Los botones

Slack es el más espacioso de los tres canales — los mensajes se pueden editar y
los botones sobran — así que una respuesta es un mensaje que crece a medida que
llega la respuesta, y todo el menú cabe en una pantalla.

| | |
|---|---|
| **New chat** | Olvidar la conversación hasta ahora |
| **History** | Reabrir una conversación anterior |
| **Mode** | Actuar, planificar o conversar |
| **Status** | Modelo, carpeta, contexto, gasto |
| **Model** | Cambiar a otro |
| **Folder** | En qué proyecto trabaja |
| **Skills** | Instalar o quitar uno |
| **Rules** | Lo que aprendió de tus correcciones |
| **What it may do** | Si puede editar y ejecutar |
| **Help** | Qué hace cada cosa |

Mientras una tarea corre lo único que se ofrece es **Stop**.

## Ejecutarlo

```bash
comodor slack start                # here, holding this terminal
comodor slack start --background   # detached; survives closing it
comodor slack stop
comodor slack service install      # starts at login, survives a reboot
comodor slack service show         # read the unit before trusting it
```

El registro es `slack.log` junto a tu configuración, añadido en lugar de
reemplazado.

Un servicio de **usuario** en cada plataforma — systemd, launchd, Task
Scheduler — nunca uno del sistema. Este es un agente que lee y escribe tus
archivos con tus credenciales, y más autoridad que la persona que posee esos
archivos no compra nada.

## Desde el panel del navegador

`comodor web` → **Admin** → **From your phone** conecta, empareja, inicia y
detiene todo esto sin una terminal. Esos controles solo responden peticiones de
la máquina donde Comodor se está ejecutando: un token de bot entrega el control
remoto a quien tenga el token.

## Cómo está construido

Ninguna dependencia nueva. La Web API es `POST /api/chat.postMessage` sobre el
cliente HTTP que este proyecto ya tiene, y Socket Mode corre sobre el cliente
websocket escrito para manejar Chrome — por eso añadir Slack no añadió
paquetes.

Tres cosas de las que el bucle del socket cuida, cada una de ellas una manera
de que un bot se quede en silencio sin que nadie lo note:

- **Cada sobre se acusa de recibo.** Slack reentrega lo que no escucha, y para
  un agente que ejecuta comandos que un mensaje se convierta en tres turnos no
  es meramente ruidoso.
- **`disconnect` es rutina.** Slack rota las conexiones según un calendario.
  Tratar eso como un fallo produce un bot que muere cada pocas horas.
- **Un espacio de trabajo en silencio sigue recibiendo pings.** El caso que más
  importa — nadie le ha escrito en una hora — es exactamente el que arruina un
  socket caído.

## Lo que no hará

- Responder a quien no esté emparejado.
- Responder todo en un canal al que fue añadido.
- Tomar un token o una cuenta permitida del `.comodor/config.json` de un
  proyecto. Un repositorio que pudiera añadir a su autor a esa lista sería una
  puerta trasera.
- Editar nada hasta `slack writes on`.
- Imprimir cualquiera de los dos tokens. Ambos se eliminan de cada error que se
  lanza.
