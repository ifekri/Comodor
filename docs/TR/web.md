# Bir tarayıcıdan

Aynı ajan, bir tarayıcı sekmesinde. Bu makinede ya da SSH üzerinden ulaştığınız bir sunucuda.

```bash
comodor web
```

```
   ______                          __
  / ____/___  ____ ___  ____  ____/ /___  _____
 / /   / __ \/ __ `__ \/ __ \/ __  / __ \/ ___/
/ /___/ /_/ / / / / / / /_/ / /_/ / /_/ / /
\____/\____/_/ /_/ /_/\____/\__,_/\____/_/

  it learns the way you correct it   0.9.0  ·  claude-sonnet-5

  Comodor is at  http://127.0.0.1:8765/?token=EYhO9St_VTy95k4gHtJytb
  Working in     /home/you/projects/api-server

  Only this machine can reach it. Ctrl-C to stop.
```

Bağlantıyı açın. Token onun içindedir.

---

## Seçenekler

```bash
comodor web --port 9000
comodor web --no-browser            # do not open one for me
comodor web --token mytoken         # a fixed token
comodor web --host 0.0.0.0          # reachable from elsewhere — read below
```

---

## Token

Her çalıştırmada yeni bir tane, böylece dünkü bir URL bugün bir giriş yolu değildir. Token URL içinde ulaşır, bir çerezle takas edilir ve ondan sonraki her istek çerezle yetkilendirilir.

Yeniden başlatmalar arasında sabit tutmak için:

```bash
export COMODOR_WEB_TOKEN=something-long-and-random
```

Tokena sahip herkes o makinede bir kabuğa sahiptir. Ona öyle davranın.

---

## Sadece loopback'ten fazlasına bağlanmak

`--host 0.0.0.0`, arayüzü makinenin her arayüzüne koyar. **Bu bağlantı noktası bir kabuktur.** Comodor, demek istediğinizi varsaymak yerine bunu söyler:

```
  Listening on every address on this machine.
  Anyone who can reach this port can run commands as you.
```

Ajan bir sunucudayken daha iyisi: loopback'te bırakın ve tünel kurun.

```bash
ssh -N -L 8765:127.0.0.1:8765 you@server
```

Ardından yerel olarak `http://127.0.0.1:8765` adresini açın. Bağlantı noktası hiç dışa açılmaz ve kimlik doğrulamayı SSH yapar.

---

## Ekranı kullanmasını izlemek

Ajan bir masaüstünü sürüyorsa baktığı kare, üzerine işlem yaptığı yerde bir işaretçiyle arayüzde görünür:

```
┌────────────────────────────────────────────┐
│                                            │
│   [ the screen the model saw ]      ✛      │
│                                            │
│   clicking Save                            │
└────────────────────────────────────────────┘
```

İşin aslı budur. Ekran üstü kaplama, sürülen makinede çizilir; o makine bir sunucu ya da bir kapsayıcı olduğunda bu işe yaramaz — panel, başkadan izlemenin yoludur.

Resim, olay akışında taşınmak yerine kare başına bir kez `/api/screen`'den alınır: bir ekran görüntüsü yaklaşık bir megabayttır ve olay günlüğünü yeniden okuyan bir tarayıcı, gördüğü her kareyi indirirdi.

[Ekranınızı kullanmak](computer.md).

---

## Yapmayacakları

**Sağlayıcısız başlamaz.** Zaten kurulmuş sağlayıcılar arasında geçiş yapabilir ama anahtar yazacak hiçbir yeri yoktur ve bir tarayıcı sekmesi onun için kötü bir yer olurdu. İlk görevde başarısız olan bir URL sunmak yerine neyin eksik olduğunu söyler ve durur:

```
Comodor has no provider configured, and the browser interface has no way to
add one.

  In Docker, pass a key in as an environment variable:
    -e ANTHROPIC_API_KEY=...    -e OPENAI_API_KEY=...
  or mount a config file at ~/.comodor/config.json.
  Anywhere with a terminal, `comodor setup` asks a few questions.
```

Bir terminalde bunun yerine kurulum sorularını sorar. Bir kapsayıcıda her zaman mesajı yazdırır — bir kapsayıcının terminali, bağlı olup olmadığından bağımsız olarak vardır ve bağlı olmayan bir kapsayıcı, aksi takdirde kimsenin yanıtlayamayacağı bir soruyu sonsuza dek beklerdi.

**Ajanın dokunabildiklerini genişletmez.** Yazmalar ve komutlar için otomatik onay, Admin'de gösterilir ve orada değiştirilemez. İzin istemleri zaten o seçimi her eylem için, onunla yaşayacak olan kişinin önünde sunar; bağlantıyı elinde tutan herkesin ulaşabildiği bir sayfa, onu daimi politika yapmanın yanlış yeridir. Onu Comodor'un başlatıldığı yerde değiştirin — bkz. [Güvenlik](safety.md).

---

## Ekranda ne var

