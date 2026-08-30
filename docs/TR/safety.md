# Güvenlik ve izinler

Comodor'un makinenizde neler yapabildiği, önce neyi sorduğu ve siz ne
dediğinizden bağımsız olarak neyi yapmayacağı.

---

## Kısa sürüm

- **Okuma sessizdir.** Dosyaları listelemek, okumak, aramak — istem yok.
- **Yazma sorar.** Değişiklik olmadan önce farkı görürsünüz.
- **Komut çalıştırmak daha gürültülü sorar**, ağa ulaşmak veya ekranınızı
  sürmek de öyle.
- **Geri alınabilir her şey `/undo` ile geri alınır.**
- **Proje klasöründen dışarı çıkamaz**, siz bunu kapatmadıkça.
- **Bir depo, yukarıdakilerin hiçbirini değiştiremez.**

---

## Risk düzeyleri

Her araç bir tane bildirir. Düzey, çalışmadan önce ne olacağına karar verir.

| Düzey | Araçlar | Ne olur |
|---|---|---|
| **safe** | `read_file`, `list_dir`, `grep`, `glob`, `todo_write` | çalışır |
| **write** | `write_file`, `edit_file` | sorar, bir farkla (diff) |
| **dangerous** | `run_shell`, `run_python`, `web_fetch`, `web_search`, `browse`, `computer` | sorar |

**Plan modunda**, `safe`'in üzerindeki her şey çalıştırılmadan önce
reddedilir. Bu izin katmanında uygulanır, modele davranmasını söylemekle
değil.

**Chat modunda** hiç araç yoktur.

---

## İstem

```
  Run  pytest tests/ -x
  ────────────────────────────────────────────
  in ~/projects/api-server

  [a] allow   [A] allow always this session   [d] deny
```

`A`, oturum boyunca, işin türüne göre hatırlar — yazma işlemlerine izin
vermek komutlara izin vermez, `pytest`'e izin vermek `rm`'ye izin vermez.

Hiç sorulmamak için:

```
/approve writes      files yes, commands still ask
/approve shell       commands yes, files still ask
/approve all         everything
```

Ya da kalıcı olarak, yapılandırmanızda:

```json
{
  "safety": {
    "auto_approve_writes": true,
    "auto_approve_shell": false
  }
}
```

### Reddetmek ona öğretir

Bir ret, arayüzün topladığı en net tercih sinyalidir. Öğrenme motoruna gider,
böylece ajan aynı şeyi tekrar önerme ihtimali daha düşüktür. Reddetmek boşa
harcanan çaba değildir.

---

## Checkpoint'ler ve `/undo`

Ajanın yazdığı her dosya, önce checkpoint'lenir — önceki içerikler, projenin
altındaki `.comodor/checkpoints/` içinde tutulur.

```
/undo
```

değiştirdiği son dosyayı geri getirir. Bu, yazma işlemini onaylamış
olup olmadığınıza ve otomatik onayın açık olup olmamasına bakılmaksızın
çalışır. `/approve all`'ın makul bir şey olmasının sebebi budur.

Kapatmanız gerekiyorsa:

```json
{ "safety": { "checkpoints": false } }
```

Bunu yapacak hiç iyi bir sebep yoktur.

---

## Çalışma alanı sınırı

Ajan, **proje klasörünün içinde okuyabilir ve yazabilir, başka hiçbir yerde
değil**.

Proje kökü, başladığınız yerden yukarı doğru, bir şey "bu bir proje" diyene
kadar yürünerek bulunur — bir `.git`, bir `pyproject.toml`, bir
`package.json`. Size gösterilir ve klasör başına bir kez sorulur:

```
  Work in  /home/you/projects/api-server ?
```

Onaylanan klasörler hatırlanır. `--cwd` birini doğrudan adlandırır ve
sormaz.

```json
{ "safety": { "workspace_only": true } }
```

Bunu kapatmak, ajanın tüm dosya sisteminize dokunmasına izin verir. Bir
deponun yapılandırması için tam olarak bu sebepten yasaktır.

---

## Çalıştırmayacağı komutlar

Bazı şeyler, hiçbir istem görünmeden önce reddedilir; çünkü hiçbir istem,
uzun bir oturumun sonunda bir insanı onlara ikna edebilmemelidir:

```
rm -rf /     rm -rf ~     mkfs        dd if=      shutdown
reboot       format c:    del /f /s /q c:         :(){
> /dev/sda   chmod -R 777 /
```

Tam liste `safety.deny_commands`'tır. Kendi ekleyin:

```json
{
  "safety": {
    "deny_commands": ["terraform destroy", "kubectl delete namespace"]
  }
}
```

