# خوادم MCP

بروتوكول Model Context Protocol وسيلة لأداة أن تصف نفسها لوكيل. ويتحدّث Comodor بها، فكل ما له خادم MCP يصبح شيئًا يستطيع الوكيل استخدامه.

---

## إضافة خادم

```bash
comodor mcp catalogue          # servers Comodor can set up for you
comodor mcp add filesystem     # one of them
comodor mcp list               # what you have, and what each offers
```

خادم غير موجود في الكتالوج:

```bash
comodor mcp custom notes -- npx -y @some/mcp-notes
comodor mcp remote github https://mcp.example.com/sse
```

ثم تأكد من أنه يعمل فعلًا قبل الوثوق به:

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

## تشغيلها وإيقافها

```bash
comodor mcp enable notes
comodor mcp disable notes
comodor mcp remove notes       # forget it entirely
```

```
/mcp                           # the same, in the interface
```

الخادم المعطَّل لا يُبدَأ ولا تُعرض أدواته.

---

## هي أدوات كغيرها

كل ما يوفره الخادم يظهر بجوار الأدوات المدمجة ويمر عبر **بوابة الأذونات نفسها بالضبط**. فأداة MCP التي تكتب ملفًا تسأل كما تسأل `write_file`. ولا يوجد باب خلفي هنا.

---

## المشروع يصرّح، ولا يُمكِّن

يمكن لملف `.comodor/config.json` الخاص بمستودع ما أن يسرد الخوادم التي يستخدمها:

```json
{
  "mcp": {
    "servers": {
      "project-db": { "command": "npx", "args": ["-y", "@acme/db-mcp"] }
    }
  }
}
```

هذا مفيد: شخص جديد يستنسخ المستودع ويستطيع رؤية ما يتوقعه المشروع.

**تصل مطفأة.** فتسمية خادم اقتراح؛ أما تشغيله فينفّذ أمرًا على جهازك، وذلك قرارك أنت. مكّنه بعد أن تتفقّده:

```bash
comodor mcp enable project-db
```

لا يستطيع المشروع ضبط `mcp.enabled`، المفتاح الرئيسي، إطلاقًا.
[الأمان](safety.md#what-a-repository-may-set).

---

## طبقات النقل

| | |
|---|---|
| **stdio** | أمر يشغّله Comodor ويتخاطب معه عبر الأنابيب. وهو المعتاد |
| **Streamable HTTP** | خادم يعمل مسبقًا في مكان ما، عبر HTTP |

كلاهما منفَّذ داخل الحزمة — ولا اعتمادية لأي منهما.

---

## عند سوء تصرّف أحدها

الخادم الذي يرفض البدء أو يستغرق وقتًا طويلًا يُبلَّغ عنه ويُتجاوَز. فهو لا يُسقط الجلسة معه.

```bash
comodor mcp test <name>        # start it and see
comodor doctor                 # includes every configured server
```

---

## انظر أيضًا

- [ما يستطيع الوكيل فعله](tools.md) — الأدوات المدمجة التي تنضم إليها هذه الخوادم
- [الأمان](safety.md) — البوابة التي تمر عبرها
