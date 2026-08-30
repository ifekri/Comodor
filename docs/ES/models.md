# Elegir un modelo

Comodor funciona con cualquier cosa que hable la API de OpenAI o la de Anthropic
— diecisiete proveedores de fábrica, más cualquier otra cosa con una URL.

---

## La respuesta corta

| Quieres | Elige |
|---|---|
| El inicio más fácil, una clave, todo | **OpenRouter** |
| El mejor trabajo agéntico | **Anthropic**, `claude-sonnet-5` |
| No pagar nada y quedarte offline | **Ollama** o **LM Studio** |
| Muy barato, bueno en código | **DeepSeek** |
| Muy rápido | **Groq** o **Cerebras** |

```bash
comodor setup        # pick one, once
```

---

## Todos los proveedores

**Hosteado, una clave:** OpenRouter · Anthropic · OpenAI · Google Gemini ·
DeepSeek · xAI · Mistral · Groq · Cerebras · Moonshot (Kimi) · Z.AI (GLM) ·
Qwen · Together · Fireworks · Xiaomi MiMo

**En tu máquina, sin clave:** Ollama · LM Studio

**Cualquier otra cosa:** elige *Something else* y dale una URL base. Cualquier
endpoint compatible con OpenAI funciona.

---

## Ejecutarlo localmente, gratis

```bash
ollama pull qwen2.5-coder:14b
comodor setup           # choose Ollama
```

Sin clave, sin costo, sin red. Un modelo de código de 14B es de verdad
utilizable para el trabajo diario; la diferencia aparece en tareas largas de
varios pasos.

---

## Cambiar

```bash
comodor --model claude-haiku-4-5      # this run only
```

```
/model                  # a list of what the provider offers
/model gpt-4o           # by name
/provider               # a different provider entirely
```

El medidor de contexto sigue al modelo. Cambiar de un modelo de un millón de
tokens a uno de 128k cambia el límite de inmediato — lo cual importa, porque el
agente compacta la conversación a una fracción de él, y un límite
desactualizado significa que nunca compacta y luego falla en el techo real del
proveedor.

Para hacer permanente un cambio: `/save`, o edita
`~/.comodor/config.json`.

---

## Claves

Cualquiera de los dos lugares funciona, y ninguno se copia al otro:

```json
{ "providers": { "anthropic": { "api_key": "sk-ant-…" } } }
```

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

Una clave en tu entorno **se queda ahí** — `/save` no la escribirá al disco.
Exportarla en lugar de guardarla es una decisión, y se respeta.

El archivo de configuración propio de Comodor se escribe con permisos solo para
el propietario, y tu clave nunca aparece en un log, una transcripción, una
exportación o un traceback. [Seguridad](safety.md#your-keys).

---

## El gateway

Enruta entre varios proveedores en lugar de fijar uno.

```
/gw                    # or F5
```

```json
{
  "gateway": {
    "enabled": true,
    "policy": "quality",
    "chain": ["anthropic", "openrouter", "deepseek"],
    "failure_threshold": 3
  }
}
```

`policy` es `cost`, `speed` o `quality`. Un proveedor que falla tres veces
seguidas se salta durante un minuto. La línea de estado muestra `GW: Quality`
cuando está activo, `GW: Disable` cuando no.

---

## Visión

Algunas herramientas devuelven imágenes — `browse look`, y cada captura de
`computer`. Esas necesitan un modelo que pueda ver. Todos los Claude y la
familia GPT-4o actuales pueden; la mayoría de los modelos abiertos no.

Si piensas usar [la pantalla](computer.md), comprueba primero que el modelo
tenga ojos, o le entregarán una imagen que no puede leer y adivinará.

---

## Cuánto cuesta

```
/cost
```

Ver [Costo](cost.md) para caché, presupuestos y por qué un límite de gasto a
veces no se puede aplicar.
