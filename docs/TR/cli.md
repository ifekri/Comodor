# Terminalden

Her komut ve bayrak, yapıştırabileceğiniz bir şeyle birlikte.

```bash
comodor help              # the written help page
comodor help computer     # one topic in more detail
```

---

## Kurulum ve güncelleme

```bash
curl -fsSL get.comodor.ai | sh     # macOS, Linux, BSD
```

```powershell
irm get.comodor.ai | iex          # Windows
```

`get.comodor.ai` bir dosya adı belirtmez: hangi istemcinin sorduğunu okur ve
o istemcinin çalıştırabileceği yükleyiciyle yanıt verir. Aynı tek satır,
var olan bir kurulumu günceller. Ya da makinenize girdikten sonra:

```bash
comodor update --check    # what is out there
comodor update            # move to it
```

[Geri kalanı](getting-started.md#1-install) [Başlangıç](getting-started.md)'ta —
paket yöneticileri ve yükleyicilerin kabul ettiği şeyler.

---

## Başlatmak

```bash
comodor                              # the interface
comodor --demo                       # the interface, offline, no key needed
comodor --resume                     # reopen the last session
comodor --resume 2026-08-22-a4f1     # reopen one by id
comodor --cwd ~/projects/api         # work somewhere other than here
comodor --model claude-sonnet-5      # a different model, this run only
comodor --mode plan                  # start read-only
```

### Seçenekler

| | |
|---|---|
| `--provider NAME` | `openrouter`, `anthropic`, `openai`, `ollama`, … |
| `--model ID` | bu çalıştırma için modeli geçersiz kıl |
| `--mode act\|plan\|chat` | plan salt okunurdur; chat'in aracı yoktur |
| `--no-loop` | bitene kadar çalışmak yerine bir kez yanıtla |
| `--cwd PATH` | dokunabileceği klasör |
| `--theme NAME` | `ember`, `midnight`, `matrix`, `mono` |
| `--ascii` | ASCII kenarlıklar |
| `--no-mouse` | fareyi terminale bırak |
| `--resume [ID]` | son oturum, ya da id ile bir oturum |
| `--demo` | betiklenmiş çevrimdışı sağlayıcı |
| `--version` | bu hangi sürüm |
| `-h`, `--help` | yazılı yardım sayfası |

Bunların hiçbiri yapılandırmanıza yazılmaz. Tek çalıştırmaya uygulanırlar.
Bir değişikliğin kalıcı olmasını istiyorsanız, arayüzün içinde `/save`
kullanın ya da yapılandırma dosyasını düzenleyin —
[Yapılandırma](configuration.md).

---

## `comodor run` — tek görev, arayüz yok

```bash
comodor run "fix the failing test in tests/test_parser.py"
comodor run "add type hints to src/parser.py" --yes
comodor run "what does this project do?" --json
comodor run "refactor the parser" --max-steps 40
```

| | |
|---|---|
| `--yes` | yazma işlemlerini ve komutları otomatik onayla |
| `--json` | stdout'ta makine tarafından okunabilir bir sonuç |
| `--max-steps N` | bu çalıştırma için adım sınırını geçersiz kıl |

`--yes` olmadan sorar, stderr üzerinde, ve hiçbir şey cevap veremiyorsa
varsaymak yerine reddeder. Bu kasıtlıdır: sessizce kendini onaylayan bir
betik, sabahın üçünde beklenmedik bir şey yapan bir betiktir.

`--json` size şunu verir:

```json
{
  "text": "Fixed. The parser raised on empty input rather than returning [\"\"] …",
  "ok": true,
  "stopped": "done",
  "steps": 6,
  "tool_calls": 11,
  "error": "",
  "usage": {
    "input_tokens": 18422,
    "output_tokens": 640,
    "cost_usd": 0.031
  },
  "elapsed": 24.71
}
```

`stopped`, neden bittiğini söyler — şunlardan biri:

| | |
|---|---|
| `done` | bittiğine kendisi karar verdi |
| `max_steps` | `agent.max_steps`'e çarptı |
| `budget` | `agent.max_cost_usd` veya `agent.max_seconds`'e çarptı |
| `cancelled` | siz onu yarıda kestiniz |
| `error` | bir şeyler ters gitti; `error` ne olduğunu söyler |

`ok`, `done` ve `max_steps` için doğrudur — adımların bitmesi bir başarısızlık
değil, tavanın işini yapmasıdır — bu yüzden farkı sizin bilmeniz
gerekiyorsa `stopped`'a da bakın:

```bash
comodor run "update the changelog for this release" --yes --json > result.json
jq -e '.stopped == "done"' result.json
```

Başsız (headless) bir çalıştırmadan da öğrenir. Sonrasında yaptığınız bir
düzeltme, etkileşimli bir çalıştırmanın öğreteceği dersi öğretir.

---

## `comodor setup` — bir sağlayıcı ve model seçin

```bash
comodor setup
```

Altı soru, ya da başka bir ajan kurulmuşsa ve içe aktarma öneriyorsa yedi.
İlk çalıştırmada otomatik olarak çalışır; fikrinizi sonradan değiştirmek
için bunu kullanın.

Cevaplar `~/.comodor/config.json` dosyasına gider.

---

## `comodor import` — OpenClaw veya Hermes'ten

```bash
comodor import             # bring keys, model and skills across
comodor import --dry-run   # say what it would take, change nothing
comodor import --keys-only # leave the skills and the model
```

Hiçbir şey taşınmaz ve burada halihazırda ayarlanmış hiçbir şey
değiştirilmez. Bkz. [Başka bir ajandan geçiş](migrating.md).

---

## `comodor doctor` — her şey yolunda mı?

```bash
comodor doctor
comodor doctor --fix
```

```
  ok    config file         ~/.comodor/config.json
  ok    config permissions  0o600
  ok    provider            Anthropic · claude-sonnet-5
  ok    model               claude-sonnet-5
  ok    spend limit         $2.00 per task
  ok    brain               ~/.comodor/brain.db
  ok    skills              4 loaded
  warn  version             0.8.9 installed; 0.9.0 is out
```

`--fix`, onarılabilir olanları onarır — eski bir sağlayıcı adı, eksik bir
dizin, bozuk bir arama dizini. Önce rapor etmediği hiçbir şeyi değiştirmez.

Bir şey başarısız olursa çıkış kodu sıfırdan farklıdır, bu yüzden bir sağlık
kontrolünde çalışır.

---

## `comodor web` — bir tarayıcıdan

```bash
comodor web                       # here, on 127.0.0.1:8765
comodor web --port 9000
comodor web --host 0.0.0.0        # reachable from elsewhere — read the warning
comodor web --no-browser          # do not open one
comodor web --token mytoken       # a fixed token instead of a fresh one
```

Tam rehber: [Bir tarayıcıdan](web.md).

---

## `comodor telegram` — telefonunuzdan

```bash
comodor telegram connect <token>  # a bot from @BotFather
comodor telegram pair             # a one-time code that adds your account
comodor telegram start            # here, holding this terminal
comodor telegram start -b         # detached; survives closing the terminal
comodor telegram stop             # end a background one
comodor telegram service install  # start it at login, so a reboot brings it back
comodor telegram service show     # read the unit before trusting it
comodor telegram status           # what is configured, who may talk, is it up
comodor telegram writes on        # let a phone turn edit files
comodor telegram writes off
comodor telegram forget 12345     # revoke one account
comodor telegram forget all
comodor telegram off              # stop without forgetting anything
```

İlk çalıştırma kurulumu bunların tümünü son soru olarak sunar; bunlar
sonradan değiştirmek ya da zaten kurulmuş bir makine içindir.

Tam rehber: [Telefonunuzdan](telegram.md).

---

## `comodor slack` — bir Slack çalışma alanından

```bash
comodor slack manifest            # the app definition to paste into Slack
comodor slack connect             # the two tokens, checked as you paste them
comodor slack pair                # a one-time code that adds your account
comodor slack start               # here, holding this terminal
comodor slack start -b            # detached
comodor slack stop
comodor slack service install     # start it at login
comodor slack status              # what is set, who may talk, is it running
comodor slack writes on           # let a Slack turn edit files
comodor slack forget U01234567
comodor slack off
```

Yaklaşık beş dakika, ve herkese açık adres yok: Socket Mode, uygulamanın
dışarı doğru bir websocket açmasını sağlar, kendisine gönderi yapılmasından
ziyade.

Tam rehber: [Slack'ten](slack.md).

---

## `comodor whatsapp` — bir WhatsApp numarasından

```bash
comodor whatsapp connect          # guided: links each page, checks each value
comodor whatsapp connect --number-id … --token … --app-secret …
comodor whatsapp webhook          # what to paste into Meta's dashboard
comodor whatsapp pair             # a one-time code that adds your number
comodor whatsapp start            # here, holding this terminal
comodor whatsapp start --tunnel   # and bring a Cloudflare tunnel up with it
comodor whatsapp start -b         # detached
comodor whatsapp stop
comodor whatsapp service install  # start it at login
comodor whatsapp status           # what is set, who may talk, is it running
comodor whatsapp writes on        # let a phone turn edit files
comodor whatsapp forget 15551234567
comodor whatsapp off
```

Meta, mesajları sizin yoklamanıza izin vermek yerine bir URL'ye teslim eder,
bu yüzden bu birine herkese açık bir HTTPS adresi gerekir. Argümansız
`connect`, tüm kurulumu yürütür ve tüneli kendi başlatır; ilk seferde
yaklaşık yirmi dakika, çoğu Meta'nın panelinde. Gerçek numara yok, kart
yok, işletme doğrulaması yok.

Tam rehber: [WhatsApp'tan](whatsapp.md).

---

## `comodor skills` — izlediği prosedürler

```bash
comodor skills browse             # what is available
comodor skills list               # what you have
comodor skills add review taste   # install some
comodor skills update             # refresh installed ones
comodor skills remove review
```

Tam rehber: [Skill'ler](skills.md).

---

## `comodor mcp` — Model Context Protocol sunucuları

```bash
comodor mcp list                  # what you have, and what it offers
comodor mcp catalogue             # what is available
comodor mcp add filesystem        # from the catalogue
comodor mcp custom NAME -- CMD    # a command of your own
comodor mcp remote NAME URL       # an HTTP server
comodor mcp enable NAME
comodor mcp disable NAME
comodor mcp remove NAME
comodor mcp test NAME             # connect and list its tools
```

Tam rehber: [MCP sunucuları](mcp.md).

---

## `comodor update` — en yeni sürüme geçin

```bash
comodor update --check     # what is out there, change nothing
comodor update             # do it
```

Bu kopyanın nasıl kurulduğunu anlar — `uv`, `pipx`, `pip` veya bir kaynak
çıkışı — ve doğru olanı kullanır. Bir kaynak çıkışı kendi haline bırakılır:
o sizindir.

---

## `comodor uninstall` — tamamen kaldırın

```bash
comodor uninstall --dry-run    # list what would go
comodor uninstall              # ask, then do it
comodor uninstall --yes        # for scripts
```

```
Your data
  everything it has learned and everything you told it     4.2 MB
    ~/.comodor
    settings and your API key · 812 lessons · 47 sessions · 4 skills

In your projects
  api-server                                               128 KB
    ~/projects/api-server/.comodor
    checkpoints, project settings, project skills

The program
  the uv installation
    ~/.local/share/uv/tools/comodor

4.3 MB across 3 places. None of it can be undone.
```

Bir şey kaldırmadan önce her şeyi adlandırır ve neyi bulamadığını söyler —
kullandığınız ama oturum geçmişi temizlenmiş bir projedeki `.comodor`
klasörü adlandırılamaz ve bunu size, öyleymiş gibi yapmadan söyler.

---

## `comodor preview` — arayüzün belirli bir boyutta görünümü

```bash
comodor preview 80x24
comodor preview 200x50 --svg wide.svg
```

Tek bir çerçeve oluşturur ve çıkar. Dar bir terminali kontrol etmek ya da
bir ekran görüntüsü almak için kullanışlıdır.

---

## Ortam değişkenleri

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, … | bir anahtar, sağlayıcı başına |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | bir sağlayıcı veya model zorla |
| `COMODOR_HOME` | yapılandırmanın, beynin ve oturumların yaşadığı yer |
| `COMODOR_BANNER=0` | bu çalıştırmada yazı logosu yok |
| `COMODOR_NO_IMPORT=1` | başka bir ajandan içe aktarmayı önerme |
| `COMODOR_WEB_TOKEN` | web arayüzü için sabit bir token |
| `NO_COLOR` | renk yok, her yerde dikkate alınır |

Ortamda bir anahtar **asla yapılandırma dosyanıza yazılmaz**. Bunu kaydetmek
yerine dışa aktarmak bir karardır ve `/save` buna saygı duyar. Bkz.
[Yapılandırma](configuration.md).

---

## Çıkış kodları

| | |
|---|---|
| `0` | işe yaradı |
| `1` | yaramadı |
| `130` | siz onu yarıda kestiniz |

---

## Ayrıca bakın

- [Arayüz](interface.md) — aynı güç, etkileşimli
- [Yapılandırma](configuration.md) — bir bayrağı kalıcı yapmak
- [Sorun giderme](troubleshooting.md) — bir komut dediğini yapmadığında
