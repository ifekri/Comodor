# Arayüz

Gördüğünüz şey, bastığınız tuşlar ve 29 komutun tamamı.

```bash
comodor          # start it
comodor --demo   # the whole interface, offline, no key
```

---

## Düzen

```
┌────────────────────────────────────────────────────────────────────────┐
│  Comodor                              Anthropic · claude-sonnet-5      │
│  ────────────────────────────────────────────────────────────────────  │
│                                                                        │
│  TASKS                    > fix the failing parser test                │
│  ● read the test          ▸ read_file  tests/test_parser.py     0.1s   │
│  ◐ find the cause         ▸ run_shell  pytest tests/test_pa…    2.3s   │
│  ○ fix it                                                              │
│                           The test expects `parse("")` to raise, but…  │
│                                                                        │
│  ────────────────────────────────────────────────────────────────────  │
│  ▌Type a task, or / for commands                                       │
│                                                                        │
│  act · loop on · 12% of 1M · $0.03      ⏎ send  ^O attach  F3 mode     │
└────────────────────────────────────────────────────────────────────────┘
```

**Kenar çubuğu**, varsa plan buradadır. `F2` gizler — dar bir terminalde
yapmaya değer.

**Durum satırı** modu, yinelenip yinelenmediğini, bağlamın ne kadar dolu
olduğunu ve bu oturumun neye mal olduğunu gösterir. Bağlam rakamı gerçektir:
modeli takip eder, yani milyon tokenlik bir modelden 128k'lık birine geçmek
onu anında değiştirir.

Yaklaşık 60 sütundan yukarısında çalışır. Onun altında kenar çubuğu kendi
kendine katlanır. `comodor preview 80x24` oturum başlatmadan herhangi bir
boyutta görüntüler.

---

## Modlar

| Mod | Ajanın yapabilecekleri | |
|---|---|---|
| **act** | Her şey, yazma işlemlerinden ve komutlardan önce sorarak | varsayılan |
| **plan** | Yalnızca okuma. Yazma yok, komut yok, ağ yok | "ne yapardın?" için |
| **chat** | Hiçbir araç yok | yapıştırdığınız bir kod hakkında soru için |

`F3` aralarında dolaşır. `/mode plan` doğrudan birini ayarlar.

Plan modu gerçekten salt okunurdur — izin katmanında uygulanır, modele
nazikçe yalvararak değil. "safe" üzerindeki riske sahip bir araç çalıştırılmadan
önce reddedilir.

---

## Tuşlar

| | |
|---|---|
| `Enter` | gönder |
| `Ctrl+J` | bir mesajın içinde yeni satır |
| `Esc` | o anda yaptığı şeyi durdur |
| `Ctrl+C` | durdur; çıkmak için iki kez |
| `F1` | yardım |
| `F2` | kenar çubuğu |
| `F3` | mod |
| `F4` | döngü aç/kapa |
| `F5` | gateway |
| `Ctrl+O` | dosya ekle |
| `Ctrl+L` | konuşmayı temizle |
| `PgUp` `PgDn` | kaydır |
| `Ctrl+↑` `Ctrl+↓` | önceki ve sonraki mesajlar |
| `!command` | modele sormadan doğrudan bir kabuk komutu çalıştır |

`!`'i hatırlamaya değer. `!git status` çalıştırır ve çıktıyı size gösterir;
model soruyu asla görmez. Sormaktan daha ucuz ve hızlıdır.

---

## Komutlar

`/` yazın ve liste siz yazdıkça filtrelenir.

### Ne yaptığını değiştirmesini isteyin

| | |
|---|---|
| `/mode [act\|plan\|chat]` | neye izni olduğu |
| `/loop` | bitene kadar çalışmaya devam et, ya da bir kez yanıtla |
| `/model [id]` | modeli seç — bir liste, ya da ismini verin |
| `/provider [name]` | sağlayıcıyı seç |
| `/gw` | gateway: sağlayıcılar arasında maliyet, hız veya kaliteye göre yönlendirir |

### Öğretin

| | |
|---|---|
| `/good` | o cevap doğrudu |
| `/bad` | o cevap yanlıştı |
| `/teach <text>` | bunu hatırla |
| `/memory` | ne öğrendiği |
| `/rules` | kodunuzdan ve düzenlemelerinizden çıkardığı ev kuralları |
| `/progress` | geliştiğine dair kanıt |
| `/skills` | iş uyuştuğunda izlediği prosedürler |

`/good` ve `/bad`, onun için yapabileceğiniz en ucuz şeydir. Bkz.
[Nasıl öğrenir](learning.md).

### Geri al ve geriye bak

| | |
|---|---|
| `/undo` | değiştirdiği son dosyayı eski haline getir |
| `/clear` | taze bir konuşma başlat |
| `/resume [id]` | daha önceki bir oturumu yeniden aç |
| `/search <text>` | önceki bir konuşmada bir şey bul |
| `/export [path]` | bu oturumu bir dosyaya yaz |

### Daha uzağa ulaşmasını sağlayın