**Sohbet**, ulaştığı anda akar; çitli kodlar kod olarak saklanır ve her araç çağrısı, gerçekte ne yaptığını görmek için açabileceğiniz bir satırdır.

**Sohbet listesi**, solda. Her sohbet `~/.comodor/sessions`'a yazılır — terminalin kullandığı aynı klasör; böylece istemde başlatılan bir sohbet tarayıcıda açılabilir ve tersi de geçerlidir. Arama içlerine bakar, yalnızca başlıklarına değil.

**Admin**, ikinci sekme; "bu şey makineme ne yapmak üzere" sorusunun cevabıdır:

| | |
|---|---|
| Model | hangi sağlayıcı ve model yanıt veriyor, ve anahtarınız olanlar arasında geçiş |
| Nasıl çalışıyor | mod, kendi kendine devam edip etmediği ve dört tavan — bağlam, adımlar, süre, harcama |
| İzinler | sormadan ne yapabileceği, ne hakkında soracağı ve bu oturumda neye izin verildiği |
| Neyi öğrendi | kurallar, dersler, beceriler, görevler ve kaçının başarılı olduğu |
| Araçlar | erişebildiği her araç, riske göre renk kodlu; artı becerileriniz ve varsa MCP sunucuları |
| Bu makine | sürüm, Python ve ayarların, sohbetlerin ve beynin nerede olduğu |

**Durum şeridi**, en altta: sayfanın bağlı olup olmadığı, çalışma klasörü, bağlamın ne kadar dolduğu, oturumun neye mal olduğu ve kaç öğrenilmiş kuralın yürürlükte olduğu.

**Ekran paneli**, ajan bir ekranı sürerken — en son baktığı kare, tıklamak üzere olduğu yerde bir işaretçiyle. Bkz. [Ekranınızı kullanmak](computer.md).

---

## Klavye

| | |
|---|---|
| `Enter` | gönder |
| `Shift`+`Enter` | yeni satır |
| `Esc` | geçerli görevi durdur, ya da kenar çubuğunu kapat |
| `Ctrl`/`⌘`+`K` | sohbetlerde ara |
| `Ctrl`/`⌘`+`B` | kenar çubuğunu göster ya da gizle |
| `/` | mesaj kutusuna atla |

---

## Bir telefonda

Aynı sayfa. 900 pikselin altında sohbet listesi, sohbetin yanındaki bir sütun yerine onun üzerine gelen bir çekmeceye dönüşür; çünkü 390 piksellik bir ekranda 292 piksellik bir kenar çubuğu, kodun okunacağı yeterince geniş hiçbir yer bırakmaz. Onu kaldırmak için dışına dokunun, `Esc`'e basın ya da kapat düğmesini kullanın.

Telefonunuzdan ona, makinenizdeki başka her şeye ulaştığınız gibi ulaşırsınız — herkese açık bir bağlanma değil, bir SSH tüneli. [Sadece loopback'ten fazlasına bağlanmak](#binding-to-more-than-loopback) nedenini açıklar.

---

## Her dilde yazmak

Farsça, Arapça ya da İbranice yazın; mesaj kutusu yazarken ters döner. O dillerdeki yanıtlar ulaştıklarında sağdan sola dizilir. Hiçbir şey yapılandırılmaz ve bir dil ayarı yoktur: her mesaj kendi başına yargılanır; böylece diller arasında gezinen bir sohbet, onlarla birlikte gider.

Yargı, ilk harfe göre değil sayma ile yapılır; bu, iki rahatsız durumun doğru sonuç vermesini sağlayan şeydir — bir paket adıyla açılan bir Farsça cümle hâlâ Farsçadır ve tek bir Farsça sözcük alıntılayan bir İngilizce cümle hâlâ İngilizcedir. Kod, yollar ve URL'ler, sağdan sola bir paragrafın içinde, ait oldukları yerde, soldan sağa dizilir.

Arap yazısıyla metin, Vazirmatn ile dizilir; bu, bir yazı tipi sunucusundan alınmak yerine paketin içinde taşınır: bu, internete ulaşamayan bir makinede de çalışmak zorundadır. Arap yazısı karakterlerine uygulanır ve başkaca hiçbir şeye uygulanmaz; böylece Farsça ile bir İngilizce tanımlayıcıyı harmanlayan bir satır, her birine uygun yüzü alır.

---

## Açık ve koyu

Varsayılan olarak sistemi izler; sağ üstteki güneş, onu değiştirir ve seçim o tarayıcıda hatırlanır.

---

## Docker içinde

```bash
docker compose up
```

ve yazdırdığı adresi açın. [Docker](docker.md).

---

## Ayrıca bkz.

- [Docker](docker.md) — aynı şey, bir kapsayıcıda
- [Arayüz](interface.md) — terminal sürümü
- [Güvenlik](safety.md) — Admin sekmesinin bildirdiği izinler
- [Ekranınızı kullanmak](computer.md) — kare panelin size gösterdikleri
