# Telefonunuzdan

Comodor bir Telegram botu üzerinden sürebilir: bir görev gönderin, çalışmasını izleyin, sorularını yanıtlayın ve onu durdurun — terminal açmadan.

**İlk çalıştırma kurulumu bunu sorar.** Altı sorunun sonuncusu bir bot bağlamayı önerir, tokenı oracıkta Telegram'la denetler ve sihirbaz bitmeden hesabınızı eşleştirir. *Şimdi değil* dediniz ya da zaten yapılandırılmış bir makine kuruyorsanız:

```bash
comodor telegram connect <token>   # a bot from @BotFather
comodor telegram pair              # add your account
comodor telegram start             # run it
```

Tarayıcı arayüzünün çalıştırdığı aynı ajan oturumunu çalıştırır. Her şey bir düğmedir; yazmak görevin kendisi içindir.

## Bot almak

Telegram'da [@BotFather](https://t.me/botfather) hesabına mesaj gönderin, `/newbot` yazın, ona bir ad ve `bot` ile biten bir kullanıcı adı verin. Bir tokenla yanıtlar:

```
1234567890:AAF…
```

```bash
comodor telegram connect 1234567890:AAF…
```

## Eşleştirme

**Bir botun kullanıcı adı herkese açıktır.** Onu bulan herkes ona mesaj gönderebilir ve bu bot dosyalarınızı okuyabilir. Bu yüzden yalnızca sabit bir sayısal Telegram kullanıcı kimliği listesine yanıt verir ve kimseye değil.

```bash
comodor telegram pair
```

Bu, altı haneli bir kod yazdırır. Onu Telegram'da botunuza gönderin ve hesabınız eklenir. Kod bir kez çalışır ve beş dakikada sona erer.

Diğer herkes **sessizlik** alır — bir reddedilme değil. "İzin verilmedi" diyen bir bot bir yabancıya var olduğunu, bir Comodor olduğunu ve girilmeye değer bir liste bulunduğunu söylemiş olur.

```bash
comodor telegram status         # who may talk to it
comodor telegram forget 12345   # revoke one account
comodor telegram forget all     # revoke everybody
```

## Yapabildikleri ve yapamadıkları

**Varsayılan olarak okur ve planlar, hiçbir şeyi değiştirmez.** Terminal neye ayarlıysa ayarlı olsun bir Telegram oturumu plan modunda tutulur.

Bu bilinçlidir. Bir telefonla, sırada beklerken, başparmakla bir kabuk komutunu onaylamak, aynı onayın klavye başında verilmesinden daha az dikkatle verilmiş bir karardır — ve sonuçları birebir aynıdır.

```bash
comodor telegram writes on      # let it edit files and run commands
comodor telegram writes off
```

Yazmalar açıkken bile önce sorar ve onay, sohbetteki bir düğmedir:

```
Comodor wants to run
  npm test

  ✓  Yes, once
  ✓✓ Yes, and stop asking this session
  ✗  No
```

En geniş taahhüt, başparmağınızın altındaki ilk düğme asla değildir — bir telefonda düğmeler birbirine yakındır ve "her zaman" geri alınamaz.

## Düğmeler

`/start`, modelle, klasörle ve neye izni olduğuyla yanıtlar; ayarlar da altında durur. Bunlar bir *Ayarlar* düğmesinin ardında değil ilk ekrandadır; çünkü bir botun neye yöneltildiğini bilmek herkesin öğrenmek istediği ilk şey ve değiştirmek istediği ilk şeydir.

| | |
|---|---|
| **New chat** | Şimdiye kadarki sohbeti unut |
| **History** | Önceki herhangi bir sohbeti, bütün olarak yeniden aç |
| **Stop** | Çalışanı kes — çalışırken *New chat*'in yerine geçer |
| **Mode** | İş, plan ya da sohbet; her biri har har yazılmış |
| **Status** | Model, klasör, bağlam, harcama |
| **Model** | Sağlayıcının sunduğu her model; geçiş için dokun |
| **Folder** | Hangi projeyle sınırlı |
| **Skills** | Kitaplıktan birini kur ya da kaldır |
| **Rules** | Düzeltmelerinizden ne öğrendiği ve kaç tane |
| **Settings** | Gerisi — maliyet ve ne yapabilir |
| **Help** | Her şeyin ne yaptığı, sohbetten çıkmadan |

