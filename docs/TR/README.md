# Comodor belgelendirmesi

Siz onu nasıl düzelttiğinizi öğrendikçe öğrenen bir terminal kodlama ajanı.

Burada mı yeni siniz? **[Başlangıç](getting-started.md)** yaklaşık beş dakika sürer ve
ajanın işe yarar bir şey yapmasıyla biter.

---

## Ne yapmaya çalıştığınıza göre

### Başlayın

| | |
|---|---|
| [Başlangıç](getting-started.md) | Kurulum, model seçimi, ilk görev |
| [Başka bir ajandan geçiş](migrating.md) | Anahtarlarınızı ve skill'lerinizi OpenClaw veya Hermes'ten getirin |
| [Model seçimi](models.md) | Hangi sağlayıcı, hangi model, maliyeti ne |

### Kullanın

| | |
|---|---|
| [Arayüz](interface.md) | Paneller, tuşlar, modlar ve 29 komutun tamamı |
| [Terminalden](cli.md) | Her komut ve bayrak, örnekleriyle birlikte |
| [Ajan neler yapabilir](tools.md) | Sahip olduğu 13 araç ve hangisini ne zaman kullandığı |
| [Skill'ler](skills.md) | Bir kez yazdığınız ve ajanın izlediği prosedürler |

### Daha uzağa ulaşmasını sağlayın

| | |
|---|---|
| [Gerçek tarayıcı](browser.md) | JavaScript çalıştırabilen ve oturum açabilen bir tarayıcı |
| [Ekranınızı kullanması](computer.md) | Herhangi bir uygulamada fare ve klavye |
| [Bir tarayıcıdan](web.md) | Web arayüzü, yerel olarak veya bir sunucuda |
| [Düzenleyicinizde](acp.md) | Comodor'u Zed'den veya herhangi bir Agent Client Protocol istemcisinden sürün |
| [Docker'da](docker.md) | Tek komut, bir konteyner içinde |
| [MCP sunucuları](mcp.md) | Model Context Protocol'den araçlar |

### Anlayın

| | |
|---|---|
| [Telefonunuzdan](telegram.md) | Telegram botu: eşleştirme, düğmeler ve kime yanıt verdiği |
| [Slack'ten](slack.md) | Socket Mode — beş dakika, herkese açık adres gerekmez ve thread'lerde yanıt verir |
| [WhatsApp'tan](whatsapp.md) | Cloud API — yaklaşık yirmi dakika ve teknik iş. Telegram aynısını bir dakikada yapar |
| [Makinenizdeki modeller](local-models.md) | Bir model indirmek, çevrimdışı çalıştırmak, listeye eklemek |
| [Sorular](questions.md) | Bir istek iki şekilde okunabildiğinde açtığı form |
| [Nasıl öğrenir](learning.md) | Düzeltmeler, dersler, kurallar ve kanıtı |
| [Güvenlik ve izinler](safety.md) | Neler yapabilir, neyi sorar, neyi asla yapmaz |
| [Maliyet](cost.md) | Önbellekleme, bütçeler ve aynı iş için daha az ödemek |
| [Yapılandırma](configuration.md) | Her ayar, dosyaların nerede yaşadığı, hangisinin geçerli olduğu |

### Bir şeyler ters gittiğinde

| | |
|---|---|
| [Sorun giderme](troubleshooting.md) | `doctor`, yaygın sorunlar ve nasıl rapor edileceği |

---

## Mümkün olan en kısa sürüm

```bash
curl -fsSL get.comodor.ai | sh      # macOS, Linux
irm get.comodor.ai | iex           # Windows

comodor                  # birkaç soru sorar, yalnızca bir kez
```

Sonra ne istediğinizi yazın. Yanlış yaptığında düzeltin — dosyayı düzenleyin
ya da sadece söyleyin — ve o öğrenir. `/progress`, bunun gerçekten işe
yarayıp yaramadığını gösterir.

```bash
comodor run "fix the failing test in tests/test_parser.py"   # tek görev, arayüz yok
comodor web                                                  # bir tarayıcıdan
comodor doctor                                               # her şey yolunda mı?
comodor help                                                 # yazılı yardım sayfası
```

## Onu farklı kılan şey

**Övgüden değil, düzeltmelerden öğrenir.** Çoğu ajan oturum biter bitmez
unutur. Comodor, çıktısında neyi değiştirdiğinizi izler ve bunu, tuttuğunda
güveni yükselen tutmadığında düşen bir derse dönüştürür. [Nasıl öğrenir](learning.md)
mekanizmayı açıklar; `/progress` kanıtı gösterir.

**Harekete geçmeden önce sorar ve her şey geri alınabilir.** Okuma sessizdir.
Yazma sorar. Komut çalıştırmak daha gürültülü sorar. Her yazma işlemi
checkpoint'lenir ve `/undo` sonuncuyu geri koyar. [Güvenlik ve izinler](safety.md).

**Tek bağımlılık.** HTTP istemcisi, SSE okuyucu, tarayıcı için WebSocket,
ekran görüntüleri için PNG kodlayıcı — hepsi paketin bir parçası. Comodor
kurmak `rich`'i getirir, başka hiçbir şeyi değil.

**Gerçek bir tarayıcı ve gerçek bir masaüstü kullanabilir.** Metin çekici
değil: JavaScript çalıştıran ve çerezleri saklayan bir tarayıcı ve — Windows'ta
— fare ve klavye, nereye tıklamak üzere olduğunu ekranda bir hâle ile göstererek.
[Tarayıcı](browser.md), [ekran](computer.md).

---

## Depoda ayrıca

| | |
|---|---|
| [CHANGELOG](../CHANGELOG.md) | Neyin değiştiği ve neden |
| [CONTRIBUTING](../CONTRIBUTING.md) | Comodor'un kendisi üzerinde çalışmak |
| [SECURITY](../SECURITY.md) | Hassas bir şeyi bildirmek |
| [RELEASING](../RELEASING.md) | Bir sürümün nasıl çıkarıldığı |
