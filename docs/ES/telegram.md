# Desde tu teléfono

Comodor puede manejarse desde un bot de Telegram: envíale una tarea, mira cómo
trabaja, responde sus preguntas y detenlo — sin abrir una terminal.

**La configuración inicial pregunta por esto.** La última de las seis preguntas
ofrece conectar un bot, comprueba el token con Telegram ahí mismo, y empareja
tu cuenta antes de que el asistente termine. Si dijiste *Not now*, o estás
configurando una máquina que ya está configurada:

```bash
comodor telegram connect <token>   # a bot from @BotFather
comodor telegram pair              # add your account
comodor telegram start             # run it
```

Ejecuta la misma sesión de agente que ejecuta la interfaz del navegador. Todo
es un botón; escribir es para la tarea misma.

## Conseguir un bot

Envía un mensaje a [@BotFather](https://t.me/botfather) en Telegram, manda
`/newbot`, dale un nombre y un nombre de usuario que termine en `bot`. Responde
con un token:

```
1234567890:AAF…
```

```bash
comodor telegram connect 1234567890:AAF…
```

## Emparejamiento

**El nombre de usuario de un bot es público.** Cualquiera que lo encuentre
puede enviarle un mensaje, y este puede leer tus archivos. Así que responde a
una lista fija de ids numéricos de usuarios de Telegram y a nadie más.

```bash
comodor telegram pair
```

Eso imprime un código de seis dígitos. Envíalo a tu bot en Telegram y tu cuenta
queda añadida. El código funciona una vez y expira en cinco minutos.

Todos los demás reciben **silencio** — no un rechazo. Un bot que dice "no
tienes permiso" le ha dicho a un extraño que existe, que es un Comodor, y que
hay una lista que vale la pena entrar.

```bash
comodor telegram status         # who may talk to it
comodor telegram forget 12345   # revoke one account
comodor telegram forget all     # revoke everybody
```

## Lo que puede hacer, y lo que no

**Por defecto lee y planifica, y no cambia nada.** Una sesión de Telegram se
mantiene en modo planificación sin importar lo que tenga configurada la
terminal.

Eso es deliberado. Aprobar un comando de shell con el pulgar, en un teléfono,
en una fila, es una decisión tomada con menos atención que la misma aprobación
en un teclado — y las consecuencias son idénticas.

```bash
comodor telegram writes on      # let it edit files and run commands
comodor telegram writes off
```

Con las escrituras activadas aún pregunta primero, y la aprobación es un botón
en el chat:

```
Comodor wants to run
  npm test

  ✓  Yes, once
  ✓✓ Yes, and stop asking this session
  ✗  No
```

El compromiso más amplio nunca es el primer botón bajo tu pulgar — en un
teléfono están muy juntos y "siempre" no se puede deshacer.

## Los botones

`/start` responde con el modelo, la carpeta y lo que se le permite hacer, y los
ajustes debajo. Están en la primera pantalla en lugar de detrás de un botón
*Settings*, porque a qué apunta un bot es lo primero que cualquiera quiere
saber y lo primero que quiere cambiar.

| | |
|---|---|
| **New chat** | Olvidar la conversación hasta ahora |
| **History** | Reabrir cualquier conversación anterior, completa |
| **Stop** | Interrumpir lo que se está ejecutando — reemplaza a *New chat* mientras lo está |
| **Mode** | Actuar, planificar o conversar, cada uno detallado |
| **Status** | Modelo, carpeta, contexto, gasto |
| **Model** | Cada modelo que ofrece el proveedor; toca para cambiar |
| **Folder** | A qué proyecto está confinado |
| **Skills** | Instalar o quitar uno de la biblioteca |
| **Rules** | Lo que ha aprendido de tus correcciones, y cuántas |
| **Settings** | El resto — costo, y lo que puede hacer |
| **Help** | Qué hace cada cosa, sin salir del chat |

Cuando el agente necesita una decisión también pregunta con botones — las
mismas preguntas que haría en la terminal, una por pantalla, con **Write my
own** para cualquier cosa que no se le ocurrió.

Las listas más largas que una pantalla — modelos, habilidades, historial — se
paginan de seis en seis, con **Previous** y **Next**. Telegram renderizará
ochenta botones con gusto y nadie los recorrerá.

## Ejecutarlo

Tres maneras, en orden de cuánto quieres que dure.

```bash
comodor telegram start                # here, holding this terminal
comodor telegram start --background   # detached; survives closing the terminal
comodor telegram service install      # starts at every login, survives a reboot
```

**En primer plano** retiene la terminal y muestra lo que hace. Es la que se usa
mientras se configura, y la que hay que volver a usar cuando algo no funciona.

**En segundo plano** es el mismo proceso, desacoplado de la terminal que lo
inició, escribiendo a un registro en lugar de a una pantalla. Cerrar la
terminal, cerrar sesión, terminar la sesión — ninguno se lo lleva consigo.

```bash
comodor telegram stop        # end it
comodor telegram status      # is it running, since when, and as which pid
```

El registro es `telegram.log` junto a tu configuración, y se añade en lugar de
reemplazarse — la razón por la que un bot se detuvo anoche está en las líneas
que un reinicio borrará de otro modo.

**Al iniciar sesión** es trabajo del sistema operativo, no nuestro: nada que un
programa arranque para sí sobrevive al reinicio de la máquina.

```bash
comodor telegram service show        # read the unit before trusting it
comodor telegram service install
comodor telegram service uninstall
```

| | |
|---|---|
| Linux | una unidad **user** de systemd en `~/.config/systemd/user` |
| macOS | un LaunchAgent en `~/Library/LaunchAgents` |
| Windows | una tarea del Task Scheduler que se ejecuta al iniciar sesión |

Un servicio de usuario en los tres, nunca uno del sistema. Un servicio del
sistema corre como root o como SYSTEM, y este es un agente que lee y escribe
tus archivos con tus credenciales — más autoridad que la persona que posee esos
archivos no compra nada y cuesta todo si alguna vez está mal.

`service show` imprime la unidad antes de que `service install` la escriba.
Nadie debería tener que confiar en una definición de daemon que no se le ha
mostrado.

La carpeta importa en los tres: el agente solo lee y escribe dentro del
directorio donde fue iniciado, y ese es el directorio en el que trabajará el
bot.

## Cómo está construido

Ninguna dependencia nueva. La Bot API es `getUpdates` en un bucle y
`sendMessage`, sobre el cliente HTTP que este proyecto ya tiene —
`python-telegram-bot` habría sido lo más grande del wheel, para eso.

La respuesta se edita con un temporizador en lugar de por token. Telegram
cobra un viaje de ida y vuelta por edición y las limita en frecuencia, así que
editar por token produce un mensaje que llega estrangulado, todo de golpe al
final.

El bot guarda un offset de actualizaciones y lo avanza a medida que va. Sin
uno, un reinicio repite cada mensaje que el bot haya recibido jamás — lo cual,
para un agente que ejecuta comandos, no es meramente ruidoso.

## Lo que no hará

- Responder a quien no esté emparejado, ni decir por qué.
- Tomar un token o una cuenta permitida del `.comodor/config.json` de un
  proyecto. Un repositorio que pudiera añadir a su autor a esa lista sería una
  puerta trasera, y a diferencia del navegador o la pantalla no habría nada en
  pantalla para verlo suceder.
- Editar nada hasta `telegram writes on`.
- Imprimir el token. Está en cada URL de la Bot API, así que todo error que se
  lanza lo tiene eliminado.
