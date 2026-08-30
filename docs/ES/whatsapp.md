# Desde WhatsApp

El mismo agente, alcanzado desde un número de WhatsApp Business: envíale una
tarea, mira cómo trabaja, responde sus preguntas — sin abrir una terminal.

> **Lee esto primero.** [Telegram](telegram.md) hace lo mismo y toma alrededor
> de un minuto: envía un mensaje a @BotFather, pega un token. WhatsApp toma
> alrededor de veinte, es técnico, y la mayor parte está en el panel de Meta —
> necesitas una app de Meta, un app secret y una dirección HTTPS pública.
> **Si no tiene que ser WhatsApp, usa Telegram.**
>
> [Slack](slack.md) es el camino intermedio: alrededor de cinco minutos, y
> tampoco necesita dirección pública.
>
> No hay manera de evitarlo. WhatsApp no tiene equivalente de un token de bot,
> y Meta entrega los mensajes a una URL en lugar de dejar que algo los
> consulte. La única versión genuina de un clic enrutaría cada mensaje por el
> servidor de otra persona, que no es un trato que esta herramienta haga.

```bash
comodor whatsapp connect              # walks you through all of it
comodor whatsapp pair                 # add your number
comodor whatsapp start --background   # run it
```

`connect` sin argumentos es una configuración guiada: enlaza cada página, toma
un valor a la vez, y comprueba cada uno a medida que llega — el token contra
Meta, el id por ser un id, el secret por ser un secret. Inicia el túnel por ti,
y espera a que el callback de verificación de Meta llegue realmente en lugar de
asumir que llegó.

Ejecuta la misma sesión de agente que ejecutan la terminal, el navegador y el
bot de Telegram. Una tarea iniciada aquí aprende las mismas lecciones y aparece
en el mismo historial.

## Por qué esto lleva más configuración que Telegram

Telegram te da un token y te deja consultar los mensajes. WhatsApp es la
**Cloud API** de Meta, y dos de sus decisiones de diseño moldean todo aquí.

**Los mensajes se entregan, no se consultan.** No hay long poll. Meta publica
cada mensaje entrante a una URL, lo que significa que algo tuyo tiene que ser
alcanzable desde internet por HTTPS. Ese es el trabajo extra, y no hay manera
de evitarlo.

**Meta quiere una app.** Una cuenta de empresa, un número, un token de acceso y
un app secret — cuatro cosas que viven en un navegador, razón por la que el
asistente inicial apunta a esta página en lugar de intentar recolectarlas.

La alternativa a la que recurren la mayoría de los proyectos es una biblioteca
que maneja WhatsApp Web a través de un navegador sin cabeza. Esas necesitan
Node, se rompen cada vez que WhatsApp cambia su cliente web, y van contra los
términos a los que se sujeta la cuenta: el modo de fallo es que el número sea
baneado. No es algo que una herramienta de código pueda entregar a sus
usuarios.

## Cuánto tarda esto

Alrededor de veinte minutos la primera vez, frente a un minuto para Telegram, y
la mayor parte está en el panel de Meta más que aquí.

Lo que **no** necesitas: un número de teléfono real, un método de pago, o
verificación de empresa. Añadir el producto WhatsApp crea un **número de
prueba** que envía mensajes a hasta cinco destinatarios gratis, lo que es
cuatro más de lo que requiere una persona hablando con su propio agente.

## Configurarlo

La versión corta es `comodor whatsapp connect`, que recorre todo. Lo que sigue
es por lo que pasa, para quien prefiera verlo primero.

### 1. Una app de Meta con WhatsApp encima

