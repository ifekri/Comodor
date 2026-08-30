# Yapılandırma

El ile düzenlemenize hiç gerek olmayan tek bir JSON dosyası — ama işte içindeki her şey.

---

## Şeylerin yaşadığı yer

| | |
|---|---|
| `~/.comodor/config.json` | sizin. Sihirbaz yazar; yalnızca sahibine açık izinler |
| `~/.comodor/brain.db` | ne öğrendiği |
| `~/.comodor/sessions/` | her konuşma |
| `~/.comodor/skills/` | kurduğunuz veya yazdığınız skill'ler |
| `./.comodor/config.json` | projenin. Commit'lenebilir — bkz. [neyi ayarlayabilir](safety.md#what-a-repository-may-set) |
| `./.comodor/checkpoints/` | değiştirdiği her dosyanın önceki içeriği |

Windows'ta `~/.comodor`, `%APPDATA%\Comodor`'dur. `COMODOR_HOME`, her yerde
bunu geçersiz kılar.

```bash
comodor doctor      # tells you exactly where all of these are
```

---

## Hangisi geçerli

Dört katman. Sonrakiler öncekileri yener.

```
1. built-in defaults
2. ~/.comodor/config.json         yours
3. ./.comodor/config.json         the project's — restricted
4. environment variables          ANTHROPIC_API_KEY, COMODOR_MODEL, …
5. the command line               --model, --mode, … for one run
```

### `/save` ne yazar

**Yalnızca seçtiklerinizi.** Kulağa geldiğinden daha önemli.

Ajanın üzerinde çalıştığı yapılandırma, dört katmanın tümünün
birleştirilmişidir. Bunun dosyanıza geri yazılması, klonlanmış bir deponun
harcama tavanını kalıcı küresel varsayılanınız yapar ve bilinçli olarak
ortamınızda tuttuğunuz bir API anahtarını diske kopyalar.

Bu yüzden `/save` her değerin nereden geldiğini hatırlar. Ödünç alınmış bir
katmanın sağladığı ne varsa hâlâ tutan bir değer, *sizin* dosyanızın
söylediğine geri döner; oturum sırasında değiştirdiğiniz bir değer sizindir
ve yazılır.

- `/model x` sonra `/save` → `x`'i kalıcılaştırır
- `max_cost_usd: 500` sabitleyen bir depoda `/save` → bu türden hiçbir şeyi
  kalıcılaştırmaz
- `ANTHROPIC_API_KEY` dışa aktarılmışken `/save` → anahtar ortamınızda kalır

---

## Her ayar

### `provider` ve `model`

```json
{ "provider": "anthropic", "model": "claude-sonnet-5" }
```

Bkz. [Model seçimi](models.md).

### `agent` — nasıl çalıştığı

```json
{
  "agent": {
    "mode": "act",
    "loop": true,
    "max_steps": 0,
    "max_seconds": 3600.0,
    "max_cost_usd": 2.0,
    "context_limit": 1000000,
    "compact_at": 0.75,
    "temperature": 0.3,
    "max_output_tokens": 8192,
    "max_tool_chars": 12000,
    "keep_screenshots": 2,
    "system_prompt_extra": "",
    "prompt_cache": true,
    "prompt_cache_ttl": "5m"
  }
}
```

