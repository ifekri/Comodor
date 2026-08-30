# الانتقال من وكيل آخر

إن كنت تستخدم **OpenClaw** أو **Hermes** أصلًا، فسيعرض عليك Comodor إحضار
إعدادك عند تشغيله أول مرة.

لقد وجدت مفاتيح API الخاصة بك ولصقتها في مكان ما. وإعادتها ثانيةً انطباع أول
ضعيف.

---

## في أول تشغيل

```
 1/7  You already use OpenClaw
  OpenClaw  1 API key, the model (claude-sonnet-5), 1 skill
  /home/you/.openclaw

  Nothing is moved and nothing already set here is replaced.
  Keys are copied into your config; the other tool keeps working.

  1.  bring it over   keys, model and skills
  2.  keys only       leave the skills and the model
  3.  start fresh     import nothing
```

لا يظهر السؤال إلا حين يكون هناك شيء للاستيراد.

---

## بعد ذلك

ثبّت أحد الأداتين لاحقًا، أو أجبت «start fresh» وغيّرت رأيك:

```bash
comodor import              # bring it across
comodor import --dry-run    # say what it would take, change nothing
comodor import --keys-only  # leave the skills and the model
```

وتشغيله مرتين آمن — في المرة الثانية يقول إنه لا شيء جديد.

---

## ما يعبر

| | |
|---|---|
| **مفاتيح API** | كامل الملل. من `.env` الخاص بها، ومن JSON المضمَّن في OpenClaw |
| **النموذج** | إن كان بإمكان Comodor استضافته |
| **المهارات** | كلتا الأداتين تكتب الصيغة المفتوحة نفسها، فهذه ملفات تُنسخ |

ثلاث قواعد على الدوام، لأن هذا يقرأ ملفات برنامج آخر:

- **لا شيء يُكتب فوقه.** المفتاح المضبوط هنا مسبقًا يغلب؛ والاستيراد يسد الفجوات.
- **لا شيء يُنقل.** كل قراءة قراءة. ويواصل الأداة الآخر العمل كما كان تمامًا.
- **الملف المشوّه يُتخطى، ولا يكون قاتلًا.** نصف القيمة أنه يعمل على جهاز
  وكيله الآخر في حالة غريبة.

---

## ما لا يعبر، ولماذا

**ذاكرتهم.** قيل بصوت عالٍ بدل أن يُتخطى في صمت:

```
not imported: MEMORY.md — its memory is prose; this agent's is lessons with
confidence and evidence, and inventing those would poison recall
```

ذاكرة Comodor دروس بدرجة ثقة ودليل وتآكل، تعلمت من التصحيحات. أما `MEMORY.md`
فهي نثر. واستيراد واحدة كالأخرى سيخترع درجات ثقة لم يقسها أحد ويملأ الاستدعاء
بمدخلات لم تُكتسب قط. فتحصل على وكيل أسوأ يبدو أفضل اطلاعًا.

**الشخصيات، والمراسلة، وتحويل النص إلى كلام.** ليس لـ Comodor ما يقابلها،
وإعداد مستورد إلى العدم أسوأ من لا إعداد.

**مفتاح مخزَّن في مكان آخر.** تتيح OpenClaw أن يكون المفتاح إشارة إلى ملف أو
أمر. وتلك تعني شيئًا على الجهاز الذي كُتبت له ولا شيء هنا، فتُبلَّغ بدل أن
يُخمَّن عنها.

---

## المهارات، وشيء واحد يستحق المعرفة

تستورد المهارات ضمن نطاق أسماء — فتصبح `review` باسم `openclaw-review` — فلا
يمكن لاستيراد أن يستبدل بصمت واحدة من مهاراتك.

وتُنسخ مجلدات المهارات ملفًا ملفًا، و**المجلد الذي يحتوي رابطًا يخرج من نفسه
يُرفض**. فالمهارة ملف تُقرأ محتوياته إلى مطالبة، ولولا ذلك لكان رابطًا رمزيًا
إلى `~/.ssh/id_rsa` جالسًا في دليل مهارات برنامج آخر قد نُسِل وأُرسل إلى نموذج.
يُرفض، ويُسمّى:

```
not imported: the skill sneaky — it contains a link out of that folder
```

---

## أين ينظر

| | |
|---|---|
| OpenClaw | `~/.openclaw`، `~/.clawdbot`، `~/.moltbot` |
| Hermes | `~/.hermes` |

تلك أدلة OpenClaw الأقدم ما زالت على أجهزة حقيقية — فقد سُمّي مرتين — فتُفحص
الثلاثة كلها.

ولإيقاف النظر كليًا:

```bash
export COMODOR_NO_IMPORT=1
```

---

## انظر أيضًا

- [البداية](getting-started.md) — بقية أول تشغيل
- [الإعداد](configuration.md) — أين ينتهي الإعداد المستورد
- [المهارات](skills.md) — ماذا تفعل بالواصل منها
