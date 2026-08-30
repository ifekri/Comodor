# En Docker

El agente, su navegador y todo lo que necesita, en un contenedor.

```bash
git clone -b docker https://github.com/ifekri/Comodor.git comodor-docker
cd comodor-docker
export ANTHROPIC_API_KEY=…        # or OPENAI_API_KEY, OPENROUTER_API_KEY, …
docker compose up
```

Construye la imagen la primera vez y luego imprime la dirección:

```
  Comodor is at  http://127.0.0.1:8765/?token=…
  Working in     /work
```

Abre el enlace. Un token nuevo en cada ejecución, así que usa el de *esta*
ejecución.

O sin clonar nada:

```bash
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e ANTHROPIC_API_KEY \
  -v "$PWD:/work" \
  ghcr.io/ifekri/comodor:latest
```

---

## Aquí una clave no es opcional

La interfaz del navegador no tiene forma de introducirla, así que sin una clave
el contenedor dice qué falta y se detiene en lugar de servir una URL que falla
en la primera tarea.

Compose pasa a través del que esté establecido en tu shell, sin escribirlo en
la imagen ni en el archivo compose:

```
ANTHROPIC_API_KEY   OPENAI_API_KEY   OPENROUTER_API_KEY   DEEPSEEK_API_KEY
GEMINI_API_KEY      GROQ_API_KEY     XAI_API_KEY          MISTRAL_API_KEY
XIAOMI_API_KEY
```

¿Prefieres un archivo a tu historial del shell? Ponlo en un `.env` junto al
archivo compose — compose lo lee, y está en el gitignore.

---

## Dónde trabaja

Todo lo que el agente puede tocar es la carpeta `work/` junto al archivo
compose. Apúntalo a otro lugar:

```yaml
volumes:
  - "/path/to/your/project:/work"
```

Lo que aprende — el cerebro, tus correcciones, las transcripciones de sesión —
vive en un volumen con nombre, así que sobrevive a `docker compose down` y es
olvidado por `docker compose down -v`.

---

## Quién puede alcanzarlo

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

**El `127.0.0.1` de la izquierda es todo el modelo de seguridad.** Quítalo y el
puerto queda en todas las interfaces de la máquina — y este puerto es una
shell.

Dentro del contenedor Comodor se enlaza a `0.0.0.0`, lo cual no es un descuido:
un contenedor tiene su propio espacio de nombres de red, así que enlazar el
loopback dentro de uno oculta el puerto de la máquina que lo ejecuta. Quién
puede realmente alcanzarlo lo decide cómo se publicó el puerto, y el banner lo
dice.

---

## Lo que el contenedor puede hacer

```yaml
cap_drop: [ALL]
security_opt:
  - no-new-privileges:true
```

Ejecuta comandos de shell, así que el contenedor es lo que se interpone entre
ellos y tu máquina. No se le da nada que no necesite, y se ejecuta como un
usuario no root.

---

## Fijar una versión

```yaml
args:
  COMODOR_VERSION: "0.9.0"
```

Fijado por defecto para que una reconstrucción sea reproducible. Para la
versión más reciente en cambio:

```bash
docker compose build --build-arg COMODOR_VERSION=
```

---

## Ejecutar otra cosa en él

```bash
docker compose run --rm comodor comodor doctor
docker compose run --rm comodor sh
```

Sin argumentos, o con argumentos que empiezan por un guion, significa
"ejecutar la interfaz web con estas opciones". Cualquier otra cosa es un
comando a ejecutar en su lugar.

---

## Lo que no está en el contenedor

**Tu pantalla.** [El control del escritorio](computer.md) maneja la máquina
donde Comodor se está ejecutando, y en un contenedor esa es una máquina sin
pantalla. La herramienta no se ofrece ahí.

El [navegador](browser.md) sí funciona — Chromium y sus fuentes están en la
imagen.

---

## Si no arranca

**Nada en `localhost:8765`** — comprueba que el puerto esté publicado:
`docker compose ps`.

**Se cierra inmediatamente** — lee el registro. Casi siempre no hay proveedor
configurado; el mensaje dice qué establecer.

**`exec /usr/local/bin/comodor-start: no such file or directory`** — un
checkout con CRLF. Corregido en la rama con un `.gitattributes`; si lo ves,
haz pull.

---

## Véase también

- [Desde un navegador](web.md) — la interfaz que usarás
- [Seguridad](safety.md) — lo que el agente puede hacer dentro del contenedor
