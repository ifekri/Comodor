# Skill'ler

Bir skill, iş gerektirdiğinde ajanın izlediği yazılı bir prosedürdür.

Her seferinde yapıştırdığınız bir istem değil — durum uyuştuğunda kendi
kendine yüklediği bir dosya.

---

## Nasıl edinilir

`comodor setup`, kütüphaneyi bir kez, en sonda sunar. Ok tuşlarıyla
hareket edin, istediğiniz kadarını işaretlemek için **space**'e basın ve
**enter** hepsini kurar. Başlangıçta hiçbir şey işaretli değildir ve hiçbir
şey işaretli olmadan enter hiçbirini almaz — istemediğiniz bir şey size
asla verilmez.

```
┌─ Skills ──────────────────────────────────────────────────┐
│    ☑ review        Review a change before it is committed │
│ ›  ☐ commit-style  Match the commit messages already here │
│    ☑ python-tests  Write tests the way this project does  │
└───────────────────────────────────── 2 selected ──────────┘
  ↑↓ move   space select   enter install 2   tab more   esc cancel
```

**Skill başına bir satır**, böylece liste ne kadar uzarsa uzasın tamamı tek
bir ekrana sığar ve pencere, okun peşinden gider, gerisinde kalmaz. Bu
açıklamaların bazıları bir paragraf uzanır — okun üzerinde olduğu şeyin
tamamını aynı çerçevede **tab** açar ve tekrar tab kapatır.

Yazmak listeyi filtreler; bir avuçtan fazla olduğunda kaydırmaktan daha
hızlıdır. Filtrelerken işaretler korunur, böylece listeyi daraltabilir,
bir şeyi işaretleyebilir, filtreyi temizleyip başka bir şeyi
işaretleyebilirsiniz.

Bir terminal olmadan devralabilir — bir boru, bir betik, `curl | sh` — aynı
soru numaralı bir liste olarak sorulur, sayfa sayfa:

| | |
|---|---|
| `1,3` or `1 3` | bunları al |
| `m` / `b` | sonraki sayfa, önceki sayfa |
| `/word` | yalnızca uyanları göster |
| `?7` | 7 numaranın tüm açıklamasını oku |
| enter | bitti |

Numaralar mutlaktır: 92 numara, hangi sayfaya ya da aramaya baktığınıza
bakılmaksızın doksan ikinci skill'dir, yani not aldığınız bir numara,
yazdığınız numara olarak kalır.

---

## Birini kullanmak

```bash
comodor skills browse            # what is available
comodor skills add review        # install it
comodor skills list              # what you have
```

```
/skills                          # the same, in the interface
```

O andan itibaren, bir skill'in kapsadığı bir şey istediğinizde yüklenir ve
ajan onu izler. Bu olduğunda size söylenir:

```
  ▸ skill: review — Review a change for correctness before it is committed
```

Uygulandığını göremediğiniz bir skill, düzeltemeyeceğiniz bir skill'dir.

---

## Birini yazmak

İçinde bir `SKILL.md` olan bir klasör:

```
~/.comodor/skills/our-tests/SKILL.md
```

```markdown
---
name: our-tests
description: How tests are written and run in this project.
---

# Tests in this project

- pytest, never unittest.
- One file per module, mirroring `src/`.
- Name the test after the behaviour, not the function:
  `test_an_empty_input_raises`, not `test_parse_2`.
- Never mock what you can construct.

## Running them

    uv run pytest -x -q

Not `python -m pytest` — the project needs the venv's own interpreter.
```

**description** en çok öneme sahip olan kısımdır. Comodor'un isteğinize
karşı, skill'i hiç yükleyip yüklemeyeceğine karar vermek için eşleştirdiği
şeydir; bu yüzden onu bir başlık gibi değil, durum olarak yazın.

Yeniden başlatın ya da `/skills`, ve oradadır.

### Dosya paketlemek

Bir skill, `SKILL.md`'nin yanında dosyalar taşıyabilir:

```
~/.comodor/skills/our-tests/
  SKILL.md
  references/
    fixtures.md
    conventions.md
```

`SKILL.md` onlara işaret eder; ajan yalnızca ihtiyaç duyduğunda birini
okur. Bu, skill'in kendisini kısa tutar — ki bu önemlidir, çünkü skill tura
yüklenir ve uzun olanı, ayrıntıya ihtiyaç duyulup duyulmadığına bakılmaksızın
token maliyetidir.

---

## Proje başına

```
./.comodor/skills/<name>/SKILL.md
```

Depoyla birlikte commit edilir, böylece üzerinde çalışan herkes aynı
prosedürleri alır. Bir projenin skill'leri sizinle birlikte yüklenir.

---

## Bütçe

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000
  }
}
```

`top_k`, bir tur için kaç tanesinin yüklenebileceğidir; `max_tokens`,
birlikte neye mal olabileceklerine tavan koyar. Sığamayacak kadar büyük bir
skill atlanır ve hangisi olduğu size söylenir — buradaki sessizlik gerçekten
bir hataydı bir keresinde: aşırı büyük bir skill, küçüklerini sessizce
dışarı itiyordu.

---

## Onları yönetmek

```bash
comodor skills add review taste output    # several at once
comodor skills update                     # refresh installed ones
comodor skills remove review
comodor skills list                       # with versions
```

---

## Ayrıca bakın

- [Nasıl öğrenir](learning.md) — yazdığınız prosedürlerden ziyade çıkarımda bulunduğu dersler
- [Ajan neler yapabilir](tools.md) — bir skill'in ona nasıl kullanacağını söylediği araçlar
