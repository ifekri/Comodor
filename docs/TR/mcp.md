# MCP sunucuları

Model Context Protocol, bir aracın kendisini bir ajana betimlemesinin yoludur. Comodor bunu konuşur; dolayısıyla bir MCP sunucusu olan her şey, ajanın kullanabileceği bir şey olur.

---

## Birini eklemek

```bash
comodor mcp catalogue          # servers Comodor can set up for you
comodor mcp add filesystem     # one of them
comodor mcp list               # what you have, and what each offers
```

Katalogda olmayan bir şey:

```bash
comodor mcp custom notes -- npx -y @some/mcp-notes
comodor mcp remote github https://mcp.example.com/sse
```

Ardından güvenmeden önce gerçekten çalıştığını denetleyin:

```bash
comodor mcp test notes
```

```
  notes            started in 0.8s
    create_note    Create a note with a title and body
    search_notes   Find notes by text
    delete_note    Delete a note by id
```

---

## Açıp kapatmak

```bash
comodor mcp enable notes
comodor mcp disable notes
comodor mcp remove notes       # forget it entirely
```

```
/mcp                           # the same, in the interface
```

Devre dışı bırakılmış bir sunucu başlatılmaz ve araçları sunulmaz.

---

## Onlar da herhangi bir araç gibi araçtır

Bir sunucunun sağladığı her şey, yerleşik araçların yanında görünür ve **birebir aynı izin kapısından** geçer. Bir dosyayı yazan bir MCP aracı, `write_file`'ın sorduğu gibi sorar. Burada arka kapı yoktur.

---

## Bir proje beyan edebilir, etkinleştiremez

Bir deponun `.comodor/config.json` dosyası, kullandığı sunucuları listeleyebilir:

```json
{
  "mcp": {
    "servers": {
      "project-db": { "command": "npx", "args": ["-y", "@acme/db-mcp"] }
    }
  }
}
```

Bu yararlıdır: yeni bir kişi depoyu klonlar ve projenin ne beklediğini görebilir.

**Kapalı olarak gelirler.** Bir sunucuyu adlandırmak bir öneridir; birini başlatmak makinenizde bir komut çalıştırır ve o sizin kararınızdır. Baktıktan sonra etkinleştirin:

```bash
comodor mcp enable project-db
```

Bir proje, ana anahtar olan `mcp.enabled`'i hiç ayarlayamaz.
[Güvenlik](safety.md#what-a-repository-may-set).

---

## Taşımalar

| | |
|---|---|
| **stdio** | Comodor'un başlattığı ve borular üzerinden konuştuğu bir komut. Olağan olan |
| **Streamable HTTP** | bir yerde zaten çalışan bir sunucu, HTTP üzerinden |

İkisi de pakette uygulanmıştır — hiçbiri için bağımlılık yoktur.

---

## Bir terslik olduğunda

Başlamayan ya da çok uzun süren bir sunucu bildirilir ve atlanır. Oturumu beraberinde aşağı çekmez.

```bash
comodor mcp test <name>        # start it and see
comodor doctor                 # includes every configured server
```

---

## Ayrıca bkz.

- [Ajanın yapabildikleri](tools.md) — bunların katıldığı yerleşik araçlar
- [Güvenlik](safety.md) — geçtikleri kapı
