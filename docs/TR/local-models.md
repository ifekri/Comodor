# Kendi makinenizdeki modeller

Comodor bir modeli indirebilir, diskinizde tutabilir ve orada çalıştırabilir — anahtar yok, hesap yok ve ağ fişek çekilmiş halde de çalışmaya devam eder.

```bash
comodor local list                       # what you can run, and what is here
comodor local get qwen2.5-coder-7b-q4    # download it, with a progress bar
comodor local use qwen2.5-coder-7b-q4    # make it the one the agent talks to
```

Aynı liste, tarayıcıda **Admin → Local LLM** altındadır; aynı indirme, aynı ilerleme ve aynı düğmelerle.

## Nasıl kurgulandı ve neden yavaş değil

Güvenilir her şey aynı şeyi yapar — Ollama, LM Studio, llama.cpp, vLLM — ve Comodor da yapar: **çıkarım, OpenAI uyumlu bir API konuşan ayrı bir süreçte çalışır ve model, istekler arasında o süreçte yüklü kalır.**

Üç neden; hepsi ajanın duyarlı kalmasıyla ilgili:

**GIL.** Üretim, uzun bir CPU-sınırlı döngüdür. Onu Comodor'un kendi sürecinde çalıştırın, diğer her iş parçacığı — arayüzü yeniden boyayan, bir aracı bitiren, olay veri yolu — onun arkasında bekler. Başka bir süreçte, başka bir çekirdeğin sorunudur.

**Yükleme pahalıdır ve bir kez olmalıdır.** Dört gigabaytı diskten okumak ve yerleştirmek saniyeler ile onlarca saniye sürer. İstek başına yükleme bunu her turda öder; yerleşik bir sunucu bir kez öder ve sonrasında milisaniyeler içinde yanıtlar.

**Bir çökme orada kalır.** Bir 14B model üzerinde bellek yetersizliği kaynaklı sonlandırma, model sunucusunu bitirir, oturumunuzu değil. Ajan bir bağlantı hatası bildirir ve kayıt sağ kalır.

Mutlu sonucu, neredeyse hiç yeni kod olmamasıdır: `http://127.0.0.1:PORT/v1` üzerindeki bir yerel sunucu, *zaten* bir OpenAI uyumlu uç noktadır; dolayısıyla mevcut sağlayıcı onu değişmeden sürer. Bağlantı noktası, sunucu başlarken seçilir; bu yüzden `local` sağlayıcı yapılandırmada URL taşımaz — oraya yazılan bir URL, bir sonraki sefer yanlış olurdu.

Sunucu, **ilk mesajınızda** başlar, başlangıçta değil. `comodor`'u her çalıştırdığınızda — modele hiçbir şey sormadığınız zamanlar dahil — dört gigabayt yüklemek, sebepsiz boş bir ekran olurdu.

## Neye ihtiyacınız var

Model dosyası — Comodor onu indirir — ve onu çalıştıracak bir şey. Comodor hangisini bulursa onu kullanır:

```bash
brew install llama.cpp          # macOS
winget install llama.cpp        # Windows
                                # Linux: github.com/ggml-org/llama.cpp
```

Ollama ya da LM Studio, hangisi hâlihazırda çalışıyorsa o da olur. Hiçbir şey yokken `comodor local list` bunu açıkça söyler; böylece bir saatlik indirmenin sonrasında değil, öncesinde öğrenirsiniz.

## İndirme

Bir model, ev hattınızdan bir ile dokuz gigabayttır ve indirmenin her şeyi bundan biçimlenir.

**Devam eder.** Baytlar bir `.part` dosyasına gider. Durdurun, dizüstünü kapatın, bağlantıyı kaybedin — sonraki `comodor local get`, sunucudan o dosyanın bittiği yerden devam etmesini ister. Tarayıcı, `Download` yerine `Resume (37%)` gösterir.

