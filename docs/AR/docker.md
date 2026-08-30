# داخل Docker

الوكيل ومتصفحه وكل ما يحتاجه، في حاوية واحدة.

```bash
git clone https://github.com/ifekri/Comodor.git
cd Comodor
export ANTHROPIC_API_KEY=…        # or OPENAI_API_KEY, OPENROUTER_API_KEY, …
docker compose up
```

يبني الصورة في المرة الأولى، ثم يطبع العنوان:

```
  Comodor is at  http://127.0.0.1:8765/?token=…
  Working in     /work
```

افتح الرابط. لكل تشغيل رمز جديد، فاستخدم رمز التشغيل *الحالي*.

أو دون استنساخ أي شيء:

```bash
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e ANTHROPIC_API_KEY \
  -v "$PWD:/work" \
  ghcr.io/ifekri/comodor:latest
```

---

## مفتاح، وإلا ستطلبه الصفحة

اضبطه ويكون جاهزًا لحظة فتحك للرابط. وبدونه يعمل أيضًا وتطلبه الصفحة —
فواجهة المتصفح صار بإمكانها استقبال مفتاح، وحاوية ترفض الإقلاع كانت
بالضبط غير قابلة للاستخدام لمن يحتاجها أكثر: من يعمل Comodor لديه على
خادم بلا طرفية.

تقول السجلات ذلك قبل أن تفتح أي شيء:

```
No provider is configured yet — the page will ask when you open it.
```

Compose أيًّا من هذه المتغيرات المضبوطة في صدفتك (shell)، دون كتابتها في الصورة أو في ملف compose:

```
ANTHROPIC_API_KEY   OPENAI_API_KEY   OPENROUTER_API_KEY   DEEPSEEK_API_KEY
GOOGLE_API_KEY      GROQ_API_KEY     XAI_API_KEY          MISTRAL_API_KEY
XIAOMI_API_KEY
```

تفضّل ملفًا على سجل أوامر صدفتك؟ ضعه في ملف `.env` بجوار ملف compose — يقرؤه compose، وهو مُتجاوَز في git.

---

## أين يعمل

كل ما يستطيع الوكيل لمسه هو مجلد `work/` بجوار ملف compose. ولتوجيهه إلى مكان آخر:

```yaml
volumes:
  - "/path/to/your/project:/work"
```

أما ما يتعلّمه — العقل، وتصحيحاتك، وسجلّات الجلسات — فيعيش في حجم مسمّى (named volume)، فينجو من `docker compose down` وينساه `docker compose down -v`.

---

## من يستطيع الوصول إليه

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

**القيمة `127.0.0.1` على اليسار هي نموذج الأمان كله.** احذفها ويصبح المنفذ على كل واجهات الجهاز — وهذا المنفذ صَدَفة (shell).

داخل الحاوية يرتبط Comodor بالعنوان `0.0.0.0`، وليس هذا سهوًا: فالحاوية لها مساحة أسماء شبكة خاصة بها، لذا فإن الربط بعنوان loopback داخلها يخفي المنفذ عن الجهاز الذي يشغّلها. ومن يصل إليه فعلًا يتحدد بطريقة نشر المنفذ، واللافتة تقول ذلك.

---

## ما يجوز للحاوية فعله

```yaml
cap_drop: [ALL]
security_opt:
  - no-new-privileges:true
```

الحاوية تنفّذ أوامر صَدَفة، فهي التي تقف بينها وبين جهازك. ولا يُعطى شيئًا لا يحتاجه، ويعمل كمستخدم غير جذري (non-root).

---

## تثبيت إصدار

```yaml
args:
  COMODOR_VERSION: ""
```

مثبَّت افتراضيًا حتى تكون إعادة البناء قابلة للتكرار. وللحصول على أحدث إصدار بدلًا من ذلك:

```bash
docker compose build --build-arg COMODOR_VERSION=
```

---

## تشغيل شيء آخر داخله

```bash
docker compose run --rm comodor comodor doctor
docker compose run --rm comodor sh
```

لا وسائط، أو وسائط تبدأ بشرطة، تعني «شغّل واجهة الويب بهذه الخيارات». وأي شيء آخر هو أمر يُنفَّذ بدلًا من ذلك.

---

## ما لا يوجد داخل الحاوية

**شاشتك.** فـ[التحكم في سطح المكتب](computer.md) يقود الجهاز الذي يعمل عليه Comodor، وفي الحاوية يكون ذلك جهازًا بلا شاشة عرض. والأداة لا تُعرض هناك.

أما [المتصفح](browser.md) فيعمل — فـChromium وخطوطه موجودان في الصورة.

---

## إذا رفض البدء

**لا شيء على `localhost:8765`** — تأكد من نشر المنفذ: `docker compose ps`.

**يخرج فورًا** — اقرأ السجل. وفي معظم الأحيان يكون السبب عدم ضبط أي مزوّد؛ والرسالة تذكر ما يجب ضبطه.

**`exec /usr/local/bin/comodor-start: no such file or directory`** — استنساخ بأسطر تنتهي بـ CRLF. أُصلح ذلك في الفرع بواسطة ملف `.gitattributes`؛ فإن رأيته اسحب التحديثات.

---

## انظر أيضًا

- [من متصفح](web.md) — الواجهة التي ستستخدمها
- [الأمان](safety.md) — ما يجوز للوكيل فعله داخل الحاوية
