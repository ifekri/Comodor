# Sorun giderme

## Buradan başlayın

```bash
comodor doctor
```

Yapılandırma dosyasını ve izinlerini, sağlayıcıyı, modeli, harcama sınırını, beyni, arama dizinini, becerilerinizi, artık dosyaları, MCP sunucularını ve daha yeni bir sürüm olup olmadığını denetler.

```bash
comodor doctor --fix
```

onarılabilir olanları onarır. Önceden bildirmediği hiçbir şeyi değiştirmez.

---

## Başlamıyor

**`comodor: command not found`, kurulumdan hemen sonra** — kurucu onu `PATH`'inize koydu; ama bir alt süreç, onu başlatan kabuğun ortamını değiştiremez. Her *yeni* terminal zaten çalışır. Bulunduğunuz terminal için kurucu yapıştırılacak satırı yazdırdı; yoksa:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`comodor: command not found`, yeni bir terminalde** — bu gerçek bir sorundur. `python -m comodor`, hiç kurulu olup olmadığını doğrular ve `ls ~/.local/bin/comodor`, olması gereken yerde olup olmadığını gösterir.

**`No provider is configured`** — `comodor setup` çalıştırın ya da bir anahtar dışa aktarın:

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

**Python çok eski.** Comodor 3.11 ya da daha yenisini ister. `python --version` ile denetleyin.

---

## Bir ayar hiçbir şey yapmıyormuş gibi görünüyor

Comodor, birini reddettiğinde size söyler:

```
config: agent.max_steps must be a whole number; keeping 0
config: this project cannot set safety, computer — only your own can
```

Hiçbir şey söylenmiyorsa ve yine de etkisizse, hangi katmanın kazandığını denetleyin:

```
/settings          # what is actually loaded
```

```bash
comodor doctor     # the same, plus where every file is
```

Komut satırındaki bir `--model`, yapılandırma dosyanızı yener ve ortamınızdaki bir anahtar, dosyadakini yener. Bu bilinçlidir —
[Yapılandırma](configuration.md#what-wins).

---

## `/save` beklediğimi kaydetmedi

Tasarım gereği. **Yalnızca seçtiklerinizi** yazar — bir deponun ayarlarını değil, ortamınızda tuttuğunuz bir anahtarı değil, tek bir çalıştırma için geçirdiğiniz bir bayrağı değil.

Bir deponun ayarını kendinize yapmak için önce kendiniz ayarlayın (`/model x`), sonra kaydedin.

---

## İstekler başarısız oluyor

**`401` ya da `invalid api key`** — anahtar yanlış, süresi dolmuş ya da farklı bir sağlayıcıya ait. `comodor doctor` hangi sağlayıcının etkin olduğunu gösterir.

**`404 model not found`** — o sağlayıcı o model kimliğini sunmuyor. `/model`, gerçekte sunduklarını listeler.

**Zaman aşımları.** Vasat bir makinede yerel bir model gerçekten dakikalar sürebilir. `providers.<name>.timeout` değerini yükseltin.

**Erken duruyor.** `stopped`'a bakın. `max_steps` ve `budget`, işini yapan tavanlardır, başarısızlıklar değil. Tek bir çalıştırma için `--max-steps` ile, kalıcı olarak `agent` altında yükseltin.

---

## Harcama sınırı çalışmıyor

Büyük olasılıkla çalışamaz ve Comodor bunu söyler. Bkz.
[Maliyet — sınırın tetiklenemediği durum](cost.md#when-the-limit-cannot-fire).

---

## Tarayıcı aracı

**"no browser found"** — Chrome, Chromium, Edge ya da Brave kurun ya da `browser.executable` ayarlayın. Biri olmadan `browse`, bir sayfa hakkındaki soruların çoğunu yine de yanıtlayan bir metin tarayıcısına geri döner.

**Çalışmasını izlemek istiyorum** — `browser.headless: false`.

**Zaten sahip olduğum bir oturum açma gerektiriyor** — kendi tarayıcınızı bir DevTools bağlantı noktasıyla başlatın ve `browser.port` ayarlayın; böylece profiliniz devredilmek yerine o oturumu kullanır.

---

## Ekran aracı

**Araç listesinde yok.** Ya bu platformun arka ucu yoktur — şimdilik yalnızca Windows — ya da `computer.enabled` yanlıştır. Ona sorun:

```
/computer
```

**Tıklamalar yanlış yere düşüyor.** Bu olmamalı: DPI farkındalığı, herhangi bir ekran ölçüsü okunmadan önce ayarlanır. Oluyorsa, lütfen ekran ölçeklemeniz ve çözünürlüğünüzle bildirin. Bu gerçek bir hatadır.

**Kendiliğinden durdu.** Fare ekranın bir köşesine gitti; bu da verileni bilinçli olarak sona erdirir. `/computer 15m` yenisini başlatır.

**Ulaşan metin, yazdığı metin değil.** Uygulama onu yeniden yazdı — Windows 11'in Not Defteri, yazarken otomatik düzeltir. Bu bir Comodor hatası değildir ve her `type` üzerinde bunu söyler. [Daha fazlası](computer.md#typed-is-not-the-same-as-arrived).

---

## Web arayüzü

**Başlamayı reddediyor.** Yapılandırılmış bir sağlayıcı yoktur ve tarayıcı arayüzünün bir tane eklemek için bir yolu yoktur. Mesaj ne ayarlanacağını adıyla söyler.

**"Unauthorised".** Her çalıştırmada yeni bir token üretilir — *bu* çalıştırmadan gelen URL'yi kullanın ya da sabit kalması için `COMODOR_WEB_TOKEN` ayarlayın.

**Docker'da `localhost:8765`'te hiçbir şey yok.** Bağlantı noktasının `127.0.0.1:8765:8765` olarak yayınlandığını denetleyin. [Docker](docker.md).

---

## Bir şey yavaş

**Oturumun ilk isteği.** Henüz hiçbir şey önbellekte değil; ikincisi çok daha hızlıdır.

**Her görevden sonra yansıma.** Bir model çağrısı. Daha ucuzu için `learning.reflect_model` kullanın ya da `reflect: false`.

**Ekran görüntüleri.** Almak yaklaşık 80 ms, artı modelin onlara bakması. Sonucu hâlâ okuyabiliyorsanız `computer.screenshot_tokens` değerini düşürün.

---

## Baştan başlamak

```bash
comodor uninstall --dry-run     # what would go, named
comodor uninstall               # do it
```

Ya da yalnızca beyni, ayarlarınızı tutarak:

```bash
rm ~/.comodor/brain.db
```

---

## Bir sorunu bildirmek

Şunları ekleyin:

```bash
comodor --version
comodor doctor
```

`doctor`, anahtarınızı maskeler. Yine de lütfen yapıştırmadan önce çıktıyı okuyun.

- Issues: <https://github.com/ifekri/Comodor/issues>
- Hassas bir şey: [SECURITY.md](../SECURITY.md)
