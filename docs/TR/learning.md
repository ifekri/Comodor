# Nasıl öğrenir

Çoğu ajan, oturum biter bitmez unutur. Bu, çıktısı hakkında neyi değiştirdiğinizi izler ve onu saklar.

---

## Fikir

Övgü ucuzdur, düzeltmeler pahalıdır; bu yüzden öğrenme kaynağı düzeltmelerdir.

Yazdığı bir dosyayı düzenlediğinizde ya da ona açıkça yanlış olduğunu söylediğinizde, bu bir **ders** olur: her seferinde tuttuğunda yükselen ve kullanılmadığında zayıflayan bir güvene sahip kısa bir kural. Dersler, durum benzer göründüğünde hatırlanır ve o tura enjekte edilir — asla sistem istemine değil; oraya konması istem önbelleğine mal olurdu.

Hiçbir şey makinenizden çıkmaz. Beyin, yapılandırma dizininizin altındaki bir SQLite dosyasıdır.

---

## İki şerit

### Refleks — bedava, anlık, hep açık

Model çağrısı yok, token yok, gecikme yok.

- **Düzeltmeler.** Yazdığı bir dosyada `"`'yi `'`'ye değiştirirsiniz. Bu bir diff'tir ve bir diff bir gerçektir.
- **Kurallar.** Mevcut kodunuzu başlangıçta bir kez okur ve ondan konvansiyonlar çıkarır — girinti, tırnak biçimi, testlerin nasıl adlandırıldığı.
- **Duyurular.** Bir kural uygulandığında bunu tek satırla söyler. Göremediğiniz bir kural, düzeltemeyeceğiniz bir kuraldır.
- **Ön getirme.** Hatırlama, siz hâlâ yazarken başlar.

Bu şerit, yansıma kapalıyken bile açıktır; çünkü bedava.

### Yansıma — bir model çağrısı, bir görevden sonra

Bir görevin sonunda ne olduğuna bakar ve hatırlaması gerekenleri yazar. Bu, bir çağrıya mal olur. İsterseniz daha ucuz bir model kullanın:

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

Ya da kapatın, Refleks kalsın:

```json
{ "learning": { "reflect": false } }
```

---

## Bilinçli olarak öğretmek

| | |
|---|---|
| `/good` | o yanıt doğrudu |
| `/bad` | o yanıt yanlıştı |
| `/teach we use pytest, never unittest` | bunu hatırla |

`/good` ve `/bad` tek tuş alır ve onun için yapabileceğiniz en ucuz şeydir.

Bir izin istemini reddetmek de ona öğretir. Bir red, arayüzün topladığı en net tercih sinyalidir ve ona öyle davranılır.

---

## Neyi bildiğini görmek

```
/memory
```

Aranabilir bir liste — her ders; onu tetikleyeni, söylediğini, türünü ve güncel güvenini gösterir:

```
┌─  Memory (23)  ────────────────────────────────────────────────────┐
│ ›  #41 writing Python strings                                      │
│      Use single quotes for string literals.  [style 91%]           │
│    #38 adding a test                                               │
│      Tests go in tests/, mirroring the src layout.  [layout 84%]   │
│    #29 adding a dependency                                         │
│      Ask before adding one; this project has exactly one.  [78%]   │
│    #12 parsing empty input                                         │
│      Raise, do not return an empty list.  [behaviour 62%]          │
└────────────────────────────────────────────────────────────────────┘
  ↑↓ move   enter open   type filter   esc close
```

`/memory <text>` arar. Birini açmak, zayıflamasını durdurmak için sabitlemenizi ya da yanlışsa silmenizi sağlar.

```
/rules
```

Siz ona söylemek yerine kodunuzdan çıkardığı ev kuralları.

---

## Çalışıp çalışmadığını görmek

```
/progress
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

**En üstteki satır, önemli olan satırdır.** Görev başına düzeltmeler düşmüyorsa öğrenme çalışmıyor demektir — panel bunu ya öyle ya böyle öne koyar, etkinliğin altına gömmek yerine. Tablodaki geri kalan her şey çabadır; o ise sonuçtur.

---

## Hatırlama ve neden sistem isteminde değil

Hatırlanan dersler, turun üzerinde, kullanıcı mesajının parçası olarak taşınır; sistem isteminde değil.

Bu, bir maliyet kararıdır. İstem önbellekleme yalnızca bayt-birebir aynı önek üzerinde çalışır ve sistem istem önektir. Oraya sorguya bağlı herhangi bir şey koymak, önbelleği her tek turda geçersiz kılar. Hatırlamayı tura taşımak, ölçülmüş önbellek isabet oranını %72'den %87'ye çıkardı. Bkz. [Maliyet](cost.md).

---

## Sizden öğrendiği sözcükler

*Sizin* sözcüklerinizden hangilerinin birlikte gittiğini de öğrenir; kendi tamamlanmış görevlerinizden — "the parser" ile "tokenise"ın kod tabanınızın aynı köşesine ait olduğunu. Token'a mal olmaz, model çağrısına da; saymadır.

Bir dersin "the tokeniser" için kaydedilmişken siz "the lexer" sorunca ortaya çıkmasını sağlayan şey budur.

```json
{ "learning": { "associative": true } }
```

---

## Kapsam

```json
{ "learning": { "share_scope": "project" } }
```

`project`, dersleri öğrenildikleri depoda tutar — doğru varsayılan; bir kod tabanındaki konvansiyon başkasında yanlıştır. `global`, onları her yerde paylaşır.

---

## Unutma

Kullanılmayan bir ders zayıflar. `half_life_days` (varsayılan 45) ne kadar hızlı olduğunu ayarlar ve `min_confidence` (0,15), altında hatırlanmayı bıraktığı tabandır.

Bu önemli: bir kod tabanı fikrini değiştirir ve iki yıllık bir konvansiyonu tam bir güvenle tutan bir ajan, unutmuş olandan daha kötüdür.

---

## Kapatmak

```json
{ "learning": { "enabled": false } }
```

Her şey yine çalışır. Yalnızca her oturuma bir yabancı olarak başlar.

---

## Nerede yaşar

```
~/.comodor/brain.db
```

SQLite. Sizin. `comodor uninstall` onu kaldırır ve ne kadar yer tuttuğunu söyler.

---

## Ayrıca bkz.

- [Beceriler](skills.md) — sizin yazdığınız yordamlar, onun çıkardığı dersler değil
- [Maliyet](cost.md) — hatırlamanın neden önekte değil turda olduğu