`safety.allow_commands` diğer yöndür — asla istem açmayan komutlar:

```json
{ "safety": { "allow_commands": ["git status", "pytest", "ls"] } }
```

---

## Anahtarlarınız

**Nerede dururlar.** Kendi `~/.comodor/config.json`'unuz, yalnızca sahibine
açık izinlerle yazılır, ya da ortamınız. Başka hiçbir yerde.

**Hiçbir zaman gitmedikleri yer.** Bir deponun yapılandırması değil. Arayüz
değil. Bir günlük değil. Bir `repr` değil — o bir gerçek hataydı, bulundu ve
düzeltilti: bir Config adını taşıyan her traceback anahtarı basardı ve pytest
sürekli traceback basar.

**Ortamınızdaki bir anahtar orada kalır.** `ANTHROPIC_API_KEY`'i kaydetmek
yerine dışa aktarırsanız, `/save` onu yapılandırma dosyanıza kopyalamaz.
Kaydetmek yerine dışa aktarmak bir karardır ve buna saygı duyulur.

**Kırmızileştirme.** Anahtarlarınızdan birine benzeyen her şey, araç
çıktısında, transkriptte ve dışa aktarmalarda maskelenir. Metin üzerinde
çalışır. Pikselleri okuyamaz — bkz.
[Ekranınızı kullanması](computer.md#what-goes-to-the-model).

---

## Bir deponun ayarlayabileceği

Bir projedeki `.comodor/config.json`, hangi dizinden başladıysanız oradan
okunur — ki bir kodlama ajanı için bu, *başka birinin yazdığı bir depodan,
kopyalandıktan hemen sonra* demektir.

Bu yüzden size karşı çevrilemeyecek şeylerle sınırlıdır:

| Bir proje ayarlayabilir | |
|---|---|
| `provider`, `model` | hangi model kullanılacak |
| `agent` | mod, döngü, bütçeler, sıcaklık, çıktı boyutu |
| `ui` | tema, kenarlıklar, banner |
| `learning`, `skills` | açık olup olmadıkları ve sınırları |
| `mcp.servers` | hangi sunucuları kullanacağı — **kapalı gelerek** |

| Bir proje **asla** ayarlayamaz | neden |
|---|---|
| `providers.*.base_url` | anahtarınız ilk istekte onların sunucusuna giderdi |
| `safety.*` | ajanı sormayı bırakabilir veya reddetme listesini boşaltabilirdi |
| `agent.system_prompt_extra` | sizin yetkinizle enjekte edilen talimatlar |
| `browser.executable` | ajanın başlatması için bir ikili dosya adlandırır |
| `computer.*` | yeni kopyalandığı makineden farenizi ister |
| `mcp.enabled` | bir sunucu bildirmek bir öneridir; birini başlatmak bir karardır |

Bu bir **izin listesi**dir, bir yasak listesi değil, yani gelecek yıl eklenen
bir ayar, bir başkası aksine karar verene kadar güvenilmezdir — yanlış
olmanın doğru yönü budur.

Retler yüksek sesle söylenir:

```
config: this project cannot set safety, computer — only your own can
```

Birinin dosyasını sessizce yok saymak, bir yapılandırma dosyasının
"çalışmıyor" diye şöhret kazanmasıdır.

---

## Tavanlar

Üç tane ve her göreve uygulanırlar:

```json
{
  "agent": {
    "max_steps": 24,
    "max_seconds": 900,
    "max_cost_usd": 2.0
  }
}
```

**Parasal olan yalnızca yayımlanmış bir oranı olan model için çalışır.**
Fiyatlandırma tablosunun bilmediği bir modelde, maliyet sayacı sıfırı gösterir
ve sınır asla ateşlenmez. Comodor, bir tavanınız olduğuna inanırken
bırakmak yerine durumu söyler:

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Bir oturumun başında ve `comodor doctor` içinde söylenir. Bkz. [Maliyet](cost.md).

---

## Alt ajanlar

`delegate`, bir git worktree içinde bir alt ajan çalıştırır — deponun izole
bir kopyası. Belleği yoktur, daha fazla delege edemez ve **ekran ona
verilmez**: bir worktree içinde çalışan bir alt ajanın farenizi alması hiçbir
yolla açıklanamaz.

---

## Bir şey bildirmek

Bir güvenlik sorunu bulursanız, lütfen herkese açık bir issue açmayın. Bkz.
[SECURITY.md](../SECURITY.md).

---

## Ayrıca bakın

- [Ekranınızı kullanması](computer.md) — buradaki en katı izin modeli
- [Yapılandırma](configuration.md) — her ayarın yaşadığı yer
- [Arayüz](interface.md#approvals) — istemlerin neye benzediği