**Doğrulanır.** Her katalog girdisi kesin bir bayt sayısı ve bir SHA-256 taşır ve dosya, eşleşene kadar kabul edilmez. Bu, önlem olsun diye yapılan bir şey değildir: kesilmiş bir GGUF *bariz bozuk değildir* — yüklenir, sonra model anlamsızlık üretir ve akşamı, övgüyle anılan bir modelin neden işe yaramadığını merak ederek geçirirsiniz. Başarısız olan dosya, sonra bulunup yarı-güvenilecek şekilde bırakılmak yerine silinir.

**İzlenebilir.** Terminalde, sorulan soruyu yanıtlayan dört sayıyla bir çubuk:

```
qwen2.5-coder-7b-q4 ━━━━━━━━━━━━━━╸────────  38.2%  1.7/4.4 GB  8.9 MB/s  0:05:12
```

Tarayıcıda, modelin kartındaki çubuğun altında aynı sayılar; olay akışından güncellenir, yoklama ile değil.

## Dosyalar nereye gider

Tek bir dizin, makinedeki her projeyle paylaşılan — yoksa üç checkout'taki aynı model, aynı baytların üç kopyası olurdu.

```bash
comodor local where
```

`comodor local remove <id>` birini siler ve ne kadar yer açıldığını söyler.

## Listeye bir model eklemek

Liste bir JSON dosyasıdır; dolayısıyla yeni bir model bir sürüm değil, bir düzenlemedir. Hem terminal hem tarayıcı onu alır.

```json
{
  "id": "my-model-q4",
  "name": "My Model 7B",
  "description": "One sentence on what it is good at, and what it is not.",
  "url": "https://huggingface.co/OWNER/REPO/resolve/main/file.gguf",
  "size": 4683074336,
  "sha256": "1664fccab734674a...",
  "context": 32768,
  "parameters": "7B",
  "quantization": "Q4_K_M",
  "needs_ram_gb": 8,
  "license": "apache-2.0",
  "good_at": ["code"],
  "tools": true,
  "vision": false
}
```

`id`, `name`, `url` ve `size` zorunludur — gerisi isteğe bağlıdır ve bıraktığınız her şey bilinmiyor olarak bildirilir, tahmin edilmez. Buradaki yanlış bir sayı, birilerine bir indirme ve bir çökme pahalıya mal olur.

Boyutu ve sağlama toplamını yazmak yerine API'den alın:

```bash
curl -s 'https://huggingface.co/api/models/OWNER/REPO?blobs=true' | python -c \
  "import json,sys;[print(f['rfilename'], f['size'], f.get('lfs',{}).get('sha256')) \
   for f in json.load(sys.stdin)['siblings'] if f['rfilename'].endswith('.gguf')]"
```

Yükleyicinin dayattığı iki kural:

- **Yalnızca `https`.** Bir model dosyası, önemli olan her bakımdan çalıştırılabilir bir artefakttır ve birinin uçuş sırasında yeniden yazabildiği bir kanaldan alınan model, bir katalog istedi diye izin verilecek bir şey değildir.
- **Tek bir kötü girdi, listeyi ödünç almaz.** Bozuk biçimli bir model atlanır ve geri kalanı yüklenir; çünkü alternatif, boş bir seçicidir.

Comodor, listenin bir kopyasını taşır ve günde bir kez daha tazesini arar; bulduğunu önbelleğe alır. Ağ yokken önbelleği kullanır; o da olmazsa taşınan kopyayı kullanır — ki bir tane taşımanın bütün anlamı budur.

## Yapmayacakları

`needs_ram_gb`, indirme başlamadan önce makinenizle karşılaştırılır ve sığmayacak bir model bunu söyler; bir saat sonra öğrenmenize izin vermez. Katılmıyorsanız `comodor local get --yes` onu geçersiz kılar.

Disk de aynı şekilde denetlenir, onda bir boş bırakılarak: bir diskin son baytını dolduran bir indirme yalnızca başarısız olmaz, makinenin gerisini de beraberinde götürür.
