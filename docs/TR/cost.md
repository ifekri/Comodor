# Maliyet

Bir oturumun neye mal olduğu ve onu daha kötü yapmadan nasıl daha ucuza
getireceğiniz.

```
/cost
```

```
This session

- prompt tokens: 84,210
- output tokens: 3,180
- served from cache: 72,418 (86% of the prompt)
- cost: $0.1904
- saved by caching: $0.4126 (68%)
- context used: 87,390 / 1,000,000
- compactions: 0

Brain

- lessons: 812
- skills: 4
- episodes: 137 (83% succeeded)
```

---

## İstem önbellekleme, işin çoğu bu

Her istek, değişmeyen kısımları yeniden gönderir — sistem istemi, araç
şemaları, şimdiye kadarki konuşma. Sağlayıcılar, bayt bayt özdeş bir öneki
yaklaşık onda bir fiyata yeniden sunar.

Comodor bunun üzerine kuruludur ve varsayılan olarak açıktır:

```json
{ "agent": { "prompt_cache": true, "prompt_cache_ttl": "5m" } }
```

Gerçek oturumlar üzerinde ölçülmüştür: **girdi tokenlerinin %86'sı
önbellekten sunuldu**.

### Sistem istemine neden dinamik hiçbir şey girmez

Önbellekleme yalnızca geçen seferkiyle bayt bayt özdeş bir önek üzerinde
çalışır. Sistem istemi *başlı başına önektir*. Tur başına değişen her şey —
hatırlanan dersler, eşleşen skill, günün saati — onu geçersiz kılar ve
siz her şeyin tam fiyatını, her turda ödersiniz.

Bu yüzden hatırlanan dersler *turun* üzerinde, kullanıcı mesajının bir
parçası olarak seyahat eder. Tek başına o değişiklik, ölçülen önbellek
isabet oranını %72'den %87'ye taşıdı.

Kendinize ait sürekli talimatlar ekleyecekseniz, onları değişken tutmak
yerine sabit olan `agent.system_prompt_extra`'ya koyun.

### Bir saatlik önbellek

```json
{ "agent": { "prompt_cache_ttl": "1h" } }
```

Bir kayıt *yazmak* yaklaşık %25 daha pahalıya mal olur ve onu beş dakika
yerine bir saat tutar. Bir oturuma tekrar tekrar dönüyorsanız değer;
tek seferlik bir iş patlaması için israftır.

---

## Tavanlar

```json
{
  "agent": {
    "max_steps": 0,
    "max_seconds": 3600,
    "max_cost_usd": 2.0
  }
}
```

Hangisi önce gelirse görevi durdurur ve `0`, sınır olmadığı anlamına gelir.
`--json` içindeki `stopped`, hangisi olduğunu söyler.

**Varsayılan olarak adım sınırı yoktur.** Gerçek bir kod tabanında
yirmi dört adım hiçbir şeydir — bir düzine dosyaya yayılan bir yeniden
düzenleme (refactor) onlara düşünüşünün ortasında taktı — ve adım sayısının
zararla hiçbir ilgisi yoktur: dosya okuyan on adım neredeyse hiçbir şeye mal
olmaz. Zarara karşılık gelen tavanlar zaman ve paradır ve onlar açık kalır.
Sert bir durdurma geri istiyorsanız `max_steps`'i bir sayıya ayarlayın.

Bunlardan biri bir görevi durdurduğunda, mesaj nasıl geçileceğini söyler ve
"continue" demek kaldığı yerden devam eder.

### Sınır ateşleyemediğinde

**Bir harcama sınırı yalnızca yayımlanmış bir oranı olan model için çalışır.**

Fiyatlandırma tablosu, emin olmadığı modeller için oranları bilinçli olarak
boş bırakır — bir fiyat uydurmak yanlış sayılar üretir, ki bu hiç olmamasından
daha kötüdür. Fiyatsız bir modelde maliyet sayacı sıfır gösterir, böylece
`spent >= max_cost_usd` asla doğru olmaz ve sınır asla ateşlenmez.

Comodor, sizi korunduğunuzu sanırken bırakmak yerine durumu söyler:

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Bir oturumun başında ve `comodor doctor` içinde söylenir:

```
  warn  spend limit    $2.00 per task cannot be enforced for gpt-4o
                       → No published rate is known for this model, so the
                         cost meter reads zero and the limit never fires.
                         The step and time limits still apply.
```

Kendi makinenizde çalışan bir model için farklı bir şey söyler, çünkü orada
zaten başlangıçta hiçbir şeye mal olmaz.

---

## Gerçekten paraya mal olan şey

**Ekran görüntüleri.** Varsayılan bütçede her biri yaklaşık 1.600 görsel
token — ve konuşmada kaldıkları her turda bir o kadar daha. Comodor son
ikisini tutar ve geri kalanını, bir tane olduğuna dair bir satırla değiştirir.
O olmadan, otuz adımlık bir masaüstü görevi, o zamandan beri tıklanmış
ekranları tanımlayan neredeyse elli bin tokenlik piksel taşır.

```json
{ "agent":    { "keep_screenshots": 2 } }
{ "computer": { "screenshot_tokens": 1600 } }
```

`screenshot_tokens`'i çok düşük ayarlamayın. Modelin okuyamadığı bir resim,
hiç resim olmamasından daha kötüdür: sormak yerine tahmin eder. Bkz.
[Ekranınızı kullanması](computer.md#screenshots-and-what-they-cost).

**Büyük araç çıktısı.** `agent.max_tool_chars` ile sınırlanır. Sığmayan,
modele nasıl okunacağı söylenen bir dosyaya yazılır, yani yalnızca bakarsa
öder.

**Yansıma (reflection).** Bir görevin sonunda bir model çağrısı. Onu daha
ucuz bir modele yönlendirin:

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

Ya da kapatın. Ücretsiz şerit — düzeltmeler, kurallar, duyurular — her iki
durumda da çalışmaya devam eder. [Nasıl öğrenir](learning.md#the-two-lanes).

**Tarayıcı, baktığında.** `browse` varsayılan olarak metin döndürür ve
yapıldığında ekran görüntüsü alır; çünkü bir sayfanın resmi her seferinde
aynı fiyata mal olur ve kırpılamaz.

---

## Hiçbir şey harcamamak

```bash
ollama pull qwen2.5-coder:14b
comodor setup       # choose Ollama
```

Bu belgelerdeki her şey, aksini söylemedikçe hiçbir maliyet olmadan çalışır.
[Model seçimi](models.md#running-it-locally-for-nothing).

---

## Ayrıca bakın

- [Model seçimi](models.md) — her sağlayıcının ne ücretlendirdiği
- [Yapılandırma](configuration.md#agent--how-it-works) — her düğme
