# المهارات

المهارة إجراء مكتوب يتّبعه الوكيل عندما يستدعي العمل ذلك.

وليست مطالبة تلصقها في كل مرة — بل ملف يحمّله بنفسه حين يتطابق الوضع.

---

## الحصول على بعضها

يعرض `comodor setup` المكتبة مرة واحدة، في النهاية. تحرّك بمفاتيح الأسهم،
واضغط **space** للإشارة إلى ما تريد بقدر ما تشاء، ويثبّت **enter** كلها.
ولا شيء مُشار إليه في البداية، وenter دون إشارة إلى شيء لا يأخذ شيئًا — فلن
تُعطَ أبدًا شيئًا لم تطلبه.

```
┌─ Skills ──────────────────────────────────────────────────┐
│    ☑ review        Review a change before it is committed │
│ ›  ☐ commit-style  Match the commit messages already here │
│    ☑ python-tests  Write tests the way this project does  │
└───────────────────────────────────── 2 selected ──────────┘
  ↑↓ move   space select   enter install 2   tab more   esc cancel
```

**سطر واحد لكل مهارة**، فيتسع كامل القائمة في شاشة واحدة مهما طالت المكتبة،
وتتبع النافذة السهم بدل أن تتقاعس عنه. بعض هذه الأوصاف يمتد إلى فقرة — يفتح
**tab** الوصف الكامل لما يشير إليه السهم، في الإطار نفسه، وtab ثانية يغلقه.

وتصفّي الكتابة القائمة، وهو أسرع من التمرير حين يزيد العدد عن قبضة. وتبقى
الإشارات أثناء التصفية، فيمكنك تضييق القائمة، والإشارة إلى شيء، ومسح عامل
التصفية، والإشارة إلى شيء آخر.

بدون طرفية يتولى الأمر — أنبوب، أو سكربت، أو `curl | sh` — فيُطرح السؤال
نفسه قائمة مرقّمة، صفحة في كل مرة:

| | |
|---|---|
| `1,3` أو `1 3` | خذ هذه |
| `m` / `b` | الصفحة التالية، الصفحة السابقة |
| `/word` | اعرض المتطابق فقط |
| `?7` | اقرأ وصف الرقم 7 كاملًا |
| enter | انتهيت |

الأرقام مطلقة: فالرقم 92 هو المهارة الثانية والتسعون مهما كانت الصفحة أو
البحث الذي تنظر إليه، فيبقى الرقم الذي دوّنته هو الرقم الذي تكتبه.

---

## استخدام واحدة

```bash
comodor skills browse            # what is available
comodor skills add review        # install it
comodor skills list              # what you have
```

```
/skills                          # the same, in the interface
```

ومن ثَم، عندما تطلب شيئًا تغطيه مهارة، تُحمَّل ويتّبعها الوكيل. وتُخبَر حين
يحدث ذلك:

```
  ▸ skill: review — Review a change for correctness before it is committed
```

فالمهارة التي لا تراها تُطبَّق هي مهارة لا تستطيع تصحيحها.

---

## كتابة واحدة

مجلد فيه `SKILL.md`:

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

**الوصف** هو الأهم. فهو ما يطابقه Comodor مع طلبك ليقرر ما إذا كان سيحمّل
المهارة من أصل، فاكتبه كالوضع، لا كعنوان.

أعد التشغيل، أو `/skills`، وستكون هناك.

### إرفاق ملفات

يمكن لمهارة أن تحمل ملفات بجوار `SKILL.md`:

```
~/.comodor/skills/our-tests/
  SKILL.md
  references/
    fixtures.md
    conventions.md
```

يشير `SKILL.md` إليها؛ ولا يقرأ الوكيل واحدة منها إلا حين يحتاجها. وهذا يُبقي
المهارة نفسها قصيرة — وهذا مهم، لأن المهارة تُحمَّل إلى الدور، والطويلة منها
تكلّف رموزًا سواء احتاج التفصيل أم لا.

---

## لكل مشروع

```
./.comodor/skills/<name>/SKILL.md
```

مثبَّتة في المستودع، فيحصل كل من يعمل عليه على الإجراءات نفسها. وتُحمَّل مهارات
المشروع إلى جانب مهاراتك.

---

## الميزانية

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000
  }
}
```

`top_k` هو كم منها يجوز أن يُحمَّل لدور واحد؛ و`max_tokens` هو السقف لما يجوز
أن تكلفه معًا. وتُتخطى المهارة الأكبر من أن تتسع، ويُخبَر أيّها — فالصمت هنا
كان عيبًا حقيقيًا في يوم من الأيام، حين أزاحت مهارة ضخمة بحجمها مهارات أصغر
هادئة.

---

## إدارتها

```bash
comodor skills add review taste output    # several at once
comodor skills update                     # refresh installed ones
comodor skills remove review
comodor skills list                       # with versions
```

---

## انظر أيضًا

- [كيف يتعلم](learning.md) — دروس يستنتجها، بدل إجراءات تكتبها أنت
- [ما يستطيع الوكيل فعله](tools.md) — الأدوات التي تخبره بها المهارة كيف
  يستخدمها
