# WhatsApp'tan

Aynı ajan, bir WhatsApp iş numarasından ulaşılan: bir görev gönderin, çalışmasını izleyin, sorularını yanıtlayın — terminal açmadan.

> **Önce bunu okuyun.** [Telegram](telegram.md) aynı şeyi yapar ve yaklaşık bir dakika alır: @BotFather'a mesaj, bir token yapıştır. WhatsApp yaklaşık yirmi dakika alır, teknik bir iştir ve çoğu Meta'nın panosundadır — bir Meta uygulaması, bir uygulama gizli anahtarı ve herkese açık bir HTTPS adresi gerekir. **WhatsApp olması zorunlu değilse Telegram kullanın.**
>
> [Slack](slack.md) orta yoldur: yaklaşık beş dakika ve orada da herkese açık bir adres gerekmez.
>
> Bunun çevresinden dolaşmak yok. WhatsApp'ın bir bot tokenı eşdeğeri yoktur ve Meta, mesajları bir URL'ye teslim eder; hiçbir şeyin onları yoklamasına izin vermez. Gerçek anlamda tek tıkla çalışan bir sürüm, her mesajı bir başkasının sunucusuna yönlendirmek zorunda kalırdı ve bu, bu aracın yapmadığı bir takastır.

```bash
comodor whatsapp connect              # walks you through all of it
comodor whatsapp pair                 # add your number
comodor whatsapp start --background   # run it
```

Argümansız `connect`, güdümlü bir kurulumdur: her sayfayı bağlantılandırır, bir seferde bir değer alır ve her biri ulaşır ulaşmaz denetler — tokenı Meta'ya karşı, kimliği bir kimlik oluşuna, gizli anahtarı bir gizli anahtar oluşuna. Tüneli sizin için başlatır ve Meta'nın doğrulama geri çağrısının gerçekten ulaştığını varsaymak yerine onu bekler.

Terminalin, tarayıcının ve Telegram botunun çalıştırdığı aynı ajan oturumunu çalıştırır. Burada başlatılan bir görev aynı dersleri öğrenir ve aynı geçmişte görünür.

## Bunun Telegram'dan daha çok kurulum istemesinin nedeni

Telegram size bir token verir ve mesajları yoklamanıza izin verir. WhatsApp, Meta'nın **Cloud API**'sidir ve onun tasarım kararlarından ikisi buradaki her şeyi biçimlendirir.

**Mesajlar teslim edilir, alınmaz.** Uzun yoklama yoktur. Meta her gelen mesajı bir URL'ye gönderir; bu da sizin bir şeyinizin internetten HTTPS üzerinden erişilebilir olması demektir. Ek iş budur ve bunun etrafından dolaşmak yoktur.

**Meta bir uygulama ister.** Bir iş hesabı, bir numara, bir erişim tokenı ve bir uygulama gizli anahtarı — bir tarayıcıda yaşayan dört şey; ilk çalıştırma sihirbazının bunları toplamaya çalışmak yerine bu sayfaya işaret etmesinin nedeni budur.

Çoğu projenin uzandığı alternatif, WhatsApp Web'i başsız bir tarayıcıyla süren bir kitaplıktır. Onlar Node ister, WhatsApp web istemcisini her değiştirdiğinde bozulur ve hesabın bağlı olduğu şartlara aykırıdır: başarısızlık biçimi, numaranın yasaklanmasıdır. Bir kodlama aracının kullanıcılarına el vereceği bir şey değildir.

## Ne kadar sürer

İlk seferde yaklaşık yirmi dakika, Telegram'ın bir dakikasına karşı; çoğu Meta'nın panosunda geçer, burada değil.

**Gerekmediği** şeyler: gerçek bir telefon numarası, bir ödeme yöntemi ya da iş doğrulaması. WhatsApp ürününü eklemek, beş alıcıya kadar ücretsiz mesaj gönderen bir **test numarası** oluşturur; bu, kendi ajanıyla konuşan tek bir kişinin gereksiniminden dört fazladır.

## Kurulumu

Kısa hali `comodor whatsapp connect`'tir; o her şeyi baştan sona yürütür. Aşağıdakiler, önceden görmeyi tercih edenler için, o neyi yürüttüyse odur.

### 1. Üzerinde WhatsApp olan bir Meta uygulaması

