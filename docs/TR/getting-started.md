# Başlangıç

Beş dakika, ajanın işe yarar bir şey yapmasıyla sona eriyor.

---

## 1. Kurulum

Tek satır. Gerisini o hallediyor.

**macOS · Linux · BSD**

```bash
curl -fsSL get.comodor.ai | sh
```

**Windows** — PowerShell

```powershell
irm get.comodor.ai | iex
```

```
Comodor — it learns the way you correct it.

  Linux x86_64
> Installing uv, a package manager Comodor needs (about 15 MB)
  from https://astral.sh/uv — it fetches a Python too, if one is missing
> Installing with uv

✓ comodor 0.9.0

  Linked into /usr/local/bin, which is on your PATH.

  comodor              start the interface
  comodor --demo       try it offline, no API key needed
  comodor doctor       check what is configured
```

**İkisi için de tek adres.** `get.comodor.ai` bir dosya adı belirtmez. Hangi
istemcinin sorduğunu okur ve `curl` ile `wget`'i kabuk yükleyicisine,
PowerShell'i Windows yükleyicisine, tarayıcıyı da bu sayfaya yönlendirir —
böylece yapıştırdığınız satır her sistemde aynı satırdır ve seçim yapmak
zorunda kalmazsınız.

**Tamamlar.** Bir web sayfasından tek satır çalıştıran biri hiçbir şeyi hata
ayıklamayı kabul etmemiştir, bu yüzden betik neye ihtiyacı varsa onu kurar —
izole bir ortam, bir paket yöneticisi, bir Python — zaten sahip olmanız
gerekenleri açıklamak için durup beklemek yerine. Üzerinde hiç Python
olmayan çıplak bir `debian:bookworm-slim` üzerinde doğrulanmıştır.

### Sonrasında yazacak bir şey kalmaması, neredeyse her zaman

Nereye olursa `comodor`'u kabuğunuzun çoktan baktığı bir yere koyar, böylece
çalıştırdığınız terminalde çalışır — `export` yok, yeni pencere yok. Bu,
root'u, konteynerleri, CI'ı ve Homebrew'lu her Mac'i kapsar.

Yapamadığı yerde — `PATH` üzerindeki hiçbir şeyin yazılabilir olmadığı sıradan
bir Linux hesabı — hiçbir yükleyici yardımcı olamaz, çünkü bir alt süreç,
onu çalıştıran kabuğun ortamını değiştiremez. Bu yüzden durumu söyler:

```
  Every new terminal can run comodor already.
  This one started before the install, and no installer
  can reach back into the shell that ran it. For this
  terminal only:

    export PATH="/home/you/.local/bin:$PATH"
```

Yeni bir terminal açın ve artık çalışır. Satır hem kabuğunuzun rc dosyasına
hem de oturum açma profilinize yazılır, böylece her tür kabuk onu bulur —
etkileşimli, oturum açma, etkileşimsiz ve bir masaüstü oturumu.

### Bir betiği kabuğa boru etmektense

Tamamen makul. İki betik de önce okuyabileceğiniz düz metindir — doğrudan
adlandırılmış, çünkü kısa adres, bir getirici olmayan her şeyi sayfaya
gönderir:

```bash
curl -fsSL https://comodor.ai/install.sh  | less
curl -fsSL https://comodor.ai/install.ps1 | less
```

Ya da zaten sahip olduğunuz bir paket yöneticisini kullanın:

```bash
uv tool install comodor      # isolated, and the fastest
pipx install comodor         # isolated
pip install comodor          # into whatever environment you are in
```

Comodor'un **Python 3.11 veya daha yenisi** gerekir, başka hiçbir şey değil.

### Geldiğini kontrol edin

```bash
comodor --version
```

Kabuk bulamazsa, yükleyici `PATH`'inize bu terminalin henüz bilmediği bir
dizin eklemiştir. Yeni bir tane açın ya da yükleyicinin yazdırdığı `export`
satırını çalıştırın.

### Yükleyicilerin anladığı seçenekler

| | |
|---|---|
| `COMODOR_FORCE_TOOL` | yöntemi sabitle: `uv`, `pipx`, `venv` veya `pip` |
| `COMODOR_NO_BOOTSTRAP` | asla araç indirme; bunun yerine başarısız ol |
| `COMODOR_NO_MODIFY_PATH` | kabuk profilinize dokunma |
| `COMODOR_INSTALL_REF` | PyPI yerine bir git ref veya yerel yoldan kur |

