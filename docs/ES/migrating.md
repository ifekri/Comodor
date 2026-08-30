# Vienes de otro agente

Si ya usas **OpenClaw** o **Hermes**, Comodor ofrece traer tu configuración la
primera vez que lo ejecutas.

Ya encontraste tus claves de API y las pegaste en algún lado. Hacerlo otra vez
es una mala primera impresión.

---

## En la primera ejecución

```
 1/7  You already use OpenClaw
  OpenClaw  1 API key, the model (claude-sonnet-5), 1 skill
  /home/you/.openclaw

  Nothing is moved and nothing already set here is replaced.
  Keys are copied into your config; the other tool keeps working.

  1.  bring it over   keys, model and skills
  2.  keys only       leave the skills and the model
  3.  start fresh     import nothing
```

La pregunta solo aparece cuando hay algo que importar.

---

## Después

Instalaste uno de ellos después, o respondiste "start fresh" y cambiaste de
opinión:

```bash
comodor import              # bring it across
comodor import --dry-run    # say what it would take, change nothing
comodor import --keys-only  # leave the skills and the model
```

Ejecutarlo dos veces es seguro — la segunda vez dice que no hay nada nuevo.

---

## Lo que llega

| | |
|---|---|
| **API keys** | todo el tedio. De su `.env`, y del JSON inline de OpenClaw |
| **The model** | si Comodor puede hospedarlo |
| **Skills** | ambas herramientas escriben el mismo formato abierto, así que son archivos que copiar |

Tres reglas en todo el proceso, porque esto lee los archivos de otro programa:

- **No se sobrescribe nada.** Una clave ya configurada aquí gana; la
  importación llena huecos.
- **No se mueve nada.** Cada lectura es una lectura. La otra herramienta sigue
  funcionando exactamente como lo hacía.
- **Un archivo malformado se salta, no es fatal.** La mitad del valor es que
  corre en una máquina cuyo otro agente está en un estado raro.

---

## Lo que no llega, y por qué

**Su memoria.** Dicho en voz alta en lugar de saltado en silencio:

```
not imported: MEMORY.md — its memory is prose; this agent's is lessons with
confidence and evidence, and inventing those would poison recall
```

El brain de Comodor son lecciones con una confianza, evidencia y un
decaimiento, aprendidas de correcciones. Un `MEMORY.md` es prosa. Importar uno
como lo otro inventaría confidencias que nadie midió y llenaría el recall con
entradas que nunca se ganaron. Obtendrías un agente peor que parecía uno mejor
informado.

**Personas, mensajería, texto a voz.** Comodor no tiene equivalente, y un
ajuste importado hacia nada es peor que ningún ajuste.

**Una clave guardada en otro lugar.** OpenClaw permite que una clave sea una
referencia a un archivo o a un comando. Esos significan algo en la máquina para
la que se escribieron y nada aquí, así que se reportan en lugar de adivinarse.

---

## Skills, y algo que vale la pena saber

Las skills importadas llevan namespace — `review` se convierte en
`openclaw-review` — así una importación nunca puede reemplazar en silencio una
tuya.

Una carpeta de skill se copia archivo por archivo, y **una carpeta que contiene
un enlace fuera de sí misma se rechaza**. Una skill es un archivo cuyo contenido
se lee dentro de un prompt, así que un symlink a `~/.ssh/id_rsa` en el
directorio de skills de otro programa de otro modo habría sido copiado y enviado
a un modelo. Rechazada, y nombrada:

```
not imported: the skill sneaky — it contains a link out of that folder
```

---

## Dónde busca

| | |
|---|---|
| OpenClaw | `~/.openclaw`, `~/.clawdbot`, `~/.moltbot` |
| Hermes | `~/.hermes` |

Los directorios antiguos de OpenClaw siguen en máquinas reales — se renombró
dos veces — así que se comprueban los tres.

Para que deje de buscar del todo:

```bash
export COMODOR_NO_IMPORT=1
```

---

## Ver también

- [Primeros pasos](getting-started.md) — el resto de la primera ejecución
- [Configuración](configuration.md) — dónde acaban los ajustes importados
- [Skills](skills.md) — qué hacer con las que llegaron
