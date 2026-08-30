# Slack'ten

Aynı ajan, çalışma alanınızda: bir görev gönderin, çalışmasını izleyin, sorularını yanıtlayın — terminal açmadan.

```bash
comodor slack manifest              # the app definition to paste into Slack
comodor slack connect               # the two tokens, checked as you paste them
comodor slack pair                  # add your account
comodor slack start --background    # run it
```

Yaklaşık beş dakika ve **düzenlenecek herkese açık bir adres yoktur** — bunu [WhatsApp](whatsapp.md)'tan ayıran şey budur.

Terminalin, tarayıcının ve Telegram botunun çalıştırdığı aynı ajan oturumunu çalıştırır. Burada başlatılan bir görev aynı dersleri öğrenir ve aynı geçmişe düşer.

## Bunun kolay olmasının nedeni

Slack'in olay teslim etmenin iki yolu vardır. Events API bir URL'ye gönderir; bu da herkese açık bir HTTPS adresi, bir sertifika ve bir tünel demektir — WhatsApp'ı zorlaştıran bütün iş.

**Socket Mode** bunu tersine çevirir: uygulama Slack'ten bir websocket adresi ister ve *dışa doğru* bağlanır. İnternetten erişilebilir olması gereken hiçbir şey yoktur ve güncel tutulacak bir adres de yoktur. Bütün numara budur ve Slack'in WhatsApp'ın değil Telegram'ın yanında durmasının nedeni odur.

İşe yarayan ikinci şey **uygulama manifesti**. Slack, bir uygulamanın bir YAML belgesiyle betimlenmesine izin verir; böylece dört ayar sayfasına yayılmış on bir onay kutusu bulmak yerine, uygulamanın tamamı — ad, kapsamlar, olaylar, Socket Mode açıkken — tek bir yapıştırmadır.

## Kurulumu

### 1. Uygulamayı oluşturun

```bash
comodor slack manifest
```