En [developers.facebook.com](https://developers.facebook.com), crea una app y
añade el producto **WhatsApp**. Meta te da un número de prueba para empezar;
uno real se añade después bajo la cuenta de empresa.

Necesitas cuatro cosas de ahí:

| | |
|---|---|
| **Phone number id** | El id numérico junto al número — *no* el número |
| **Access token** | El del panel dura 24 horas. Un token de **System User** bajo Business Settings no expira, y es el que hay que usar |
| **App secret** | Settings → Basic. Cada webhook se firma con él |
| **Una dirección HTTPS pública** | Donde Meta entrega. Véase abajo |

```bash
comodor whatsapp connect \
    --number-id 123456789012345 \
    --token EAAG… \
    --app-secret 0a1b2c…
```

Eso comprueba el token contra Meta antes de guardar nada, así que un error
tipográfico es un mensaje ahora en lugar de un misterio la próxima semana.

### 2. Algún lugar al que Meta pueda entregar

El bot escucha en `127.0.0.1:8770`. Meta solo entregará a **HTTPS** y no
aceptará un certificado autofirmado, así que algo tiene que poner uno real
delante de él. Un túnel es la respuesta usual: sin puerto abierto, sin DNS, sin
dominio.

**`comodor whatsapp connect` lo hace por ti** si `cloudflared` está instalado —
inicia el túnel, lee la dirección de él, y te muestra qué pegar. Para ejecutar
uno tú mismo:

```bash
cloudflared tunnel --url http://127.0.0.1:8770
comodor whatsapp connect --url https://something.trycloudflare.com/whatsapp
comodor whatsapp webhook
```

**Un túnel rápido obtiene una dirección nueva cada vez que arranca.** Eso está
bien mientras configuras y está mal para un bot pensado para seguir corriendo:
Meta sigue entregando a la dirección que le diste, así que tras un reinicio no
llega nada y nada dice por qué. `comodor whatsapp start --tunnel` avisa cuando
la dirección se ha movido.

Para una dirección que permanezca, crea un túnel con nombre una vez — necesita
una cuenta gratuita de Cloudflare:

```bash
cloudflared tunnel login
cloudflared tunnel create comodor
cloudflared tunnel route dns comodor comodor-hooks.example.com
```

Cualquier otra cosa que termine TLS y reenvíe a `127.0.0.1:8770` funciona del
mismo modo.

```
  Callback URL   https://something.trycloudflare.com/whatsapp
  Verify token   Kq3nP…
```

Pega ambos en **WhatsApp → Configuration** en el panel, luego suscribe la app
al campo **messages**. Meta llama inmediatamente a la URL una vez para
comprobarla; el bot responde ese handshake por sí mismo.

Un proxy inverso que ya tengas corriendo funciona del mismo modo — cualquier
cosa que termine TLS y reenvíe a `127.0.0.1:8770`.

### 3. Empareja tu número

```bash
comodor whatsapp pair
```

Eso imprime un código de seis dígitos. Envíalo al número de empresa desde
WhatsApp y tu número queda añadido. El código funciona una vez y expira en
cinco minutos.

**Un número de empresa es un número de teléfono**, y los extraños escriben a
números de teléfono como cosa normal. Así que responde a una lista fija y todos
los demás reciben **silencio** — no un rechazo. Un número que dice "no tienes
permiso" le ha dicho a un extraño que vale la pena intentarlo de nuevo.

```bash
comodor whatsapp status         # who may talk to it
comodor whatsapp forget 15551234567
comodor whatsapp forget all
```

La lista se compara como dígitos, así que `+1 555…`, `001 555…` y `1555…` son
una persona en lugar de tres.

## Lo que puede hacer, y lo que no

**Por defecto lee y planifica, y no cambia nada.** Una sesión de WhatsApp se
mantiene en modo planificación sin importar lo que tenga configurada la
terminal, por la misma razón que Telegram: aprobar un comando de shell con el
pulgar, en una fila, es una decisión tomada con menos atención que la misma
aprobación en un teclado.

```bash
comodor whatsapp writes on
comodor whatsapp writes off
```

Eso es un comando de terminal a propósito. Un bot que pudiera ampliar sus
propios permisos solo necesitaría el teléfono de alguien.

## Los botones

WhatsApp permite **tres** botones de respuesta de veinte caracteres, o un botón
que abre una lista de **diez** filas. Esos son límites duros — Meta rechaza el
mensaje completo en lugar de recortarlo — así que el menú es una lista, y es
exactamente de diez filas:

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

Mientras una tarea corre lo único que se ofrece es **Stop**: no hay espacio en
una pantalla tan estrecha para mantener un control ahí deshabilitado.

Las listas más largas — modelos, habilidades, historial — se paginan de ocho en
ocho, porque las dos filas de navegación cuentan contra las diez.

## Dos cosas que te sorprenderán

**No puede editar un mensaje.** Telegram transmite una respuesta reescribiendo
un mensaje a medida que llega la respuesta. WhatsApp no tiene edición, y un
mensaje por token serían cien notificaciones por una pregunta. Así que un turno
dice una línea cuando empieza, habla de vez en cuando mientras trabaja, y envía
la respuesta cuando hay una.

**Hay una ventana de un día.** Meta solo permite mensajes de formato libre
dentro de las veinticuatro horas de *tu* último mensaje. Si una tarea larga
termina después de eso, el bot no puede decírtelo — lo dice en su registro, y
escribirle de nuevo reabre la ventana.

## Ejecutarlo

Exactamente como Telegram:

```bash
comodor whatsapp start                # here, holding this terminal
comodor whatsapp start --tunnel       # and bring a tunnel up with it
comodor whatsapp start --background   # detached; survives closing it
comodor whatsapp stop
comodor whatsapp service install      # starts at login, survives a reboot
comodor whatsapp service show         # read the unit before trusting it
```

El registro es `whatsapp.log` junto a tu configuración, añadido en lugar de
reemplazado.

Un servicio de **usuario** en cada plataforma — systemd, launchd, Task
Scheduler — nunca uno del sistema. Este es un agente que lee y escribe tus
archivos con tus credenciales, y más autoridad que la persona que posee esos
archivos no compra nada.

## Cómo está construido

Ninguna dependencia nueva. La Cloud API es `POST /messages` sobre el cliente
HTTP que este proyecto ya tiene, y el webhook es `http.server` de la biblioteca
estándar.

El endpoint responde a Meta **antes** de hacer el trabajo. Meta reintenta
cualquier cosa por la que no recibe un 200 en segundos, y un turno del agente
toma minutos — un webhook que espera recibe el mismo mensaje entregado cinco
veces.

Los ids de mensaje se recuerdan, así que una reentrega que llegue de todos
modos no se convierte en un segundo turno.

## Lo que no hará

- Responder a quien no esté emparejado, ni decir por qué.
- Aceptar un webhook que no pueda verificar. Sin un app secret nada se
  verifica, y `comodor whatsapp status` lo dice en amarillo.
- Tomar un token, un número o una cuenta permitida del `.comodor/config.json`
  de un proyecto. Un repositorio que pudiera añadir a su autor a esa lista
  sería una puerta trasera.
- Editar nada hasta `whatsapp writes on`.
- Imprimir el token. Se elimina de cada error que se lanza.