| | |
|---|---|
| `/computer [15m\|1h this app\|stop]` | ekranınızı kullanmasına izin verin — [rehber](computer.md) |
| `/mcp` | MCP sunucuları ve araçları — [rehber](mcp.md) |
| `/attach <path>` | bir sonraki mesaja dosya ekle |

### Onu rahatlatın

| | |
|---|---|
| `/settings` | şu anda ne yapılandırılmış |
| `/approve [writes\|shell\|all]` | bunlardan önce sormayı bırak |
| `/theme [name]` | ember, midnight, matrix, mono |
| `/save` | geçerli ayarları yapılandırma dosyanıza yaz |
| `/cost` | tokenler, harcama ve önbelleğin tasarruf ettirdikleri |
| `/copy [all\|task]` | son cevabı ya da her şeyi panoya kopyala |
| `/mouse [on\|off]` | fare takibi, böylece metni kendiniz seçebilirsiniz |
| `/help` | bunların tümü, arayüzün içinde |
| `/quit` | çık |

**`/save` yalnızca seçtiklerinizi yazar.** Deponun ayarlarını değil,
ortamınızda tuttuğunuz bir anahtarı değil, tek bir çalıştırma için
geçirdiğiniz bir `--model`'i değil. Bkz.
[Yapılandırma](configuration.md#what-save-writes).

---

## Onaylar

Ajan bir dosyaya yazmak ya da bir komut çalıştırmak istediğinde:

```
  Write  src/parser.py
  ────────────────────────────────────────────
   - def parse(text):
   -     return text.split(",")
   + def parse(text):
   +     if not text:
   +         raise ValueError("nothing to parse")
   +     return text.split(",")

  [a] allow   [A] allow always this session   [d] deny
```

`A`, oturum boyunca, işin türüne göre hatırlar — yazma işlemlerine izin
vermek komutlara izin vermez.

Reddetmek boşa gitmez. Bir ret, arayüzün topladığı en net tercih sinyalidir
ve öğrenme motoruna gider: ajan o öneriyi bir daha sunma ihtimali daha
düşüktür.

Hiç sorulmamak için:

```
/approve writes      files, yes; commands, still ask
/approve all         everything
```

Her şey yine de checkpoint'lenir. `/undo` her koşulda çalışır.

---

## Metni dışarı kopyalama

Fare takip edilirken sürükleme Comodor'a aittir ve terminal onu asla
görmez — yani olağan seç-kopyala çalışmaz. Üç çözüm yolu:

```
/copy              the last answer
/copy all          the whole conversation
/copy task         the last thing you asked for
/mouse             mouse tracking off, so selection works as usual
```

`/copy`, Windows veya macOS'ta hiçbir şeyin kurulmasını gerektirmez.
Linux'ta `wl-copy`, `xclip` veya `xsel` kullanır, hangisi varsa, ve hiçbiri
yoksa hangisinin eksik olduğunu söyler.

SSH üzerinden bir escape dizisine düşer, *sizin* terminalinizden *sizin*
panonuzu ayarlamasını ister — böylece bir sunucudaki ajandan gelen metin,
yapıştırabileceğiniz yere gelir, panosu olmayan bir sunucuya değil.

Çoğu terminal ayrıca **Shift** basılıyken seçim yapmanıza izin verir; bu,
takibi kapatmadan fare takibini aşar.

---

## Kim konuşuyor

Her tur, sakin bir bant üzerinde durur — bir ton, yazdıklarınızın arkasında;
başka bir ton, cevabın arkasında:

```
▌ › why does the parser drop the last field?              ← warm

▌   Because split is called with a maxsplit of 2 …        ← neutral
▌
▌   ┌─ python ────────────────────────┐
▌   │ return text.split(',', 2)       │
▌   └─────────────────────────────────┘
```

Kasıtlı olarak kısık. Bu, dakikalarca okuduğunuz gövde metninin
arkasındadır ve kendi varlığı olan bir arka plan kelimelerle yarışır. Her
temanın kendi çifti vardır, arka planından birkaç yüzde uzakta; `mono`'nun
yoktur, çünkü öncülü renksizlik olan bir tema ikisini istemez.

Dikey alan maliyeti yoktur — renk değişimi sınırın kendisidir.

---

## Sağdan sola metin

Farsça, Arapça ve İbranice, satırlarının başladığı sağa doğru dizilir,
onlara uyan bir yazı tipi yığınıyla. Karışık paragraflar — Farsça bir
cümlenin içinde bir İngilizce tanımlayıcı — dosya başına değil satır
başına ele alınır; teknik bir konuşmada gerçekten olan da budur.

---

## Temalar

```
/theme midnight
```

`ember` (varsayılan, sıcak kehribar), `midnight` (serin mavi), `matrix`
(yeşil), `mono` (hiç renk yok).

`--ascii`, kutu çizim karakterlerini, onlara sahip olmayan terminaller için
ASCII ile değiştirir. Ortamınızdaki `NO_COLOR` dikkate alınır.

---

## Ayrıca bakın

- [Terminalden](cli.md) — arayüz olmadan aynı güç
- [Ajan neler yapabilir](tools.md) — o `▸` satırlarının ardındaki araçlar
- [Güvenlik](safety.md) — onay istemlerinin koruduğu şey