Bu, manifesti ve bağlantıyı yazdırır. [api.slack.com/apps](https://api.slack.com/apps?new_app=1) adresinde **From a manifest** seçin, çalışma alanınızı seçin, yapıştırın, oluşturun — sonra **Install to Workspace**.

### 2. İki token

Bunlar birbirinin yerine geçmez ve karıştırmaları, bunun başarısız olmasının en yaygın tek yoludur. Comodor, Slack'in bir saat sonra `invalid_auth` yanıt vermesine izin vermek yerine her birini diğerinin yerine, adına göre reddeder.

| | | |
|---|---|---|
| `xoxb-…` | **Bot token** | OAuth & Permissions. Botun yaptığı her şeyi yapar |
| `xapp-…` | **App-level token** | Basic Information → App-Level Tokens, kapsam `connections:write`. Soketi açar ve başka hiçbir şey |

```bash
comodor slack connect
```

Argümansız ikisini de baştan sona sizinle yürütür ve her biri ulaşır ulaşmaz denetler — bot tokenını `auth.test`'e karşı, uygulama tokenını gerçekten onunla bir soket açarak. Yanlış olanı, gelecek haftanın bilinmezi değil, bugünün cümlesidir.

### 3. Hesabınızı eşleştirin

```bash
comodor slack pair
```

Bu, altı haneli bir kod yazdırır. Comodor'a doğrudan mesaj olarak gönderin ve hesabınız eklenir. Kod bir kez çalışır ve beş dakikada sona erer.

**Bir çalışma alanı içinde yüzlerce kişi olabilir** ve bu, dosyalarınızı okuyan ve yazan bir ajandır. Bu yüzden sabit bir Slack kullanıcı kimliği listesine yanıt verir ve diğer herkesi yok sayar.

```bash
comodor slack status
comodor slack forget U01234567
comodor slack forget all
```

## Nerede yanıtlar

**Doğrudan mesajda**, her zaman.

**Bir kanalda, yalnızca anıldığında.** Paylaşımlı bir kanaldaki her mesaja yanıt veren bir bot, birilerinin o öğleden sonra kaldırdığı bottur.

**Konuşulduğu iş parçacığında.** Bir iş parçacığında sorulan soru o iş parçacığında yanıtlanır, herkesin önündeki kanalda değil.

Kendi mesajları asla yanıtlanmaz — kendine yanıt veren bir bot, üstünde hız sınırı olan bir döngüdür.

## Yapabildikleri ve yapamadıkları

**Varsayılan olarak okur ve planlar, hiçbir şeyi değiştirmez.** Terminal neye ayarlıysa ayarlı olsun bir Slack oturumu plan modunda tutulur; diğer kanallarla aynı nedenden: telefondan, sırada beklerken bir kabuk komutunu onaylamak, aynı onayın klavye başında verilmesinden daha az dikkatle verilmiş bir karardır.

```bash
comodor slack writes on
comodor slack writes off
```

Bilinçli olarak bir terminal komutu. Kendi izinlerini genişletebilen bir botun tek gereksinimi, birilerinin Slack hesabı olurdu.

## Düğmeler

Slack, üç kanalın en geniş olanıdır — mesajlar düzenlenebilir ve düğmeler boldur — dolayısıyla bir yanıt, yanıt gelirken büyüyen tek bir mesajdır ve menünün tamamı bir ekrana sığar.

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

Bir görev çalışırken sunulan tek şey **Stop**'tur.

## Çalıştırmak

```bash
comodor slack start                # here, holding this terminal
comodor slack start --background   # detached; survives closing it
comodor slack stop
comodor slack service install      # starts at login, survives a reboot
comodor slack service show         # read the unit before trusting it
```

Günlük, yapılandırmanızın yanındaki `slack.log`'dur; değiştirilmek yerine sona eklenir.

Her platformda bir **kullanıcı** servisi — systemd, launchd, Görev Zamanlayıcı — asla sistem servisi değil. Bu, dosyalarınızı sizin kimlik bilgilerinizle okuyan ve yazan bir ajandır ve o dosyaların sahibi olan kişiden fazla yetki hiçbir şey getirmez.

## Tarayıcı panelinden

`comodor web` → **Admin** → **From your phone**, bunların tümünü bağlar, eşleştirir, başlatır ve durdurur — terminalsiz. O denetimler yalnızca Comodor'un üzerinde çalıştığı makineden gelen istekleri yanıtlar: bir bot tokenı, ona uzaktan kumandayı tokenı elinde tutan herkese verir.

## Nasıl inşa edildi

Yeni bir bağımlılık yok. Web API'si, bu projenin hâlihazırda sahip olduğu HTTP istemcisi üzerinden `POST /api/chat.postMessage`'tır ve Socket Mode, Chrome'u sürmek için yazılan websocket istemcisi üzerinde çalışır — Slack eklemenin hiçbir paket eklememiş olmasının nedeni budur.

Soket döngüsünün dikkatli olduğu üç şey; her biri, bir botun kimseye haber vermeden susmasının bir yoludur:

- **Her zarf onaylanır.** Slack, kendisinden haber almadığını yeniden teslim eder ve komut çalıştıran bir ajan için bir mesajın üç tura dönüşmesi yalnızca gürültü olmanın ötesindedir.
- **`disconnect` olağandır.** Slack bağlantıları bir takvime göre döndürür. Bunu bir başarısızlık saymak, saat başı ölen bir bot üretir.
- **Sessiz bir çalışma alanı yine de ping alır.** En çok önemli olan durum — bir saattir kimse ona mesaj atmamıştır — tam da düşmüş bir soketin mahvettiği durumdur.

## Yapmayacakları

- Eşleşmemiş herhangi birine yanıt vermek.
- Eklendiği bir kanaldaki her şeye yanıt vermek.
- Bir projenin `.comodor/config.json` dosyasından bir token ya da izinli bir hesap almak. Kendi yazarını o listeye ekleyebilen bir depo bir arka kapı olurdu.
- `slack writes on` olana dek hiçbir şeyi düzenlemek.
- İki tokenı da yazdırmak. İkisi de yükselen her hatadan sansürlenir.