```bash
COMODOR_NO_MODIFY_PATH=1 curl -fsSL get.comodor.ai | sh
```

> **Henüz kurmak istediğinize emin değil misiniz?** `comodor --demo`, arayüzün
> tamamını betiklenmiş bir çevrimdışı sağlayıcıya karşı çalıştırır. Anahtar
> yok, hesap yok, ağ yok.

---

## 2. Bir model seçin

Çalıştırın. İlk seferde altı soru sorar ve bir daha asla sormaz.

```bash
comodor
```

```
 1/6  Which model provider?
┌─  Providers  ───────────────────────────────────────────┐
│ ›  OpenRouter        One key, hundreds of models         │
│    Anthropic         Claude, direct from the source      │
│    OpenAI            GPT models, direct                  │
│    Ollama (local)    Runs on your machine. No key        │
└──────────────────────────────────────────────────────────┘
  ↑↓ move   enter choose   tab more   esc cancel
```

Ok tuşları ya da filtrelemek için yazın. **Tab**, okun üzerinde olduğu
şeyin tam açıklamasını aynı çerçevede açar — listeler ekrana sığmak için
satır başına bir satır gösterir ve bu açıklamaların bazıları bir paragraf
uzunluğundadır.

Boruyla aktarıldığında veya betiklendiğinde aynı sorular numaralı bir liste
olarak gelir, böylece otomatikleştirilebilir.

**Ne anahtar ne para mı var?** **Ollama** veya **LM Studio**'yu seçin.
Makinenizde çalışırlar, anahtar gerekmez ve hiçbir şeye mal olmazlar. Bu
belgelerdeki her şey onlarla çalışır, aksini söyleyen kısımlar hariç.

**Zaten OpenClaw veya Hermes mi kullanıyorsunuz?** İlk ekran anahtarlarınızı,
modelinizi ve skill'lerinizi taşımayı önerir. Hiçbir şey taşınmaz ve burada
halihazırda ayarlanmış hiçbir şey değiştirilmez. Bkz.
[Başka bir ajandan geçiş](migrating.md).

Cevaplarınız `~/.comodor/config.json` dosyasına gider, yalnızca siz
okuyabilirsiniz. Fikrinizi sonra `comodor setup` ile değiştirin ya da tek
tek ayarlayın — bkz. [Yapılandırma](configuration.md).

### Son soru telefonunuz

```
 6/6  Run it from your phone?
┌─  From your phone  ─────────────────────────────────────────────┐
│ ›  Not now    you can set any of them up later                   │
│    Telegram   one token from @BotFather — about a minute         │
│    Slack      an app from a manifest, two tokens — five minutes  │
│    WhatsApp   a Meta app and a public address — twenty minutes   │
└──────────────────────────────────────────────────────────────────┘
```