[developers.facebook.com](https://developers.facebook.com) adresinde bir uygulama oluşturun ve **WhatsApp** ürününü ekleyin. Meta başlangıç için size bir test numarası verir; gerçek olan daha sonra iş hesabının altına eklenir.

Oradan dört şeye ihtiyacınız var:

| | |
|---|---|
| **Phone number id** | Numaranın yanındaki sayısal kimlik — numaranın *kendi* değil |
| **Access token** | Panonun kendi tokenı 24 saat yaşar. Business Settings altındaki bir **System User** tokenı süresizdir ve kullanılacak olan odur |
| **App secret** | Settings → Basic. Her webhook onunla imzalanır |
| **Herkese açık bir HTTPS adresi** | Meta'nın teslim edeceği yer. Aşağıya bakın |

```bash
comodor whatsapp connect \
    --number-id 123456789012345 \
    --token EAAG… \
    --app-secret 0a1b2c…
```

Bu, herhangi bir şeyi kaydetmeden önce tokenı Meta'ya karşı denetler; böylece bir yazım hatası gelecek haftanın bilinmezi değil, bugünün mesajı olur.

### 2. Meta'nın teslim edeceği bir yer

Bot `127.0.0.1:8770` üzerinde dinler. Meta yalnızca **HTTPS**'e teslim eder ve öz-imzalı bir sertifikayı kabul etmez; dolayısıyla bir şeyin önüne gerçek bir tane koyması gerekir. Tünel, her zamanki cevaptır: açık bağlantı noktası yok, DNS yok, etki alanı yok.

**`comodor whatsapp connect` bunu sizin için yapar** — `cloudflared` kuruluysa tüneli başlatır, adresi onun içinden okur ve neyi yapıştıracağınızı gösterir. Kendiniz çalıştıracaksanız:

```bash
cloudflared tunnel --url http://127.0.0.1:8770
comodor whatsapp connect --url https://something.trycloudflare.com/whatsapp
comodor whatsapp webhook
```

**Hızlı bir tünel, her başlayışında yeni bir adres alır.** Kuruluma iyi gelir, çalışmaya devam etmesi amaçlanan bir bota yanlıştır: Meta, verdiğiniz adrese teslim etmeye devam eder; yeniden başlatmadan sonra hiçbir şey ulaşmaz ve hiçbir şey nedenini söylemez. `comodor whatsapp start --tunnel`, adres kaydığında uyarır.

Kalıcı bir adres için bir adlandırılmış tüneli bir kez yapın — ücretsiz bir Cloudflare hesabı gerekir:

```bash
cloudflared tunnel login
cloudflared tunnel create comodor
cloudflared tunnel route dns comodor comodor-hooks.example.com
```

TLS'i sonlandıran ve `127.0.0.1:8770`'ye ileten başka her şey, aynı biçimde çalışır.

```
  Callback URL   https://something.trycloudflare.com/whatsapp
  Verify token   Kq3nP…
```

İkisini de panodaki **WhatsApp → Configuration** bölümüne yapıştırın, ardından uygulamayı **messages** alanına abone edin. Meta, denetlemek için URL'yi hemen bir kez çağırır; el sıkışmayı bot kendisi yanıtlar.

Hâlihazırda çalıştırdığınız bir ters vekil de aynı şekilde çalışır — TLS'i sonlandıran ve `127.0.0.1:8770`'ye ileten her şey.

### 3. Numaranızı eşleştirin

```bash
comodor whatsapp pair
```

Bu, altı haneli bir kod yazdırır. WhatsApp'tan iş numarasına gönderin ve numaranız eklenir. Kod bir kez çalışır ve beş dakikada sona erer.

**Bir iş numarası bir telefon numarasıdır** ve yabancılar, telefon numaralarına mesaj göndermeyi olağan sayar. Bu yüzden sabit bir listeye yanıt verir ve diğer herkes **sessizlik** alır — bir reddedilme değil. "İzin verilmedi" diyen bir numara, bir yabancıya yeniden denemeye değer olduğunu söylemiş olur.

```bash
comodor whatsapp status         # who may talk to it
comodor whatsapp forget 15551234567
comodor whatsapp forget all
```

Liste rakamlar olarak karşılaştırılır; böylece `+1 555…`, `001 555…` ve `1555…` tek bir kişidir, üç kişi değil.

## Yapabildikleri ve yapamadıkları

**Varsayılan olarak okur ve planlar, hiçbir şeyi değiştirmez.** Terminal neye ayarlıysa ayarlı olsun bir WhatsApp oturumu plan modunda tutulur; Telegram'la aynı nedenden: sırada beklerken başparmakla bir kabuk komutunu onaylamak, aynı onayın klavye başında verilmesinden daha az dikkatle verilmiş bir karardır.

```bash
comodor whatsapp writes on
comodor whatsapp writes off
```

Bu bilinçli olarak bir terminal komutudur. Kendi izinlerini genişletebilen bir botun tek gereksinimi, birilerinin telefonu olurdu.

## Düğmeler

WhatsApp, yirmi karakterlik **üç** yanıt düğmesine ya da **on** satırlık bir liste açan tek düğmeye izin verir. Bunlar kesin sınırlardır — Meta, kırpacak yerinde bütün mesajı reddeder — dolayısıyla menü bir listedir ve tam olarak on satırdır:

| | |
|---|---|
| **New chat** | Şimdiye kadarki sohbeti unut |
| **History** | Önceki bir sohbeti yeniden aç |
| **Mode** | İş, plan ya da sohbet |
| **Status** | Model, klasör, bağlam, harcama |
| **Model** | Bir başkasına geç |
| **Folder** | Hangi projede çalıştığı |
| **Skills** | Birini kur ya da kaldır |
| **Rules** | Düzeltmelerinizden ne öğrendiği |
| **What it may do** | Düzenleyip çalıştırıp çalıştıramayacağı |
| **Help** | Her şeyin ne yaptığı |

Bir görev çalışırken sunulan tek şey **Stop**'tur: bu kadar dar bir ekranda, bir denetimi soluklaşmış halde tutacak yer yoktur.

Daha uzun listeler — modeller, beceriler, geçmiş — bir seferde sekiz adet olacak biçimde sayfalanır; çünkü iki gezinti satırı da onun payından düşer.

## Sizi şaşırtacak iki şey

**Bir mesajı düzenleyemez.** Telegram, yanıt gelirken tek bir mesajı yeniden yazarak akış halinde sunar. WhatsApp'ta düzenleme yoktur ve token başına bir mesaj, tek bir soru için yüz bildirim olurdu. Bu yüzden bir tur, başlarken tek bir satır söyler, çalışırken arada bir konuşur ve yanıt olgunlaşınca gönderir.

**Gün boyu süren bir pencere vardır.** Meta, serbest biçimli mesajlara yalnızca *sizin* son mesajınızdan itibaren yirmi dört saat içinde izin verir. Uzun bir görev ondan sonra biterse bot size bunu söyleyemez — günlüğüne yazar ve ona yeniden yazmak pencereyi yeniden açar.

## Çalıştırmak

Tam olarak Telegram gibi:

```bash
comodor whatsapp start                # here, holding this terminal
comodor whatsapp start --tunnel       # and bring a tunnel up with it
comodor whatsapp start --background   # detached; survives closing it
comodor whatsapp stop
comodor whatsapp service install      # starts at login, survives a reboot
comodor whatsapp service show         # read the unit before trusting it
```

Günlük, yapılandırmanızın yanındaki `whatsapp.log`'dur; değiştirilmek yerine sona eklenir.

Her platformda bir **kullanıcı** servisi — systemd, launchd, Görev Zamanlayıcı — asla sistem servisi değil. Bu, dosyalarınızı sizin kimlik bilgilerinizle okuyan ve yazan bir ajandır ve o dosyaların sahibi olan kişiden fazla yetki hiçbir şey getirmez.

## Nasıl inşa edildi

Yeni bir bağımlılık yok. Cloud API, bu projenin hâlihazırda sahip olduğu HTTP istemcisi üzerinden `POST /messages`'tır ve webhook, standart kitaplıktan `http.server`'dır.

Uç nokta, işi yapmadan **önce** Meta'ya yanıt verir. Meta, bir 200 almadığı her şeyi saniyeler içinde yeniden dener ve bir ajan turu dakikalar sürer — bekleyen bir webhook, aynı mesajın beş kez teslim edilmesini getirir.

Mesaj kimlikleri hatırlanır; böylece yine de ulaşan bir yeniden teslim, ikinci bir tura dönüşmez.

## Yapmayacakları

- Eşleşmemiş herhangi birine yanıt vermek ya da nedenini söylemek.
- Doğrulayamadığı bir webhook kabul etmek. Bir uygulama gizli anahtarı olmadan hiçbir şey doğrulanmaz ve `comodor whatsapp status` bunu sarıyla söyler.
- Bir projenin `.comodor/config.json` dosyasından bir token, bir numara ya da izinli bir hesap almak. Kendi yazarını o listeye ekleyebilen bir depo bir arka kapı olurdu.
- `whatsapp writes on` olana dek hiçbir şeyi düzenlemek.
- Tokenı yazdırmak. Yükselen her hatadan sansürlenir.
