# Gerçek tarayıcı

Bir sayfa indirici değil. Gerçekten kurulu olan bir tarayıcı — JavaScript çalıştırır, çerezleri tutar ve oturum açabilir.

---

## Neyi kullanır

Chrome, Chromium, Edge ya da Brave; makinede hangisi varsa. **Hiçbir şey indirilmez.** Kendisine ait, hiçbir yere oturum açmamış bir profilde birini başlatır ve oturum sona erdiğinde kapatır.

Hiçbiri kurulu değilse `browse`, bir sayfa hakkındaki soruların çoğunu yine de yanıtlayabilen bir metin tarayıcısına geri döner. İkisine de `browse` denir; çünkü "tarayıcı" adını taşıyan iki şey arasında seçim yapmak, modelin harcamaması gereken bir turdur.

---

## Ne döner

Ekran görüntüsü değil. Başlık, okunabilir metin ve **ekrande gerçekten duran denetimlerin numaralı listesi**:

```
  Sign in — Example
  ─────────────────────────────────────────────
  Sign in to your account. New here? Create one.

  [1]  textbox   Email
  [2]  textbox   Password
  [3]  button    Sign in
  [4]  link      Forgot your password?
```

Model, bir denetim numarasıyla üzerine işlem yapar. Bu liste, görünür olanla, adı olanla, ekranda olanla ve yinelenen olmayanla sınırlandırılır — bu, erişilebilirlik ağacından çok daha küçüktür ve ölçülmüştür, aynı sayfanın ekran görüntüsünden de küçüktür.

Ekran görüntüsü yalnızca soru görselse — yerleşim, stil, bir grafik — alınır; çünkü bir resim her seferinde aynı maliyetle gelir ve kırpılamaz.

---

## Eylemler

| | |
|---|---|
| `open` | bir URL'ye git |
| `click` | bir denetim, numarasıyla |
| `type` | bir alana, numarasıyla |
| `scroll` | yukarı ya da aşağı |
| `back` | önceki sayfa |
| `read` | sayfayı yeniden, bir şey değiştikten sonra |
| `look` | bir ekran görüntüsü, soru görünümüne dairse |
| `script` | JavaScript çalıştır ve değerini geri al |

---

## Çalışmasını izlemek

```json
{ "browser": { "headless": false } }
```

Görünür bir pencere; böylece ne yaptığını görebilirsiniz.

> Bu ayar bir zamanlar yok sayılıyordu — `browser` yapılandırma bölümü olarak kaydedilmemişti, dolayısıyla her `browser` ayarı sessizce hiçbir şey yapmıyordu. 0.9.0'da düzeltildi.

---

## Zaten oturum açtığınız bir oturumu kullanmak

Profilinizi devretmek yerine kendi tarayıcınızı bir DevTools bağlantı noktasıyla başlatın ve Comodor'u ona yönlendirin:

```bash
chrome --remote-debugging-port=9222
```

```json
{ "browser": { "port": 9222 } }
```

O tarayıcıya bağlanır ve orada zaten duran sekmeleri ve çerezleri kullanır. İşiniz bitince bağlantı noktasını kapatın — makinenizdeki her şey onu kullanabilir.

---

## Tüm ayarlar

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

| | |
|---|---|
| `executable` | belirli bir tarayıcı. Boşsa olağan yerlere bakılır |
| `headless` | varsayılan olarak görünmezdir, böylece odağı çalmaz |
| `width`, `height` | pencere |
| `port` | bir tarayıcı başlatmak yerine, başlattığınız bir tarayıcıya bağlanır |

Bir depo bunların hiçbirini ayarlayamaz — `browser.executable` başlatılacak bir ikili dosya adlandırır. [Güvenlik](safety.md#what-a-repository-may-set).

---

## `browse` mi `web_fetch` mi?

| | |
|---|---|
| `web_fetch` | sayfa bir belgedir. Metne indirgenir. Ucuz |
| `browse` | sayfa bir uygulamadır. JavaScript, bir oturum açma ya da bir tıklama gerekir |

Modele `web_fetch`'i tercih etmesi ve bu yetmediğinde `browse`'a uzanması söylenir.

---

## Bir kapsayıcı içinde

Docker imajı, Chromium'u ve onunla birlikte kullanılacak yazı tiplerini getirir. Chromium'un kendi sanal alanı, seccomp profili kullanıcı ad alanlarını engelleyen bir kapsayıcının içinde başlayamaz; Comodor bunu algılar ve iç sanal alan olmadan yeniden dener — gerçek sınır olan kapsayıcının kısıtlanmasını koruyarak. [Docker](docker.md).

---

## Perde arkası

Elle yazılmış bir WebSocket üzerinden Chrome DevTools Protocol. Bağımlılık yok: RFC 6455 çerçevelemesi yüz dolayında bir satırdır ve paketin parçasıdır; tıpkı HTTP istemcisi ve SSE okuyucusu gibi.

---

## Ayrıca bkz.

- [Ajanın yapabildikleri](tools.md) — diğer araçlar
- [Ekranınızı kullanmak](computer.md) — iş bir web sayfası olmadığında
- [Maliyet](cost.md) — resimler yerine neden metin döndürdüğü
