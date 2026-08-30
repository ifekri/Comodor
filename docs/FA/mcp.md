# سرورهای MCP

پروتکل Model Context راهی است برای اینکه یک ابزار خودش را به یک ایجنت معرفی کند.
Comodor با آن صحبت می‌کند، پس هر چیزی که سرور MCP داشته باشد، به چیزی تبدیل
می‌شود که ایجنت می‌تواند استفاده کند.

---

## اضافه کردن یکی

```bash
comodor mcp catalogue          # servers Comodor can set up for you
comodor mcp add filesystem     # one of them
comodor mcp list               # what you have, and what each offers
```

چیزی که در کاتالوگ نیست:

```bash
comodor mcp custom notes -- npx -y @some/mcp-notes
comodor mcp remote github https://mcp.example.com/sse
```

سپس پیش از اعتماد به آن بررسی کنید که واقعاً کار می‌کند:

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

## روشن و خاموش کردن‌شان

```bash
comodor mcp enable notes
comodor mcp disable notes
comodor mcp remove notes       # forget it entirely
```

```
/mcp                           # the same, in the interface
```

سرورِ غیرفعال اجرا نمی‌شود و ابزارهایش پیشنهاد نمی‌شوند.

---

## ابزارهایی هستند مثل هر ابزار دیگر

هر چه سرور فراهم کند در کنار ابزارهای داخلی ظاهر می‌شود و از **همان دروازه‌ی
مجوزِ عیناً یکسان** می‌گذرد. یک ابزار MCP که فایلی را می‌نویسد، همان‌طور سؤال
می‌پرسد که `write_file` می‌پرسد. اینجا درِ پشتی وجود ندارد.

---

## یک پروژه می‌تواند اعلام کند، نه فعال کند

`.comodor/config.json` یک مخزن می‌تواند سرورهایی را که استفاده می‌کند فهرست کند:

```json
{
  "mcp": {
    "servers": {
      "project-db": { "command": "npx", "args": ["-y", "@acme/db-mcp"] }
    }
  }
}
```

این مفید است: فرد تازه‌ای مخزن را کلون می‌کند و می‌بیند پروژه چه انتظاری دارد.

**آن‌ها خاموش می‌رسند.** نام بردن از یک سرور یک پیشنهاد است؛ اجرای یکی یعنی اجرای
یک فرمان روی ماشین شما، و آن تصمیم شماست. وقتی نگاهش کردید فعالش کنید:

```bash
comodor mcp enable project-db
```

یک پروژه اصلاً نمی‌تواند `mcp.enabled`، کلید اصلی، را تنظیم کند.
[ایمنی](safety.md#what-a-repository-may-set).

---

## انتقال‌ها

| | |
|---|---|
| **stdio** | فرمانی که Comodor اجرا می‌کند و با آن از طریق پایپ‌ها صحبت می‌کند. حالت همیشگی |
| **Streamable HTTP** | سروری که از پیش جای دیگری در حال اجراست، روی HTTP |

هر دو در خود بسته پیاده‌سازی شده‌اند — برای هیچ‌کدام وابستگی‌ای نیست.

---

## وقتی یکی خراب می‌شود

سروری که اجرا نمی‌شود، یا بیش از حد طول می‌کشد، گزارش و نادیده گرفته می‌شود.
جلسه را با خودش پایین نمی‌کشد.

```bash
comodor mcp test <name>        # start it and see
comodor doctor                 # includes every configured server
```

---

## ببینید همچنین

- [آنچه ایجنت می‌تواند بکند](tools.md) — ابزارهای داخلی که این‌ها به آن‌ها می‌پیوندند
- [ایمنی](safety.md) — دروازه‌ای که از آن می‌گذرند