| | |
|---|---|
| `mode` | `act`, `plan` (salt okunur), `chat` (araç yok) |
| `loop` | bitene kadar çalışmaya devam et, ya da bir kez yanıtla |
| `max_steps` | **`0` — sınır yok ve varsayılan budur.** Bir düzine dosyaya yayılan bir yeniden düzenleme (refactor), düşünüşünün ortasında yirmi dört adıma takıldı ve adım sayısının zararla hiçbir ilgisi yoktur. Geri getirmek için bir sayı ayarlayın |
| `max_seconds` | bir saat. Sınır yok için `0` |
| `max_cost_usd` | ters giden şeyin maliyetine denk gelen tavan — [modelin yayımlanmış oranı olduğu yerde](cost.md#when-the-limit-cannot-fire). Sınır yok için `0` |
| `context_limit` | gösterge. Değiştirdiğinizde modeli otomatik takip eder |
| `compact_at` | bu kesrin ötesinde geçmişe özet çıkar |
| `max_tool_chars` | bir araç sonucunun ne kadarının modele ulaştığı. Gerisi, nasıl okunacağı söylenen bir dosyaya yazılır — kırpılmaz |
| `keep_screenshots` | kaç tanesi konuşmada kalır. [Neden](computer.md#screenshots-and-what-they-cost) |
| `system_prompt_extra` | sizin sürekli talimatlarınız |
| `prompt_cache` | sağlayıcının değişmeyen öneki yeniden sunmasına izin ver. [Maliyet](cost.md) |
| `prompt_cache_ttl` | `5m` veya `1h`. Saatlik olan yazması daha pahalıdır |

### `safety` — ne yapabilir

```json
{
  "safety": {
    "auto_approve_safe": true,
    "auto_approve_writes": false,
    "auto_approve_shell": false,
    "checkpoints": true,
    "workspace_only": true,
    "allow_commands": [],
    "deny_commands": ["rm -rf /", "..."],
    "max_file_read_bytes": 512000,
    "max_file_scan_bytes": 64000000,
    "trusted_folders": []
  }
}
```

Tam açıklama: [Güvenlik ve izinler](safety.md).

### `learning` — neyi hatırladığı

```json
{
  "learning": {
    "enabled": true,
    "top_k": 6,
    "max_playbook_tokens": 800,
    "reflect": true,
    "reflect_model": "",
    "min_confidence": 0.15,
    "half_life_days": 45.0,
    "share_scope": "project",
    "associative": true,
    "corrections": true,
    "rules": true,
    "announce": true,
    "prefetch": true
  }
}
```

| | |
|---|---|
| `top_k` | tur başına hatırlanan ders sayısı |
| `max_playbook_tokens` | hatırlamanın enjekte edebileceğine sert üst sınır |
| `reflect` | bir görevden sonra dersleri damıtır — bu bir model çağrısına mal olur |
| `reflect_model` | bunun için daha ucuz bir model, isterseniz |
| `half_life_days` | kullanılmayan bir dersin ne kadar hızlı solması |
| `share_scope` | `project` veya `global` |
| `corrections`, `rules`, `announce`, `prefetch` | hızlı şerit — ücretsiz, model çağrısı yok, `reflect` kapalıyken bile açık |

Tam açıklama: [Nasıl öğrenir](learning.md).

### `ui` — nasıl göründüğü

```json
{
  "ui": {
    "theme": "ember",
    "ascii_borders": false,
    "mouse": true,
    "max_fps": 20,
    "show_timestamps": false,
    "sidebar": true,
    "banner": true,
    "syntax_theme": ""
  }
}
```

`banner: false` yazı logosunu kalıcı olarak kapatır; `COMODOR_BANNER=0` bunu
tek bir çalıştırma için yapar.

### `skills` — prosedürler

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000,
    "install_examples": true
  }
}
```

Tam açıklama: [Skill'ler](skills.md).

### `telegram` — telefonunuzdan

```json
{
  "telegram": {
    "enabled": false,
    "token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300
  }
}
```

| | |
|---|---|
| `enabled` | `comodor telegram start`'in botu çalıştırıp çalıştırmadığı |
| `token` | [@BotFather](https://t.me/botfather)'dan. İlk çalıştırma kurulumu onu sorar ya da `comodor telegram connect` |
| `allowed` | cevapladığı sayısal Telegram kullanıcı id'leri, başka kimse değil. `comodor telegram pair` tarafından doldurulur, asla Telegram'ın kendisinden değil |
| `allow_writes` | telefondan başlayan bir turun dosya düzenleyip komut çalıştırıp çalıştıramayacağı. Kapalıyken, terminal ne şekilde ayarlı olursa olsun onu plan modunda tutar |
| `pair_window` | bir eşleştirme kodunun geçerli kaldığı saniyeler |

**Bir projenin `.comodor/config.json` dosyası bunların hiçbirini ayarlayamaz.**
`allowed`'a bir hesap ekleyebilen bir depo bir arka kapı olurdu ve tarayıcı
veya ekranın aksine, bu olurken görünürde hiçbir şey olmazdı.

Tam açıklama: [Telefonunuzdan](telegram.md).

### `slack` — bir Slack çalışma alanından

```json
{
  "slack": {
    "enabled": false,
    "bot_token": "",
    "app_token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300,
    "team": ""
  }
}
```

| | |
|---|---|
| `bot_token` | OAuth & Permissions'tan `xoxb-…`. Botun yaptığı her şeyi yapar |
| `app_token` | Basic Information'dan `xapp-…`, scope `connections:write`. Socket Mode websocket'ini açar, başka hiçbir şey değil |
| `allowed` | cevapladığı Slack kullanıcı id'leri. Görünen adlar değil: bir görünen adı, o adı elinde tutan kişi değiştirebilir |
| `allow_writes` | Bir Slack turunun dosya düzenleyip komut çalıştırıp çalıştıramayacağı |
| `pair_window` | Bir eşleştirme kodunun geçerli kaldığı saniyeler |
| `team` | Bağlandığı çalışma alanı; `status`'ün gidiş-dönüş yapmadan adlandırabilmesi için hatırlanır |

**Bir projenin `.comodor/config.json` dosyası bunların hiçbirini
ayarlayamaz**, diğerleriyle aynı nedenle: `allowed`'a bir hesap ekleyebilen
bir depo bir arka kapı olurdu.

Tam açıklama: [Slack'ten](slack.md).

### `whatsapp` — bir WhatsApp numarasından

```json
{
  "whatsapp": {
    "enabled": false,
    "token": "",
    "phone_number_id": "",
    "app_secret": "",
    "verify_token": "",
    "allowed": [],
    "allow_writes": false,
    "host": "127.0.0.1",
    "port": 8770,
    "path": "/whatsapp",
    "public_url": "",
    "api_version": "v21.0"
  }
}
```

| | |
|---|---|
| `token` | Bir Meta erişim tokeni. Bir System User tokeni süresizdir; panelin kendi tokeni 24 saat sürer |
| `phone_number_id` | Meta'nın numaranın yanında gösterdiği sayısal id, numaranın kendisi değil |
| `app_secret` | Her webhook onunla imzalanır. Olmadığında hiçbir şey doğrulanmaz |
| `verify_token` | Meta'nın tek seferlik el sıkışması sırasında geri yansıtılır. Üretilir, seçilmez |
| `allowed` | cevapladığı numaralar, rakamlar olarak karşılaştırılır. Diğer herkes sessizlik alır |
| `allow_writes` | Bir WhatsApp turunun dosya düzenleyip komut çalıştırıp çalıştıramayacağı |
| `host`, `port`, `path` | Webhook'un dinlediği yer. Localhost, TLS'i sonlandıran bir şeyin arkasında |
| `public_url` | Meta'nın teslim ettiği adres; `whatsapp webhook`'un yazdırabilmesi için hatırlanır |
| `api_version` | Sabitlenmiştir, çünkü Meta sürümleri sizin takviminize göre değil kendi takvimlerine göre kullanımdan kaldırır |

**Bir projenin `.comodor/config.json` dosyası bunların hiçbirini
ayarlayamaz**, `telegram` ile aynı nedenle: `allowed`'a bir numara ekleyebilen
bir depo, gerçekleştiğini ekranda gösteren hiçbir şeyin olmadığı bir arka kapı
olurdu.

Tam açıklama: [WhatsApp'tan](whatsapp.md).

### `browser` — gerçek tarayıcı

```json
{
  "browser": {
    "executable": "",
    "headless": true,
    "width": 1280,
    "height": 800,
    "port": 0
  }
}
```

`headless: false`, çalışmasını izlemenin yoludur. `port`, kendiniz
başlattığınız bir tarayıcıya bağlanır; böylece size profilinizin verilmesi
yerine zaten oturum açtığınız bir oturumu kullanabilir.

Tam açıklama: [Gerçek tarayıcı](browser.md).

### `computer` — ekranınız

```json
{
  "computer": {
    "enabled": false,
    "screenshot_tokens": 1600,
    "grant_seconds": 900,
    "travel_seconds": 0.32,
    "overlay": true,
    "never": []
  }
}
```

Tam açıklama: [Ekranınızı kullanması](computer.md).

### `gateway` — sağlayıcılar arasında yönlendirme

```json
{
  "gateway": {
    "enabled": false,
    "policy": "quality",
    "chain": [],
    "failure_threshold": 3,
    "cooldown_seconds": 60.0
  }
}
```

`policy`, `cost`, `speed` veya `quality`'dir. `enabled: true` ile `chain`'den
seçer ve sürekli başarısız olan bir sağlayıcının yanından geçer. Arayüzde
`F5` veya `/gw`.

### `mcp` — Model Context Protocol sunucuları

```json
{
  "mcp": {
    "enabled": true,
    "servers": { }
  }
}
```

El ile değil, `comodor mcp` ile yönetilir. [MCP sunucuları](mcp.md).

---

## Ortam değişkenleri

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, … | sağlayıcı başına bir tane |
| `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODEL` | bir uç noktayı veya modeli geçersiz kıl |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | ikisinden birini zorla |
| `COMODOR_HOME` | her şeyin yaşadığı yer |
| `COMODOR_BANNER=0` | yazı logosu yok |
| `COMODOR_NO_IMPORT=1` | başka bir ajandan içe aktarmayı önerme |
| `COMODOR_WEB_TOKEN` | web arayüzü için sabit bir token |
| `NO_COLOR` | renk yok |

---

## Bir ayar etkili olmadığında

Comodor, sizi yok saymak yerine durumu söyler:

```
config: agent.max_steps must be a whole number; keeping 24
config: this project cannot set safety, computer — only your own can
```

Yanlış türde bir değer, durumu belirsiz değilse dönüştürülür, belirsizse
reddedilir ve ret, anahtarı ve bekleneni adlandırır. `null`, sessizce bir
string'i `None` ile değiştirmez.

Bir ayar hâlâ hiçbir şey yapmıyorsa:

```bash
comodor doctor          # what it actually loaded
```

```
/settings               # the same, in the interface
```
