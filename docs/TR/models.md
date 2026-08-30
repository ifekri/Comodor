# Model seçimi

Comodor, OpenAI veya Anthropic API'sinden konuşan her şeyle çalışır —
kutudan çıktığı gibi on yedi sağlayıcı, artı URL'si olan her başka şey.

---

## Kısa cevap

| İstediğiniz | Seçin |
|---|---|
| En kolay başlangıç, tek anahtar, her şey | **OpenRouter** |
| En güçlü ajansal iş | **Anthropic**, `claude-sonnet-5` |
| Hiçbir şey ödememek ve çevrimdışı kalmak | **Ollama** veya **LM Studio** |
| Çok ucuz, kodda iyi | **DeepSeek** |
| Çok hızlı | **Groq** veya **Cerebras** |

```bash
comodor setup        # pick one, once
```

---

## Her sağlayıcı

**Barındırılan, tek anahtar:** OpenRouter · Anthropic · OpenAI · Google Gemini ·
DeepSeek · xAI · Mistral · Groq · Cerebras · Moonshot (Kimi) · Z.AI (GLM) ·
Qwen · Together · Fireworks · Xiaomi MiMo

**Makinenizde, anahtar yok:** Ollama · LM Studio

**Başka herhangi bir şey:** *Something else*'i seçin ve ona bir base URL
verin. OpenAI uyumlu herhangi bir uç nokta çalışır.

---

## Yerel çalıştırma, bedava

```bash
ollama pull qwen2.5-coder:14b
comodor setup           # choose Ollama
```

Anahtar yok, maliyet yok, ağ yok. 14B'lik bir kodlayıcı model günlük iş için
gerçekten kullanılabilir; fark, uzun çok adımlı görevlerde ortaya çıkar.

---

## Değiştirme

```bash
comodor --model claude-haiku-4-5      # this run only
```

```
/model                  # a list of what the provider offers
/model gpt-4o           # by name
/provider               # a different provider entirely
```

Bağlam göstergesi modeli takip eder. Milyon tokenlik bir modelden 128k'lık
birine geçmek sınırı anında değiştirir — bu önemlidir, çünkü ajan konuşmayı
sınırın bir kesrinde sıkıştırır ve eski bir sınır, hiç sıkıştırmayıp sonra
sağlayıcının gerçek tavanında başarısız olmak demektir.

Bir değişikliği kalıcı yapmak için: `/save` ya da
`~/.comodor/config.json`'ı düzenleyin.

---

## Anahtarlar

Her iki yer de çalışır ve hiçbiri diğerine kopyalanmaz:

```json
{ "providers": { "anthropic": { "api_key": "sk-ant-…" } } }
```

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

Ortamınızdaki bir anahtar **orada kalır** — `/save` onu diske yazmaz.
Kaydetmek yerine dışa aktarmak bir karardır ve buna saygı duyulur.

Comodor'un kendi yapılandırma dosyası yalnızca sahibine açık izinlerle
yazılır ve anahtarınız hiçbir zaman bir günlükte, bir transkriptte, bir
dışa aktarmada veya bir traceback'te görünmez.
[Güvenlik](safety.md#your-keys).

---

## Gateway

Birini sabitlemek yerine birkaç sağlayıcı arasında yönlendirin.

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

`policy`, `cost`, `speed` veya `quality`'dir. Üst üste üç kez başarısız olan
bir sağlayıcının bir dakika boyunca yanından geçilir. Durum satırı, açıkken
`GW: Quality`, değilken `GW: Disable` gösterir.

---

## Görüntü (vision)

Bazı araçlar resimler döndürür — `browse look` ve her `computer` ekran
görüntüsü. Bunlar görebilen bir model gerektirir. Güncel Claude ve GPT-4o
ailesinin tamamı görebilir; açık modellerin çoğu göremez.

[Ekranı](computer.md) kullanmayı planlıyorsanız, önce modelin gözleri
olduğunu kontrol edin, yoksa okuyamayacağı bir resim verilir ve tahmin
eder.

---

## Neye mal olur

```
/cost
```

Önbellekleme, bütçeler ve bir harcama sınırının bazen neden uygulanamadığı
için bkz. [Maliyet](cost.md).
