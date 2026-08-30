# Docker içinde

Ajan, onun tarayıcısı ve ihtiyaç duyduğu her şey, tek bir kapsayıcıda.

```bash
git clone -b docker https://github.com/ifekri/Comodor.git comodor-docker
cd comodor-docker
export ANTHROPIC_API_KEY=…        # or OPENAI_API_KEY, OPENROUTER_API_KEY, …
docker compose up
```

İmajı ilk seferde derler, sonra adresi yazdırır:

```
  Comodor is at  http://127.0.0.1:8765/?token=…
  Working in     /work
```

Bağlantıyı açın. Her çalıştırmada yeni bir token olur; bu yüzden *bu* çalıştırmaya ait olanı kullanın.

Ya da hiçbir şey klonlamadan:

```bash
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e ANTHROPIC_API_KEY \
  -v "$PWD:/work" \
  ghcr.io/ifekri/comodor:latest
```

---

## Burada bir anahtar isteğe bağlı değildir

Tarayıcı arayüzünün anahtar girmek için bir yolu yoktur; bu yüzden anahtar olmadan kapsayıcı neyin eksik olduğunu söyler ve durur — ilk görevde başarısız olan bir URL sunmak yerine.

Compose, kabuğunuzda ayarlı olan hangisi varsa onu iletir; onu imaja ya da compose dosyasına yazmadan:

```
ANTHROPIC_API_KEY   OPENAI_API_KEY   OPENROUTER_API_KEY   DEEPSEEK_API_KEY
GEMINI_API_KEY      GROQ_API_KEY     XAI_API_KEY          MISTRAL_API_KEY
XIAOMI_API_KEY
```

Kabuk geçmişinizden ziyade bir dosyayı mı tercih edersiniz? Compose dosyasının yanındaki bir `.env` dosyasına koyun — compose onu okur ve git'e yok sayılır.

---

## Nerede çalışır

Ajanın dokunabildiği her şey, compose dosyasının yanındaki `work/` klasörüdür. Onu başka bir yere yönlendirin:

```yaml
volumes:
  - "/path/to/your/project:/work"
```

Öğrendikleri — beyin, düzeltmeleriniz, oturum kayıtları — adlandırılmış bir birimde yaşar; bu yüzden `docker compose down`'dan sağ çıkar ve `docker compose down -v` tarafından unutulur.

---

## Kim erişebilir

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

**Soldaki `127.0.0.1`, bütün güvenlik modelidir.** Onu bırakın, bağlantı noktası makinenin her arayüzünde olur — ve bu bağlantı noktası bir kabuktur.

Kapsayıcının içinde Comodor `0.0.0.0`'a bağlanır; bu bir ihmal değildir: bir kapsayıcının kendi ağ ad alanı vardır, dolayısıyla birinin içinde loopback'e bağlanmak bağlantı noktasını onu çalıştıran makineden gizler. Ona gerçekte kimin erişebileceğine, bağlantı noktasının nasıl yayınlandığı karar verir ve başlık (banner) tam bunu söyler.

---

## Kapsayıcının yapabildikleri

```yaml
cap_drop: [ALL]
security_opt:
  - no-new-privileges:true
```

Kabuk komutları çalıştırır; dolayısıyla kapsayıcı, bunlarla sizin makinenizin arasındaki şeydir. Gerekmediği hiçbir şey verilmez ve root olmayan bir kullanıcı olarak çalışır.

---

## Bir sürümü sabitlemek

```yaml
args:
  COMODOR_VERSION: "0.9.0"
```

Varsayılan olarak sabitlenmiştir; böylece yeniden derleme yeniden üretilebilirdir. Bunun yerine en yeni sürüm için:

```bash
docker compose build --build-arg COMODOR_VERSION=
```

---

## İçinde başka bir şey çalıştırmak

```bash
docker compose run --rm comodor comodor doctor
docker compose run --rm comodor sh
```

Argümansız olmak ya da tire ile başlayan argümanlar, "bu seçeneklerle web arayüzünü çalıştır" demektir. Gerisi, onun yerine çalıştırılacak bir komuttur.

---

## Kapsayıcıda olmayan

**Ekranınız.** [Masaüstü denetimi](computer.md), Comodor'un üzerinde çalıştığı makineyi sürer ve bir kapsayıcıda o, ekransız bir makinedir. Araç orada sunulmaz.

[Tarayıcı](browser.md) çalışır — Chromium ve yazı tipleri imajın içindedir.

---

## Başlamıyorsa

**`localhost:8765`'te hiçbir şey yok** — bağlantı noktasının yayınlandığını denetleyin: `docker compose ps`.

**Hemen çıkıyor** — günlüğü okuyun. Neredeyse her zaman yapılandırılmış bir sağlayıcı yoktur; mesaj ne ayarlanacağını söyler.

**`exec /usr/local/bin/comodor-start: no such file or directory`** — CRLF'li bir checkout. Dalda bir `.gitattributes` ile düzeltildi; görüyorsanız pull edin.

---

## Ayrıca bkz.

- [Bir tarayıcıdan](web.md) — kullanacağınız arayüz
- [Güvenlik](safety.md) — ajanın kapsayıcı içinde yapabilecekleri
