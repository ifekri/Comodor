# Ajan neler yapabilir

On üç araç. Her biri bir risk düzeyi bildirir; bu, önce sorup sormayacağına
karar verir — bkz. [Güvenlik](safety.md#risk-tiers).

---

## Dosyalar

| | Risk | |
|---|---|---|
| `read_file` | safe | Bir metin dosyası oku. Akış halinde çalışır, böylece büyük bir günlüğün bir dilimi bile erişilebilir |
| `list_dir` | safe | Bir dizinin girdileri, boyutlarıyla |
| `glob` | safe | Dosyaları ad örüntüsüne göre bul — `src/**/*.py` |
| `grep` | safe | İçerikleri bir düzenli ifadeyle ara |
| `write_file` | write | Bir dosya oluştur veya tamamen değiştir |
| `edit_file` | write | Bir dosyadaki birebir bir string'i değiştir |

Her şey, `safety.workspace_only`'yi kapatmadıkça proje klasörüne
hapsedilmiştir.

Var olan bir dosyada değişiklik için `edit_file`, `write_file`'a tercih
edilir: daha küçüktür, bir fark (diff) olarak gözden geçirilebilir ve
dosyanın geri kalanını sessizce kaybedemez.

---

## Şeyleri çalıştırmak

| | Risk | |
|---|---|---|
| `run_shell` | dangerous | Çalışma alanında bir kabuk komutu |
| `run_python` | dangerous | Kısa bir Python parçacığı, bir alt süreçte |

İkisi de çalıştırmadan önce sorar, ikisi de `safety.deny_commands`'a
tabidir ve ikisinin de çıktısı sınırlanır — bkz. [Çıktı çok büyükken](#when-output-is-too-big).

Arayüzde modeli tamamen atlayabilirsiniz:

```
!git status
```

Çalıştırır, çıktıyı size gösterir ve modele asla söylemez. Sormaktan daha
hızlı ve daha ucuzdur.

---

## Web

| | Risk | |
|---|---|---|
| `web_fetch` | dangerous | Bir URL indir ve okunabilir metnini döndür |
| `web_search` | dangerous | Ara, başlıkları, URL'leri ve özet parçacıklarını döndür |
| `browse` | dangerous | Gerçek bir tarayıcı — JavaScript, çerezler, oturum açmalar |

`web_fetch` ucuza gelen olandır: sayfayı metne indirir. Sayfa bir belgeyse
bunu kullanın.

`browse`, sayfa bir uygulama olduğundur — JavaScript, bir oturum açma ya da
bir tıklama gerektiren bir şey. [Tam rehber](browser.md).

---

## Makine

| | Risk | |
|---|---|---|
| `computer` | dangerous | Fare, klavye ve ekran, herhangi bir uygulamada |

Kapalıdır, siz açarsınız; açtığınızda bile izin verilene kadar
kullanılamaz. [Tam rehber](computer.md). Şimdilik yalnızca Windows.

---

## Takipte kalma

| | Risk | |
|---|---|---|
| `todo_write` | safe | Kenar çubuğunda gördüğünüz görev listesi |

Ajan kendi planını buraya yazar. Süsleme değildir — uzun bir görevin
tutarlı kalmasının ve nerede olduğunu görebilmenizin yoludur.

---

## Bazen orada, bazen değil

Comodor, modelin gerçekten kullanabileceği bir aracı sunar. Görebildiği ama
asla başarıyla kullanamayacağı bir araç, her turda boşa bir çağrı daveti
çıkarır.

| | Ne zaman görünür |
|---|---|
| `read_skill_file` | kurduğunuz bir skill dosya paketliyorsa |
| `search_history` | aranacak geçmiş oturumlar varsa |
| `delegate` | bir alt ajan başlatılabiliyorsa |
| `computer` | platformda bir backend var **ve** siz onu etkinleştirdiyseniz |
| MCP araçları | bir sunucu yapılandırılmış ve etkinse |

`browse`'ın iki uygulaması vardır: Chrome, Chromium, Edge veya Brave
kuruluysa gerçek tarayıcı, hiçbiri kurulu değilse metin tarayıcısı. İkisine
de `browse` denir, çünkü "tarayıcı" denen iki şey arasında seçim yapmak,
modelin harcamaması gereken bir turdur.

---

## Çıktı çok büyükken

Elli bin satır basan bir komut, işe yaramazlığa kırpılmaz ve bağlamı
patlatmaz.

Sığan şey modele gider — baş ve kuyruk, çünkü cevap genellikle oralarda
olur. Gerisi `~/.comodor/output/` altındaki bir dosyaya yazılır ve modele
yol ile nasıl okunacağı söylenir. Yani gerekirse gidip bakabilir ve
bakmıyorsa hiçbir şey ödemez.

```json
{ "agent": { "max_tool_chars": 12000 } }
```

---

## Alt ajanlar

`delegate`, **git worktree** içinde ikinci bir ajan çalıştırır — aynı
deponun izole bir çıkışı. Orada çalışır ve değişiklikleri, üç yönlü bir
birleştirmeyle uygulanan bir yama olarak geri gelir.

Belleği yoktur, daha fazla delege edemez ve ekran ona verilmez. Üstten gelen
iptali devralır, yani `Esc` onu da durdurur.

Gerçekten ayrı bir iş için kullanışlıdır — "ben çalışmaya devam ederken bu
modülü yeni API'ye taşı" — başka her şey için israftır.

---

## MCP araçları

Etkin bir Model Context Protocol sunucusunun sağladığı her şey, yerleşik
araçların yanında görünür ve tam olarak aynı izin kapısından geçer.

```bash
comodor mcp list
```

[Tam rehber](mcp.md).

---

## Ayrıca bakın

- [Güvenlik ve izinler](safety.md) — her düzeyin pratikte anlamı
- [Arayüz](interface.md) — araçların çalışmasını izlemek
- [Skill'ler](skills.md) — bunları belirli bir iş için *nasıl* kullanacağını öğretmek
