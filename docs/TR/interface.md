# Arayüz

Ne gördüğünüz, neye bastığınız ve ekrandaki her şeyin nereden geldiği.

```bash
comodor          # başlatın
comodor --demo   # tüm arayüz, çevrimdışı, anahtarsız
```

Arayüz [Bun](https://bun.sh) üzerinde çalışır — `comodor doctor` var olup
olmadığını söyler. O olmadan `comodor run "..."` arayüzsüz tek bir işi yapar
ve `comodor web` tarayıcıya bir arayüz sunar.

Nasıl kurulduğu — sürdüğü çekirdek, aralarındaki protokol ve ekrandaki her
gerçeğin neden ekranın değil çekirdeğin olduğu — [tui-v2.md](../tui-v2.md)
içinde. Bu sayfa, onu kullanan kişi için kısa sürüm.

---

## Ekran

```
┌──────────────────────────────────────────┬───────────────────────┐
│ Comodor   ~/work/my-project  fake-1      │ Agents         1 live │
│                                          │  ● d1 running    12.3s│
│  You                                     │    survey the retries │
│  fix the failing parser test             │ Tasks            2/5  │
│                                          │  ◐ write the tests    │
│  Comodor                                 │  ● read the code      │
│  The test expects parse("") to raise, …  │  ○ run the suite      │
│  ✓ read_file  tests/test_parser.py  0.2s │                       │
│  ● run_shell  pytest tests/…     running…│                       │
│      collected 12 items                  │                       │
│                                          │                       │
├──────────────────────────────────────────┴───────────────────────┤
│ ▌ask for anything                                                │
├──────────────────────────────────────────────────────────────────┤
│  [ACT]   PLAN    ASK    Reads, writes and runs commands…         │
│ ● 1 agent  tab Mode  ctrl+b Work  ctrl+k Commands      42% ctx  │
└──────────────────────────────────────────────────────────────────┘
```

**Başlık** projeyi ve yanıt veren sağlayıcı ile modeli adlandırır. Bu,
çekirdeğin bildirdiğidir, bir yapılandırma dosyasının söylediği değil: model
değiştiğinde — buradan, başka bir istemciden ya da çekirdeğin kendisiyle —
başlık onu izler.

**Sohbet**, araç zaman çizelgesini içinde taşır. Her araç çağrısı, gerçekleştiği
yerde tek bir satır olarak durur: bir işaret (`●` çalışıyor, `✓` bitti, `×`
başarısız), ad, tek satırlık bir özet ve ne kadar sürdüğü. Çalışan bir araç
çıktısının son satırlarını gösterir; biten bir araç katlanır ve tıklandığında
çekirdeğin hâlâ tuttuğu şey açılır.

**Çalışma tezgâhı** — `Ctrl+B` — sohbetin dışındaki iştir: ajanın kendisi için
tuttuğu görev listesi ve başlattığı arka plan ajanları, her biri kendi
durumuyla. Dar bir terminalde sohbetin yanında değil üstünde açılır ve aynı
tuş onu kapatır.

**Alt bilgi**, basabileceklerinizi tuşların okunduğu aynı listeden yazdırır ve
sağlayıcının ölçtüğü yerde bu oturumun neye mal olduğunu gösterir.

---

## Tuşlar

| Tuş | Ne yapar |
|---|---|
| `Enter` | yazdığınızı gönderir |
| `Tab` / `Shift+Tab` | sonraki / önceki mod |
| `Ctrl+K` | komut paleti — her eylem, aranabilir |
| `Ctrl+B` | çalışma tezgâhını açar ya da kapatır |
| `End` | yukarı kaydırdıktan sonra en yeni çıktıya döner |
| `PageUp` / `PageDown` | sohbeti kaydırır |
| `Ctrl+R` | çekirdeğin reddettiği bir mesajı yeniden gönderir |
| `Ctrl+C` | yaptığı şeyi durdurur; boştayken çıkar |
| `Ctrl+D` | çıkar |
| `Esc` | paleti kapatır, bir alandan çıkar ya da bir kartın güvenli seçeneğini alır |

Alt bilginin gösterdiği her kısayol vardır; bağlı olmayan bir tuş için ipucu
yazdırılamaz.

---

## Modlar

```
ACT    okur, yazar ve komut çalıştırır; bir şeyi değiştirmeden önce sorar
PLAN   okur ve planlar; yazamaz, çalıştıramaz ya da hiçbir şeyi değiştiremez
ASK    konuşarak çözer; hiç araç yok
```

`Tab` aralarında döner. Etiket tuş inince değil, çekirdek onayladığında
hareket eder: tek bir gidiş-dönüş içindeki basışlar birikir — üç Tab, üçüncünün
gösterdiği yer için bir kez sorar — ve reddedilen bir değişiklik etiketi
oynatmak yerine bunu sözle söyler.

---

## Size bir şey sorduğunda

Bir izin kartı ya da soru formu, açık olduğu sürece klavyeyi alır; böylece bir
karar için basılan tuş aynı zamanda bir mesaj gönderemez.

- **Ok tuşları** seçenekler ya da sorular arasında gezer; **Enter** gönderir.
- **Esc** isteğin kendi güvenli seçeneğini alır — bir izin için bu *reddet*,
  önerilen bir mod değişikliği için *değişiklik yok* — ve kart hangisi
  olduğunu söyler. Asla hiçbir şeye izin vermez.
- *İzin ver* için tek tuşlu bir kısayol yoktur. İzin vermek, seçeneğe bir
  hareket ve onaylamak için bir hareket daha ister; böylece başka herhangi bir
  nedenle basılan bir tuş bir komuta yetki veremez.
- Kendiniz-yazın satırı sunan bir soru, `Space` ile bunun için bir alan açar;
  `Esc` formu iptal etmeden önce alandan çıkar.

Aynı anda iki şey bekleyebilir — iki paralel araç ayrı ayrı sorabilir — ve
geldikleri sırayla gösterilirler, hiçbiri kaybolmaz.

Kart açıkken mod tuşları çalışmaya devam eder. Palet çalışmaz: bir kararın
üstündeki bir başlatıcı, yanıtlanması gereken şeyi gizlerdi.

---

## Takip etmek

Uzun bir yanıt en yeni satırı görünür tutar. Yukarı kaydırın; takip durur. Yeni
çıktı sizi aşağı çekmez ve bir işaret aşağıda daha fazlası olduğunu söyler.
`End` canlı kuyruğa döner; yeni bir mesaj göndermek de aynısını yapar.

---

## Oturumlar

`Ctrl+K` → *Önceki bir sohbeti aç*, çekirdeğin sakladıklarını listeler ve
birini yerinde açar. Aynı depo tarayıcıya da hizmet eder; bu yüzden burada
başlayan bir sohbet orada yeniden açılabilir.

`comodor --resume` başlangıçta en yenisini yeniden açar; `--resume ID` birini
adlandırır.

---

## Metni dışarı kopyalamak

Terminalinizin izin verdiği şekilde fareyle seçin. `--theme` ve `--ascii`
bayrakları komutların yazdırdıklarına uygulanır — `setup`, `doctor`, `help` —
kendi tasarım belirteçlerinden çizen arayüze değil.

---

## Sağdan sola metin

Farsça, Arapça ve karışık satırlar terminale yazıldığı gibi aktarılır, program
tarafından asla ters çevrilmez. Karışık bir satırın ne kadar iyi şekillendiği
terminalin işidir ve bunu iyi yapanlar burada da iyi yapar.

---

## Ayrıca bakınız

- [tui-v2.md](../tui-v2.md) — arayüzün nasıl kurulduğu, neleri yapabildiği ve
  henüz neleri yapamadığı
- [questions.md](questions.md) — ajanın önünüze koyduğu formlar
- [safety.md](safety.md) — ne sorar, ne sormaz ve neden
- [computer.md](computer.md) — ekranınızı kullanmasına izin vermek