Ajan bir karar gereksindiğinde düğmelerle de sorar — terminalde soracağı aynı sorular, ekran başına bir tane, düşünmediği her şey için **Write my own** ile birlikte.

Bir ekrandan uzun listeler — modeller, beceriler, geçmiş — bir seferde altı adet olacak biçimde sayfalanır, **Previous** ve **Next** ile birlikte. Telegram seksen düğmeyi gönül rahatlığıyla çizer ve kimse onları kaydırmaz.

## Çalıştırmak

Üç yol, ne kadar dayanmasını istediğinizin sırasına göre.

```bash
comodor telegram start                # here, holding this terminal
comodor telegram start --background   # detached; survives closing the terminal
comodor telegram service install      # starts at every login, survives a reboot
```

**Ön planda** terminali tutar ve ne yaptığını gösterir. Kurulum sırasında kullanılacak odur ve bir şey çalışmadığında geri dönülecek odur.

**Arka planda** aynı süreçtir, onu başlatan terminalden kopmuş, ekrana değil bir günlüğe yazan. Terminali kapatmak, oturumu kapatmak, oturumu bitirmek — hiçbiri onu beraberinde götürmez.

```bash
comodor telegram stop        # end it
comodor telegram status      # is it running, since when, and as which pid
```

Günlük, yapılandırmanızın yanındaki `telegram.log`'dur ve değiştirilmek yerine sona eklenir — bir botun dün gece neden durduğu, yeniden başlatmanın sileceği satırlarda durur.

**Oturum açılışında** bu, işletim sisteminin işidir, bizim değil: bir programın kendi başına başlattığı hiçbir şey makinenin yeniden başlamasından sağ çıkmaz.

```bash
comodor telegram service show        # read the unit before trusting it
comodor telegram service install
comodor telegram service uninstall
```

| | |
|---|---|
| Linux | `~/.config/systemd/user` içinde bir systemd **kullanıcı** birimi |
| macOS | `~/Library/LaunchAgents` içinde bir LaunchAgent |
| Windows | Oturum açılışında çalışan bir Görev Zamanlayıcı görevi |

Üçünde de kullanıcı servisi, asla sistem servisi değil. Bir sistem servisi root ya da SYSTEM olarak çalışır; bu ise dosyalarınızı sizin kimlik bilgilerinizle okuyan ve yazan bir ajandır — o dosyaların sahibi olan kişiden fazla yetki hiçbir şey getirmez ve yanlışsa her şeyi kaybettirir.

`service show`, `service install` yazmadan önce birimi yazdırır. Kimseden gösterilmemiş bir arka plan süreci (daemon) tanımına güvenilmesi istenmemelidir.

Klasör üçünde de önemlidir: ajan yalnızca başlatıldığı dizinin içinde okur ve yazar ve bot onun içinde çalışacak olan o dizindir.

## Nasıl inşa edildi

Yeni bir bağımlılık yok. Bot API'si, bu projenin hâlihazırda sahip olduğu HTTP istemcisi üzerinden döngüdeki `getUpdates` ve `sendMessage`'dır — `python-telegram-bot` tekerlekteki en büyük şey olurdu, onun için.

Yanıt, token başına değil bir zamanlayıcıyla düzenlenir. Telegram her düzenleme için bir gidiş-dönüş ücretlendirir ve onları hız sınırına tabi tutar; token başına düzenleme, sonunda bir anda gelecek biçimde kısılan bir mesaj üretir.

Bot bir güncelleme ofseti tutar ve giderken onu ilerletir. Bu olmadan, bir yeniden başlatma botun şimdiye dek aldığı her mesajı yeniden oynatır — komut çalıştıran bir ajan için bu, yalnızca gürültü olmanın ötesindedir.

## Yapmayacakları

- Eşleşmemiş herhangi birine yanıt vermek ya da nedenini söylemek.
- Bir projenin `.comodor/config.json` dosyasından bir token ya da izinli bir hesap almak. Kendi yazarını o listeye ekleyebilen bir depo bir arka kapı olurdu ve tarayıcının ya da ekranın aksine, bunun olduğunu görülebileceği ekranda hiçbir şey olmazdı.
- `telegram writes on` olana dek hiçbir şeyi düzenlemek.
- Tokenı yazdırmak. O, her Bot API URL'sindedir; bu yüzden yükselen her hatadan arındırılır.
