# Başka bir ajandan geçiş

Halihazırda **OpenClaw** veya **Hermes** kullanıyorsanız, Comodor kurulumunuzu
getirmeyi, ilk kez çalıştırdığınızda önerir.

API anahtarlarınızı çoktan bulmuş ve bir yere yapıştırmışsınızdır. Bunu
tekrarlamak kötü bir ilk izlenimdir.

---

## İlk çalıştırmada

```
 1/7  You already use OpenClaw
  OpenClaw  1 API key, the model (claude-sonnet-5), 1 skill
  /home/you/.openclaw

  Nothing is moved and nothing already set here is replaced.
  Keys are copied into your config; the other tool keeps working.

  1.  bring it over   keys, model and skills
  2.  keys only       leave the skills and the model
  3.  start fresh     import nothing
```

Soru yalnızca içe aktarılacak bir şey olduğunda görünür.

---

## Sonrasında

Onlardan birini daha sonra kurdunuz ya da "start fresh" dediniz ve fikriniz
değişti:

```bash
comodor import              # bring it across
comodor import --dry-run    # say what it would take, change nothing
comodor import --keys-only  # leave the skills and the model
```

İki kez çalıştırmak güvenlidir — ikinci seferde yeni bir şey olmadığını
söyler.

---

## Neler gelir

| | |
|---|---|
| **API anahtarları** | yorgunluğun tamamı. Onların `.env`'inden ve OpenClaw'ın satır içi JSON'undan |
| **Model** | Comodor onu barındırabiliyorsa |
| **Skill'ler** | her iki araç da aynı açık formatı yazar, yani bunlar kopyalanacak dosyalardır |

Baştan sona üç kural, çünkü bu başka bir programın dosyalarını okur:

- **Hiçbir şeyin üzerine yazılmaz.** Burada halihazırda yapılandırılmış bir
  anahtar kazanır; içe aktarma boşlukları doldurur.
- **Hiçbir şey taşınmaz.** Her okuma bir okumadır. Diğer araç, az önce
  çalıştığı gibi tam olarak çalışmaya devam eder.
- **Bozuk bir dosya atlanır, ölümcül değildir.** Değerin yarısı, diğer
  ajanı tuhaf bir durumda olan bir makinede çalışmasıdır.

---

## Neler gelmez, ve neden

**Onların hafızası.** Sessizce atlanmak yerine açıkça söylenir:

```
not imported: MEMORY.md — its memory is prose; this agent's is lessons with
confidence and evidence, and inventing those would poison recall
```

Comodor'un beyni, düzeltmelerden öğrenilen, güveni, kanıtı ve bir yarılanma
süresi olan derslerdir. Bir `MEMORY.md` düz yazıdır. Birini diğer olarak içe
aktarmak, kimsenin ölçmediği güvenler uydurur ve hiçbir zaman hak edilmemiş
girdilerle hatırlamayı doldurur. Daha iyi bilgilendirilmiş görünen ama daha
kötü bir ajan elde edersiniz.

**Kişilikler, mesajlaşma, metinden konuşmaya.** Comodor'un eşdeğeri yoktur
ve hiçbir şeye içe aktarılmış bir ayar, hiç ayar olmamasından daha kötüdür.

**Başka bir yerde saklanan bir anahtar.** OpenClaw, bir anahtarın bir dosyaya
veya bir komuta referans olmasına izin verir. Bunlar yazıldıkları makinede
anlamlıdır ve burada hiçbir anlam taşımaz, bu yüzden tahmin edilmek yerine
rapor edilirler.

---

## Skill'ler ve bilinmesi gereken bir şey

İçe aktarılan skill'ler ad alanlıdır — `review`, `openclaw-review` olur —
yani bir içe aktarma sizinkilerden birini asla sessizce değiştiremez.

Bir skill klasörü dosya dosya kopyalanır ve **kendi dışına bir bağlantı
içeren bir klasör reddedilir**. Bir skill, içeriği bir isteme okunan bir
dosyadır; başka bir programın skill'ler dizininde oturan `~/.ssh/id_rsa`
symbollü bir bağlantı, aksi halde içeri kopyalanır ve bir modele gönderilirdi.
Reddedilir ve adlandırılır:

```
not imported: the skill sneaky — it contains a link out of that folder
```

---

## Nereye bakar

| | |
|---|---|
| OpenClaw | `~/.openclaw`, `~/.clawdbot`, `~/.moltbot` |
| Hermes | `~/.hermes` |

Daha eski OpenClaw dizinleri gerçek makinelerde hâlâ vardır — iki kez
adlandırılmıştır — bu yüzden üçü de kontrol edilir.

Hiç bakmaması için:

```bash
export COMODOR_NO_IMPORT=1
```

---

## Ayrıca bakın

- [Başlangıç](getting-started.md) — ilk çalıştırmanın geri kalanı
- [Yapılandırma](configuration.md) — içe aktarılan ayarların nereye gittiği
- [Skill'ler](skills.md) — gelenlerle ne yapılacağı
