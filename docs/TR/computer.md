# Ekranınızı kullanmak

Comodor, makineyi bir insanın yapacağı şekilde sürebilir — ekrana bakmak, fareyi hareket ettirmek, tıklamak ve yazmak — herhangi bir uygulamada, yalnızca bir tarayıcıda değil.

Yapabildiği en güçlü şey ve en tehlikelisi olan budur. Açmadan önce [izin modelini](#permission) okuyun.

> **Şimdilik yalnızca Windows.** macOS ve Linux arka uçları henüz yazılmadı. O platformlarda araç hiç sunulmaz; sunulup da başarısız olmaz — bkz. [Neden yok](#why-it-is-not-there).

---

## Nasıl görünür

Olanları izlersiniz. İşaretçi hareket etmeden önce, tıklamak üzere olduğu yerde bir hale belirir:

```
   ┌─────────────────────────────────────────┐
   │   Comodor · 14m 32s left, anywhere      │   ← the panel, top centre
   │   move the mouse to a corner to stop    │
   └─────────────────────────────────────────┘


               ╭──────────╮
               │   Save   │      ◎  ← the halo, drawn before it moves
               ╰──────────╯
                               clicking (842, 517)
```

İşaretçi daha sonra ışınlanmak yerine yaklaşık bir üçüncü saniye boyunca oraya gider ve bir dalga, tıklamanın nereye indiğini işaretler.

**Duraklama bir süs değildir.** Üzerinde hâlâ durdurabileceğiniz andır. Tek anda zıplayıp tıklayan bir imleç size hiçbir şey vermez.

Ajan başka bir yerde çalışıyorsa — bir sunucu, bir kapsayıcı — aynı şey [web arayüzünde](web.md) görünür: baktığı kare, üzerine işlem yaptığı yerde bir işaretçiyle.

---

## Açmak

İki adım, bilinçli olarak. Ne biri ne diğeri kendi kendine olur.

**1. Aracın var olmasına izin verin**, `~/.comodor/config.json` içinde:

```json
{
  "computer": {
    "enabled": true
  }
}
```

Bu ayarlanana kadar modele araç hiç sunulmaz. Araç listesinde değildir; bu yüzden isteyemez ve ona ikna edilemez.

**2. Harekete geçmesine izin verin**, önemli olduğu anda:

```
/computer 15m              fifteen minutes, anywhere on screen
/computer 1h this app      one hour, only while the current window is in front
/computer                  how things stand
/computer stop             end it now
```

Ya da modelin sormasına izin verin. Ekranı ilk kez gereksindiğinde şunu görürsünüz:

```
  Let Comodor use your screen, mouse and keyboard?

  It will be able to see everything on your screen and to click and type
  anywhere, in any application.

  Screenshots go to the model. Whatever is on screen goes with them - open
  messages, tokens, anything visible. Redaction works on text and cannot
  read pixels.

  It will never touch a password manager, a window asking for a password,
  a locked screen, or Comodor's own window.

  To stop it at any moment: move your mouse into a corner of the screen.

  [15 minutes]  [15 minutes, this app only]  [1 hour]  [no]
```

---

## Durdurmak

**Fareyi ekranın bir köşesine götürün.** O, bütün mesele.

Ajan işaretçiyi tutarken de çalışır; hiçbir klavye kısayolu bunu vaat edemez — ajan o anda bir pencereye yazıyor olabilir. Aynı zamanda insanların ekranları kendiliğinden hareket etmeye başladığında gerçekten yaptıkları şeydir.

Bir köşeye dokunmak çalışmayı sona erdirir ve izni geri alır. Tekrar sormak yeni bir verilmedir.

Ajan yine de kendisi bir köşeye tıklayabilir — Başlat düğmesi, bir kapatma kutusu. İşaretçiyi nereye bıraktığını hatırlar; bu yüzden yalnızca kimsenin koymadığı bir yere gitmiş bir işaretçi siz sayılır.

Elleriniz klavyedeyken durdurmanın diğer yolları:

```
/computer stop       ends the permission
Esc                  stops the current task
```

---

## İzin

Bir verilen aynı anda üç şeydir ve hiçbiri onay kutusu değildir.

| | |
|---|---|
| **Bir kapsam** | her yer, ya da pencere başlığına göre tek bir uygulama |
| **Bir saat** | süresi dolar ve kalan süre boyunca ekranda görünür |
| **Bir çıkış yolu** | köşe; işaretçi sürülürken de çalışır |

**Her tek eylemden önce** denetlenir, başta bir kez değil. Verilmiş bir çalışmanın yarısında beliren bir pencere yakalanır.

### Ne izin vermiş olursanız olun reddedilen

- Bir parola yöneticisi — 1Password, Bitwarden, KeePass, LastPass, Dashlane, NordPass ve sistem kimlik bilgisi depoları.
- Başlığı bir parola, parola tümcesi, 2FA ya da tek seferlik bir kod belirten her pencere.
- Bir cüzdan ya da donanım cüzdanı uygulaması — MetaMask, Ledger Live, Trezor.
- İnternet bankacılığına benzeyen her şey.
- Kilitli bir ekran.
- **Comodor'un kendi penceresi.** Onu süren terminale tıklayan bir ajan, kendi istemine yazar.

Kendi listenizi ekleyin:

```json
{
  "computer": {
    "never": ["Internal HR", "Payroll"]
  }
}
```

Pencere başlığının herhangi bir yerinde, büyük/küçük harfe duyarsız olarak eşleştirilir.

### Bir verilen olmayan şey

**Asla yapılandırma dosyanıza yazılmaz.** Comodor'u kapatmak onu sona erdirir. Ekran için "her zaman izin ver" yoktur ve bu eksiklik bilinçlidir.

Bir depo bunu etkinleştiremez. `computer`, bir projenin `.comodor/config.json` dosyasının ayarlayabileceği şeyler listesinde değildir ve bunu deneyen bir depo açıkça reddedilir. Bkz. [Güvenlik](safety.md#what-a-repository-may-set).

---

## Modele ne gider

**Ekran görüntüleri ve içinde görünen her şey.** Bunun üzerinde durmaya değer.

Editörünüzün arkasında bir parola yöneticisi açıksa, bir sohbet penceresinde bir mesaj varsa, bir API anahtarı bir terminale basılmışsa — o resmin içindedir ve resim, yapılandırdığınız hangi sağlayıcıysa ona gider.

Comodor'un redaksiyonu metin üzerinde çalışır ve piksel okuyamaz. Bunun çevresinde yol yok: özellik, "modele ekranınızı göster" demektir.

Pratik öğütler:

- Bir sohbet penceresine yapıştırmayacağınız her şeyi kapatın.
- Yalnızca tek bir pencere öndeyken işlem yapması için `/computer 1h this app` kullanın — yine de ekran görüntüsündeki *her şeyi görür*.
- İş bir web sayfasıysa [tarayıcı aracını](browser.md) tercih edin. Metin döndürür, piksel değil ve maliyeti çok daha düşüktür.

---

## Yapabildikleri

Tek bir aracın arkasında on yedi eylem. Adlar Anthropic'indir, çünkü modeller o sözcük dağarcığıyla eğitilir.

### Bakmak

| Eylem | Ne yapar |
|---|---|
| `screenshot` | Etkin monitör. Her monitör için `whole_desktop: true`. |
| `zoom` | Tam çözünürlükte bir bölge — küçük metni böyle okur |
| `cursor_position` | İşaretçinin nerede olduğu |

### İşaret etmek

| Eylem | |
|---|---|
| `mouse_move` | Tıklamadan bir yere gitmek |
| `left_click` `right_click` `middle_click` | İsteğe bağlı değiştirici tuşlarla |
| `double_click` `triple_click` | Üçlü tıklama çoğu düzenleyicide bir satırı seçer |
| `left_click_drag` | Bir noktadan bir başkasına |
| `left_mouse_down` `left_mouse_up` | Bir sürüklemenin ifade edemediği her şey için |
| `scroll` | Yukarı, aşağı, sola, sağa, tekerlek tıklamalarıyla |

### Yazmak

| Eylem | |
|---|---|
| `type` | Metin, karakter karakter — her klavye düzeninde doğru |
| `key` | `Return`, `ctrl+s`, `alt+Tab`, `F5`, `Page_Down`, … |
| `hold_key` | Bir tuşu ya da birleşimi bir süre boyunca basılı tutmak |
| `wait` | Ekrandaki bir şeyin bitmesini beklemek |

Metin **tuş konumuna göre değil, karakter karakter yazılır**. `@`'nin ABD klavyesinde durduğu yerdeki tuşa basmak Fransız klavyesinde başka bir şey üretir; karakteri adlandırmak her yerde `@` üretir, onun için tuşu bulunmayan düzenlerde bile.

---

## Yazılan, ulaşılan demek değildir

Uygulamalar, içlerine yazılanı yeniden yazar.

Windows 11'in Not Defteri'nde otomatik düzeltme varsayılan olarak açıktır. İçine `ümlaut` yazmak `umlaut` üretir. Yolda hiçbir şey kaybolmamıştır — otuz aksanlı ve Latin olmayan karakterin her biri tek başına gönderildiğinde sağlam ulaşır ve aynı konumdaki `üxqzv` dokunulmamış kalır. Değiştiren uygulamadır.

Comodor her `type` üzerinde bunu söyler:

```
Typed 29 characters. Applications can autocorrect or reformat what is
typed into them - take a screenshot if what arrived matters.
```

Kesin metin önemliyse — bir parola alanı, bir yapılandırma değeri, bir commit mesajı — yeniden bakmasını isteyin.

---

## Ekran görüntüleri ve maliyetleri

Bir ekran görüntüsü, bu aracın gönderdiği en pahalı şeydir.

Boyut, modelin kabul edeceğine göre ayarlanır: 2.576 piksellik bir uzun kenar ve bir token bütçesi. Varsayılan bütçe 1.600 görsel tokendır; denenmiş her ekranda okunabilir bir resim verir.

| Ekranınız | Varsayılan bütçede | Maliyet |
|---|---|---|
| 1920 × 1080 | 1480 × 833 | ~1.590 token |
| 3840 × 1080 | 2068 × 582 | ~1.554 token |
| 3840 × 2160 | 1064 × 599 | ~836 token |

**Bunu çok düşük ayarlamayın.** "1280 genişlikte yakala" biçimindeki yaygın öğüt bir 16:9 ekran varsayar. 3840 × 1080 bir ekranda bu, üç kat küçültme demektir ve o boyutta modelin eline okuyamayacağı metin geçer — bu yüzden sormak yerine tahmin eder. O ekranda ölçülmüştür: menü etiketleri 1280 genişlikte okunaksız, 2068'de tamamen net.

```json
{
  "computer": {
    "screenshot_tokens": 1600
  }
}
```

700 ucuzdur ve bir dizüstü bilgisayarda yine de okunabilir. 4784, modelin kabul ettiği en yüksek değerdir.

**Eski ekran görüntüleri otomatik olarak atılır.** Sohbette yalnızca son ikisi kalır; gerisi, bir tanesinin orada olduğunu söyleyen bir satıra dönüşür. Bu olmadan otuz adımlık bir görev, neredeyse tamamı o sırada tıklanmış bir ekranı betimleyen yaklaşık elli bin tokenlık piksel taşımış olurdu. Bir nedeniniz varsa `agent.keep_screenshots` ile değiştirin.

---

## Tüm ayarlar

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

| Ayar | Varsayılan | |
|---|---|---|
| `enabled` | `false` | Modele aracın hiç sunulup sunulmayacağı |
| `screenshot_tokens` | `1600` | Okunabilirlik karşısında fiyat. En fazla 4784 |
| `grant_seconds` | `900` | Düz bir verilenin süresi |
| `travel_seconds` | `0.32` | İşaretçinin yolculuğunun süresi. `0` çalışır ama izlenemez olurdu |
| `overlay` | `true` | Haleyi ve paneli çiz. Kimsenin oturmadığı bir makine için kapalı |
| `never` | `[]` | Asla dokunulmayacak ek pencere başlıkları |

---

## Neden yok

`computer` araçlar arasında değilse, şunlardan biri doğrudur:

**Platformun arka ucu yok.** Şimdilik yalnızca Windows. Araç, sunulup her seferinde başarısız olmak yerine hiç sunulmaz — modelin görebildiği ama hiç kullanamadığı bir araç, her turda boşa bir çağrı davet eder.

**Kapalıdır.** `computer.enabled` varsayılanı `false`'tur.

Doğrudan sorun:

```
/computer
```

```
no screen control: it is switched off. Set computer.enabled in your config.
```

---

## Perde arkası

Meraklılar için ve onu başka bir platforma taşıyacak herkes için.

**Bağımlılık yok.** Ekran yakalama, `ctypes` üzerinden GDI'dır; küçültme, `HALFTONE` modunda `StretchBlt`'dir ve pikselleri düşürmek yerine ortalar — okunabilir küçük metin ile benek arasındaki fark budur. PNG kodlaması `zlib` ve `struct` ile yaklaşık kırk satırdır. Girdi `SendInput`'tur.

**DPI farkındalığı, bir şey ekran ölçüsü okumadan önce ayarlanır.** %125'e ölçeklenmiş bir ekranda — çoğu Windows dizüstü bilgisayarın varsayılanı — kendini DPI-farkındı ilan etmemiş bir işleme ekran olduğundan daha küçük söylenir ve her tıklama, tam olarak ölçek katsayısı kadar kısa düşer. Nedeni görünmezdir; modele nişan alamıyormuş gibi görünür.

**Koordinatlar tek bir yerde dönüştürülür.** Model, kendisine gösterilen resmin pikselleriyle yanıtlar; bu resim, hakkında hiç bilgilendirilmediği bir başlangıç noktasından başlayan bir ekranın küçültülmüş bir kırpmasıdır. `Shot.to_screen`, bunu bilen tek koddur; çünkü ikinci bir kopya, yanlış yapmak için ikinci bir şanstır.

**Kaplama, tıklamaları geçiren, odaklanmayan bir penceredir.** `WS_EX_LAYERED |
WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`, böylece işaretçi alttakine ulaşır ve klavye olduğunda kalır. Kendi iş parçacığında kendi olay döngüsüyle çalışır ve çizememek eksik bir resimdir, eksik bir özellik değil — ajan hiç ekransız da çalışır.

macOS ya da Linux'a taşımak, `win32.py`'nin yanına aynı düzine işlevle tek bir dosya yazmak demektir. O katmanın üstünde hiçbir şey `ctypes` içe aktarmaz.

---

## Ayrıca bkz.

- [Güvenlik ve izinler](safety.md) — izin modelinin geri kalanı
- [Gerçek tarayıcı](browser.md) — daha ucuz; iş bir web sayfası olduğunda
- [Bir tarayıcıdan](web.md) — başka bir yerden çalışmasını izlemek
- [Maliyet](cost.md) — uzun bir masaüstü oturumunun gerçekte neye mal olduğu
