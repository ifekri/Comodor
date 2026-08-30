# Editörünüzde

Comodor, [Agent Client Protocol](https://agentclientprotocol.com) protokolünü konuşur; bu protokolü destekleyen bir editör, Comodor'u doğrudan sürebilir — kendi paneli, kendi izin istemleri, kendi dosya görünümüyle — aynı ajan, aynı öğrenilmiş kurallar ve terminaldekiyle aynı kayıtlarla.

```bash
comodor acp
```

Bunu genellikle siz yazmazsınız. Editör başlatır.

---

## Kurulumu

Comodor, editörünüzün istediği bloğu yazdırır:

```bash
comodor acp --print-config
```

```json
{
  "agent_servers": {
    "Comodor": {
      "command": "/home/you/.local/bin/comodor",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

Bloğun nereye gideceği editöre bağlıdır. Bu belge yazılırken gerçek bir makinede kurulup doğrulanan üç editör:

**JetBrains** — PyCharm, IntelliJ, WebStorm ve diğerleri; AI Assistant eklentisi üzerinden. Bloğu `~/.jetbrains/acp.json` dosyasına koyun ya da AI Chat penceresinin menüsündeki *Add Custom Agent* seçeneğini kullanın; aynı dosya açılır. Ardından Comodor, sohbet panelinin altındaki ajan seçicide görünür. Bunun için JetBrains AI aboneliği gerekmez — ACP ajanları abonelik olmadan da çalışır.

**VS Code** — bir ACP istemci eklentisi kurun; [ACP
Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client) burada doğrulanan eklentidir. Blok, `settings.json` içindeki `acp.agents` altına gider ve Comodor, ACP panelinin ajan listesinde görünür.

**Zed** — `settings.json`; Comodor ajan panelinde görünür.

Ayrıca çalıştığı bildirilen, ancak burada doğrulanmayan editörler: Neovim (CodeCompanion, avante.nvim, agentic.nvim), Emacs (agent-shell.el), Qt Creator, Obsidian ve Visual Studio.

Protokol her yerde aynıdır; yalnızca ayarlar dosyası farklıdır.

Önce Comodor'u kurun, bir terminalde:

```bash
comodor setup
```

Bir editörün hangi sağlayıcıyı kullanacağını soracağı bir yeri yoktur; bu yüzden hiç yapılandırılmamış bir Comodor oturum başlatmayı reddeder ve hangi komutun çalıştırılacağını söyler. Bu, ilk görevde bir başarısızlık olmaktan çok, editörde net bir mesajdır.

---

## Editörün elde ettiği

| | |
|---|---|
| Akış yanıtları | model yazarken |
| Araç çağrıları | her biri adıyla, ne yaptığıyla ve editörün simge seçebilmesi için okuma / düzenleme / yürütme olarak işaretlenmiş şekilde |
| İzin istemleri | editörde sorulur, editörde yanıtlanır |
| Planlar | Comodor bir görev listesi yazdığında editör onu çizer |
| İptal | editörün durdur düğmesi turu keser |
| Oturumlar | listelenir, devam ettirilir ve silinir — `comodor`'un devam ettirdiği aynı kayıtlar |

Çalışma klasörü editörden gelir: hangi projeyi açık tutuyorsanız ajan orada okur ve yazar ve o klasörle sınırlıdır.

---

## Yapmadıkları

**Editörden model sağlayıcısı almaz.** Comodor'un sağlayıcısı, modeli, kuralları, becerileri ve izinleri kendisine aittir; `comodor setup` ile ya da tarayıcı arayüzünde yapılandırılır. Bir editörün de model yapılandırmak istemesi, aynı ayar için ikinci bir doğruluk kaynağı olurdu.

**Oturum açmaz.** Comodor bir model sağlayıcısına kimlik doğrular, editörünüze değil; bu yüzden hiçbir kimlik doğrulama yöntemi tanıtmaz ve bir istemci size oturum açma seçeneği sunmaz.

---

## Bir terslik olduğunda

Protokol, standart çıktıyı mesajlara ayırır; bu yüzden Comodor'un günlükleri standart hataya gider. Editörler bunu genellikle bir yerde gösterir — Zed'de bu, ajan sunucusunun günlüğüdür.

```
comodor acp — stdio üzerinden ACP v2 konuşuyor
```

Sık görülen bir durum ve bozuk bir ajana benziyor gibi görünür, oysa değildir: sağlayıcının anahtarınızı reddetmesi. Editörde `Error during prompt turn` olarak ya da sağlayıcının kendi sözleriyle ulaşır — örneğin `OpenRouter: User not found`, bu da anahtarın iptal edildiği anlamına gelir. `comodor doctor` hangi sağlayıcının yapılandırıldığını söyler; tarayıcı arayüzü yeni bir anahtar kabul eder ya da sizi oturum açar.

Ajan bağlanıyor ama hiçbir şey yapmıyorsa önce bir terminalde `comodor doctor` çalıştırın: erişilemeyen bir sağlayıcı, editörden bakınca bozuk bir ajandan ayırt edilemez.

---

## Ayrıca bkz.

- [Bir tarayıcıdan](web.md) — aynı ajan, bir tarayıcı sekmesinde
- [Arayüz](interface.md) — terminal sürümü
- [Güvenlik](safety.md) — öncesinde ne sorar ve asla ne yapmaz
