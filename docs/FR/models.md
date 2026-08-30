# Choisir un modèle

Comodor fonctionne avec tout ce qui parle l'API OpenAI ou Anthropic — dix-sept
fournisseurs fournis, plus tout autre avec une URL.

---

## La réponse courte

| Vous voulez | Choisissez |
|---|---|
| Le démarrage le plus simple, une clé, tout | **OpenRouter** |
| Le travail agentique le plus solide | **Anthropic**, `claude-sonnet-5` |
| Ne rien payer et rester hors ligne | **Ollama** ou **LM Studio** |
| Très bon marché, doué pour le code | **DeepSeek** |
| Très rapide | **Groq** ou **Cerebras** |

```bash
comodor setup        # pick one, once
```

---

## Chaque fournisseur

**Hébergés, une clé :** OpenRouter · Anthropic · OpenAI · Google Gemini ·
DeepSeek · xAI · Mistral · Groq · Cerebras · Moonshot (Kimi) · Z.AI (GLM) ·
Qwen · Together · Fireworks · Xiaomi MiMo

**Sur votre machine, sans clé :** Ollama · LM Studio

**Tout le reste :** choisissez *Something else* et donnez-lui une URL de base.
Tout point de terminaison compatible OpenAI fonctionne.

---

## Le faire tourner en local, pour rien

```bash
ollama pull qwen2.5-coder:14b
comodor setup           # choose Ollama
```

Pas de clé, pas de coût, pas de réseau. Un modèle de code 14B est réellement
utilisable pour le travail quotidien ; la différence apparaît sur les longues
tâches multi-étapes.

---

## Changer

```bash
comodor --model claude-haiku-4-5      # this run only
```

```
/model                  # a list of what the provider offers
/model gpt-4o           # by name
/provider               # a different provider entirely
```

La jauge de contexte suit le modèle. Passer d'un modèle à un million de tokens
à un modèle 128k change la limite immédiatement — ce qui compte, car l'agent
compacte la conversation à une fraction de celle-ci, et une limite périmée
signifie qu'il ne compacte jamais puis échoue au vrai plafond du fournisseur.

Pour rendre un changement permanent : `/save`, ou éditez
`~/.comodor/config.json`.

---

## Clés

L'un ou l'autre endroit fonctionne, et rien n'est copié de l'un vers l'autre :

```json
{ "providers": { "anthropic": { "api_key": "sk-ant-…" } } }
```

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

Une clé dans votre environnement **y reste** — `/save` ne l'écrira pas sur le
disque. L'exporter plutôt que la sauvegarder est une décision, et elle est
respectée.

Le fichier de configuration propre à Comodor est écrit avec des permissions
réservées au propriétaire, et votre clé n'apparaît jamais dans un journal, une
transcription, un export ou une trace d'erreur.
[Sécurité](safety.md#your-keys).

---

## La passerelle

Router entre plusieurs fournisseurs au lieu d'en figer un.

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

`policy` vaut `cost`, `speed` ou `quality`. Un fournisseur qui échoue trois fois
de suite est contourné pendant une minute. La ligne d'état affiche
`GW: Quality` quand il est actif, `GW: Disable` quand il ne l'est pas.

---

## Vision

Certains outils renvoient des images — `browse look`, et chaque capture
d'écran `computer`. Cela exige un modèle capable de voir. Toute la famille
Claude et GPT-4o actuelle le peut ; la plupart des modèles ouverts non.

Si vous prévoyez d'utiliser [l'écran](computer.md), vérifiez d'abord que le
modèle a des yeux, sinon une image qu'il ne peut pas lire lui sera remise et
il devinera.

---

## Ce que cela coûte

```
/cost
```

Voir [Coût](cost.md) pour le cache, les budgets, et pourquoi une limite de
dépense ne peut parfois pas être appliquée.
