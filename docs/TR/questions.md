# Sorular

Belirsizliğin iki kötü sonu vardır. Ajan bir okuma seçer, yanlış şeyi inşa
eder ve size bir gözden geçirme turuna mal olur. Ya da düzyazıyla, soru soru
sorar ve siz tek bir ekranda çözülebilecek bir şeyi dört turda
çözebilirdiniz.

Comodor üçüncü bir yol izler. Bir istek birden fazla şekilde okunabildiğinde,
ajan önce *emin olmadığı her şeyi* çözer, sonra size kısa bir çoktan seçmeli
form olarak sunar — üç veya dört soru, yaklaşık on beş saniyede yanıtlanır,
tek bir satır yazılmadan önce.

"add rate limiting to the web server" istendiğinde, on dosya okudu ve sonra
şunu sordu:

```
┏━  3 questions  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                          ┃
┃    ☐  Client identity   ☐  Over-limit   ☐  Scope                         ┃
┃                                                                          ┃
┃  How should clients be identified for rate limiting?                     ┃
┃                                                                          ┃
┃   › ☐ By IP address (recommended)                                        ┃
┃        The server already reads client_address for the loopback check.   ┃
┃     ☐ By token                                                           ┃
┃     ☐ Something else                                                     ┃
┃                                                                          ┃
┃    0 of 3 answered                                                       ┃
┃                                                                          ┃
┗━━━━━━━━━━━━━━  ↑↓ move · ←→ question · space pick · enter next · esc  ━━┛
```

İlk seçeneğin ikinci satırına dikkat. Sormadan önce `web/server.py`'yi
okumuştu ve soru, o okumanın çözemediği karar hakkındadır.

## Terminalde

```
left / right      previous and next question
up / down         move within the options
space             pick — and toggle, when several answers may apply
enter             pick, then jump to the next unanswered question;
                  on the last one, send
ctrl+s            send from anywhere
escape            close without answering
```

Sekme şeridi soru başına bir işaret taşır, böylece her birini ziyaret
etmeden hangilerinin hâlâ beklediğini bir bakışta görürsünüz.

## Tarayıcıda

Bir pencere (dialog) olarak aynı form. Sekmelere tıklayın ya da ok tuşlarını
kullanın, bir seçeneğe tıklayın ve **Send**'e basın. `Escape` kapatır.

## Son satır

Her soru, **Something else** ve yazılacak bir kutuyla biter. Model tarafından
değil, Comodor tarafından eklenir ve model onu kaldıramaz — satırın tamamı,
modelin düşünmeyi başaramadığı şeyi kapsaması içindir. İçine yazmak, seçili
olan herhangi bir seçeneğin yerine geçer ve bir seçenek seçmek yazılanı
temizler; böylece bir soru, birbiriyle çelişen iki cevapla bir daha asla
geri dönmez.

## Atlamak

Soruları yanıtlanmamış bırakarak bir formu göndermek sorun değildir ve onu
kapatmakla aynı şey değildir. Ajana, hangilerini boş bıraktığınız ve bu
yüzden onları kısıtlamadığınız tam olarak söylenir — o yüzden o, bunlara
kendisi karar verir ve hangi yönde gittiğini söyler.

Formu tamamen kapatmak (**Not now** veya `escape`) ajana makul varsayılanlarla
devam etmesini ve **bir daha sormamasını** söyler. Az önce birinciyi kapatmış
birine sunulan ikinci bir form, böylesi bir özelliğin sevilmez olmasına yol
açan davranıştır.

## Ne zaman sormaz

Tasarım gereği, tesadüf değil:

- Projeyi okuyarak öğrenebileceği her şey. Önce okur.
- Devam etme izni. Onay istemi tam olarak bunun içindir.
- Planını size geri onaylatmak.
- Bariz bir varsayılanı olan bir karar. Varsayılanı alır ve bunu yaptığını
  size söyler.

## Sınırlar

En fazla dört soru ve her biri en fazla dört seçenek — artı kendi-cevabınızı-
yazın satırı, bu dörtten birini harcamaz. Bundan fazlası hızlı bir form
olmayı bırakır ve bir mülakata döner; altı cevaba ihtiyaç duyan bir ajan,
önemli olan dördünü sormayı ve gerisini kendisi çözmeyi bilmelidir.

Form otuz dakika bekler. Ondan sonra yanıtlanmamış olarak geri döner ve ajan
devam eder; böylece kimse olmayan bir makinede açık bırakılmış bir form, bir
çalıştırmayı sonsuza dek meşgul edemez.

## Diğer modeller için

Araç `ask` adını taşır ve `SAFE`'tir, yani Plan modunda da mevcuttur —
belirsizliğin en çok ağır bastığı an planlama anıdır.

Modelin ona ne kadar kolay davrandığı değişir. Test edilen her model, istek
açıkça gerektirdiğinde sorar ve gerekmediğinde sessiz kalır; ama sizinki bir
tahmin üzerine inşa ediyorsa, kendi mesajınızda *"herhangi bir karar vermeden
önce bana soracağın şeyler varsa sor"* demek anında çözer.