**Telegram**, [@BotFather](https://t.me/botfather)'dan bir token alır, orada
Telegram'a karşı hemen doğrular ve bota hangi hesabı yanıtlayacağını
bildirmek için gönderilecek bir kod gösterir — baştan sona bir dakika.
Bkz. [Telefonunuzdan](telegram.md).

**Slack** yaklaşık beş dakika sürer. Uygulama, Comodor'un yazdırdığı bir
manifest'ten oluşturulur, yani bir sayfalık onay kutusu yerine tek bir
yapıştırmadır ve Socket Mode hiçbir herkese açık adres gerekmediği anlamına
gelir — bkz. [Slack'ten](slack.md).

**WhatsApp** aynı şeyi yapar ve yaklaşık yirmi dakika sürer: bir Meta
uygulaması, bir iş numarası, bir uygulama sırrı ve bir herkese açık HTTPS
adresi — bunların hiçbiri bir terminalden yapılamaz. Sadece WhatsApp
olmak zorundaysa değer — bkz. [WhatsApp'tan](whatsapp.md).

Her iki durumda da siz aksini söyleyene kadar yalnızca okur ve plan yapar,
reddetmek tek bir tuş basımına mal olur.

### Ve sonra başlamayı önerir

```
 What now?
   1  Start Comodor          — the interface, here in this terminal
   2  Start the Telegram bot — in the background, answers while this is closed
   3  Both
   4  Nothing yet            — `comodor` starts it whenever you want
```

Kurulum eskiden burada biterdi, hiçbir şey çalışmadan tekrar kabuk
istemcinizde. Bağlanmış ve eşleştirilmiş her kanal için, adıyla bir telefon
satırı görünür — WhatsApp kuran birine "Telegram botu" önerilmez.

---

## 3. Hangi klasörü sorar

```
  Work in  /home/you/projects/api-server ?
```

Klasör başına bir kez sorulur. Ajanın dokunabileceği her şey onun
altındadır — siz bunu bilinçli olarak kapatmadıkça dışarıyı okuyamaz ya da
yazamaz. Onaylanan klasörler hatırlanır.

---

## 4. Bir şey isteyin

Yazın ve Enter'a basın.

```
> the tests in tests/test_parser.py are failing, work out why and fix it
```

Dosyaları okuyacak, testleri çalıştıracak ve bir şeyi değiştirecek. Bir
dosyaya yazmadan önce size bir fark (diff) ve bir seçenek sunar:

```
  Write  src/parser.py
    - 12 lines removed, 8 added
  [a] allow   [A] allow always this session   [d] deny
```

Bir kez `a` ile yanıtlayın, ya da oturumun geri kalanında sormayı bırakmasını
tercih ediyorsanız `A` ile. Her iki durumda da her yazma işlemi
checkpoint'lenir: `/undo` sonuncuyu geri koyar.

---

## 5. Düzeltin — işin asıl önemli kısmı bu

Bir şeyi yanlış yaptığında, ona söyleyin. İki yol var ve ikisi de ona aynı
şeyi öğretir:

**Dosyayı kendiniz düzenleyin.** Comodor, çıktısında neyi değiştirdiğinizi
fark eder.

**Söyleyin.**

```
> no — we use single quotes in this codebase, not double
```

Her iki durumda da bu bir ders olur: durum benzer göründüğünde bir sonraki
sefer hatırlanır, tuttuğunda güveni yükselir ve tutmadığında azalır.

Birkaç oturumdan sonra:

```
> /progress
```

```
◈ Corrections per task down 100% since the first tasks in this project.

metric                trend                       now  vs first
Steps per task        ▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇    6.1      ↑10%
Corrections per task  ████████▅▅▅▅▅▅▅▅▁▁▁▁▁▁▁▁    0.0     ↓100%
Approvals asked       ▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅    2.0         —
Tokens per task       ▁▁▁▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▇▇▇███  12.0K      ↑40%
First-try success     ▁██████▁██████▁██████▁██    86%         —

brain    7 rules · 812 lessons · 24 corrections learned from
history  24 tasks over 8 days
success  83% overall
```

Bu bir iddia değil, kanıttır. Düzeltme oranı düşmüyorsa öğrenme çalışmıyor
demektir ve panel bunu gizlemek yerine söyler.

[Nasıl öğrenir](learning.md) mekanizmayı açıklar.

---

## 6. İlk gün bilinmesi gerekenler

```
/help          every command
/mode          act · plan (read-only) · chat (no tools)     F3 cycles
/undo          restore the last file it changed
/cost          tokens, spend, what the cache saved
Esc            stop it, mid-thought
Ctrl-C twice   leave
```

---

## Bundan sonrası

| Ne istiyorsanız | Okuyun |
|---|---|
| Arayüz olmadan, bir betik içinde kullanmak | [Terminalden](cli.md) |
| Makinenizde tam olarak neler yapabildiğini bilmek | [Güvenlik ve izinler](safety.md) |
| Daha az ödemek | [Maliyet](cost.md) |
| Bir tarayıcı kullanmasına izin vermek | [Gerçek tarayıcı](browser.md) |
| Farenizi ve klavyenizi kullanmasına izin vermek | [Ekranınızı kullanması](computer.md) |
| Her seferinde izlediği bir prosedür yazmak | [Skill'ler](skills.md) |
| Bir sunucuda veya Docker'da çalıştırmak | [Bir tarayıcıdan](web.md), [Docker'da](docker.md) |

---

## Bir şey ters gittiyse

```bash
comodor doctor
```

Kontrol edebildiği her şeyi kontrol eder ve bulduğu her şey için ne
yapmanız gerektiğini söyler. `comodor doctor --fix`, onarılabilir olanları
onarır. Bkz. [Sorun giderme](troubleshooting.md).
