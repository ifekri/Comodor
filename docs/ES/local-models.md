# Modelos en tu propia máquina

Comodor puede descargar un modelo, guardarlo en tu disco y ejecutarlo ahí — sin
clave, sin cuenta, y sigue funcionando con la red desconectada.

```bash
comodor local list                       # what you can run, and what is here
comodor local get qwen2.5-coder-7b-q4    # download it, with a progress bar
comodor local use qwen2.5-coder-7b-q4    # make it the one the agent talks to
```

La misma lista está en el navegador bajo **Admin → Local LLM**, con la misma
descarga, el mismo progreso y los mismos botones.

## Cómo está montado esto, y por qué no es lento

Todo lo creíble hace lo mismo — Ollama, LM Studio, llama.cpp, vLLM — y Comodor
también: **la inferencia corre en un proceso separado que habla una API
compatible con OpenAI, y el modelo se queda cargado en él entre peticiones.**

Tres razones, todas sobre el agente seguir respondiendo:

**El GIL.** La generación es un largo bucle ligado a la CPU. Ejecutarlo en el
propio proceso de Comodor hace que todos los demás hilos — la interfaz
repintando, una herramienta terminando, el bus de eventos — esperen detrás. En
otro proceso es el problema de otro núcleo.

**Cargar es caro y debe pasar una vez.** Leer cuatro gigabytes del disco y
acomodarlos toma de segundos a decenas de segundos. Cargar por petición paga
eso en cada turno; un servidor residente lo paga una vez y después responde en
milisegundos.

**Un fallo se queda allá.** Un kill por falta de memoria en un modelo 14B
termina el servidor del modelo, no tu sesión. El agente reporta un error de
conexión y la transcripción sobrevive.

La consecuencia feliz es que casi no hay código nuevo: un servidor local en
`http://127.0.0.1:PORT/v1` *es* un endpoint compatible con OpenAI, así que el
proveedor existente lo maneja sin cambios. El puerto se elige cuando el
servidor arranca, razón por la que el proveedor `local` no lleva URL en la
configuración — una escrita ahí estaría mal la próxima vez.

El servidor arranca con tu **primer mensaje**, no al inicio. Cargar cuatro
gigabytes cada vez que ejecutaste `comodor` — incluidas las veces que nunca le
preguntaste nada al modelo — sería una pantalla en blanco sin razón.

## Lo que necesitas

El archivo del modelo, que Comodor descarga, y algo que lo ejecute. Comodor usa
el que encuentre:

```bash
brew install llama.cpp          # macOS
winget install llama.cpp        # Windows
                                # Linux: github.com/ggml-org/llama.cpp
```

Ollama o LM Studio, si alguno ya está corriendo, funcionan también.
`comodor local list` lo dice claramente cuando nada está disponible, así que te
enteras antes de gastar una hora en una descarga en lugar de después.

## La descarga

Un modelo son uno a nueve gigabytes por tu línea de casa, y todo lo de la
descarga está moldeado por eso.

**Se reanuda.** Los bytes van a un archivo `.part`. Detenlo, cierra la laptop,
pierde la conexión — el siguiente `comodor local get` le pide al servidor
continuar desde donde termina ese archivo. El navegador muestra `Resume (37%)`
en lugar de `Download`.

**Se verifica.** Cada entrada del catálogo lleva un conteo exacto de bytes y un
SHA-256, y el archivo no se acepta hasta que coincide. Esto no es por
precaución doble: un GGUF truncado *no* está obviamente roto — carga, y luego
el modelo produce tonterías, y pasas una tarde preguntándote por qué un modelo
bien considerado es inútil. Un archivo que falla se elimina en lugar de dejarse
para encontrarlo después y confiarle a medias.

**Es observable.** En la terminal, una barra con los cuatro números que
responden la pregunta que se hace:

```
qwen2.5-coder-7b-q4 ━━━━━━━━━━━━━━╸────────  38.2%  1.7/4.4 GB  8.9 MB/s  0:05:12
```

En el navegador, los mismos números bajo una barra en la tarjeta del modelo,
actualizándose desde el flujo de eventos en lugar de por sondeo.

## Dónde van los archivos

Un directorio, compartido por cada proyecto de la máquina — de otro modo el
mismo modelo en tres checkouts serían tres copias de los mismos bytes.

```bash
comodor local where
```

`comodor local remove <id>` elimina uno, y dice cuánto volvió.

## Añadir un modelo a la lista

La lista es un archivo JSON, así que un modelo nuevo es una edición en lugar de
un lanzamiento. Tanto la terminal como el navegador lo recogen.

```json
{
  "id": "my-model-q4",
  "name": "My Model 7B",
  "description": "One sentence on what it is good at, and what it is not.",
  "url": "https://huggingface.co/OWNER/REPO/resolve/main/file.gguf",
  "size": 4683074336,
  "sha256": "1664fccab734674a...",
  "context": 32768,
  "parameters": "7B",
  "quantization": "Q4_K_M",
  "needs_ram_gb": 8,
  "license": "apache-2.0",
  "good_at": ["code"],
  "tools": true,
  "vision": false
}
```

`id`, `name`, `url` y `size` son obligatorios — todo lo demás es opcional, y
cualquier cosa que dejes fuera se reporta como desconocida en lugar de
adivinarse. Un número equivocado aquí le cuesta a alguien una descarga y un
fallo.

Consigue el tamaño y el checksum desde la API en lugar de teclearlos:

```bash
curl -s 'https://huggingface.co/api/models/OWNER/REPO?blobs=true' | python -c \
  "import json,sys;[print(f['rfilename'], f['size'], f.get('lfs',{}).get('sha256')) \
   for f in json.load(sys.stdin)['siblings'] if f['rfilename'].endswith('.gguf')]"
```

Dos reglas que el cargador impone:

- **Solo `https`.** Un archivo de modelo es un artefacto ejecutable en todo lo
  que importa, y uno descargado por un canal que alguien pueda reescribir en
  vuelo no es algo que se permita porque un catálogo lo pida.
- **Una entrada mala no cuesta la lista.** Un modelo malformado se salta y el
  resto carga, porque la alternativa es un selector vacío.

Comodor trae una copia de la lista y busca una más nueva una vez al día,
guardando en caché lo que encuentra. Sin red usa la caché, y en su defecto la
copia que trae — que es todo el punto de traer una.

## Lo que no hará

`needs_ram_gb` se comprueba contra tu máquina antes de que empiece la descarga,
y un modelo que no quepa lo dice en lugar de dejarte gastar una hora en
descubrirlo. `comodor local get --yes` lo anula si no estás de acuerdo.

El disco se comprueba del mismo modo, con un décimo de reserva: una descarga
que llena el último byte de un disco no solo falla, se lleva el resto de la
máquina consigo.
