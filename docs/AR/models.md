# اختيار نموذج

يعمل Comodor مع أي شيء يفهم واجهة OpenAI أو Anthropic — سبعة عشر مزوّدًا
فورًا من الصندوق، إضافة إلى أي شيء آخر له عنوان URL.

---

## الجواب المختصر

| تريد | اختر |
|---|---|
| أيسر بداية، مفتاح واحد، كل شيء | **OpenRouter** |
| أقوى عمل وكيلي | **Anthropic**، `claude-sonnet-5` |
| ألا تدفع شيئًا وتبقى دون اتصال | **Ollama** أو **LM Studio** |
| رخيص جدًا، جيد في الكود | **DeepSeek** |
| سريع جدًا | **Groq** أو **Cerebras** |

```bash
comodor setup        # pick one, once
```

---

## كل مزوّد

**مستضاف، بمفتاح واحد:** OpenRouter · Anthropic · OpenAI · Google Gemini ·
DeepSeek · xAI · Mistral · Groq · Cerebras · Moonshot (Kimi) · Z.AI (GLM) ·
Qwen · Together · Fireworks · Xiaomi MiMo

**على جهازك، بلا مفتاح:** Ollama · LM Studio

**أي شيء آخر:** اختر *Something else* وأعطه عنوان URL أساسي. أي نقطة نهاية
متوافقة مع OpenAI تعمل.

---

## تشغيله محليًا، مجانًا

```bash
ollama pull qwen2.5-coder:14b
comodor setup           # choose Ollama
```

لا مفتاح، لا كلفة، لا شبكة. نموذج 14B للمبرمجين قابل للاستخدام فعلًا في العمل
اليومي؛ ويظهر الفرق في المهام الطويلة متعددة الخطوات.

---

## التبديل

```bash
comodor --model claude-haiku-4-5      # this run only
```

```
/model                  # a list of what the provider offers
/model gpt-4o           # by name
/provider               # a different provider entirely
```

يتبع مقياس السياق النموذج. فالانتقال من نموذج بمليون رمز إلى نموذج 128k يغيّر
الحد فورًا — وهذا مهم، لأن الوكيل يلخّص المحادثة عند جزء من الحد، والحد القديم
يعني أنه لا يلخّص أبدًا ثم يفشل عند السقف الحقيقي للمزوّد.

لجعل التبديل دائمًا: `/save`، أو عدّل `~/.comodor/config.json`.

---

## المفاتيح

كلا المكانين يعمل، ولا يُنسخ أحدهما إلى الآخر:

```json
{ "providers": { "anthropic": { "api_key": "sk-ant-…" } } }
```

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

المفتاح في بيئتك **يبقى هناك** — لن يكتبه `/save` إلى القرص. فالتصدير بدل
الحفظ قرار، ويُحترم.

يُكتب ملف إعداد Comodor نفسه بأذونات المالك فقط، ولا يظهر مفتاحك أبدًا في سجل،
أو نسخة نصية، أو تصدير، أو تتبع استثناء.
[السلامة](safety.md#your-keys).

---

## البوابة

وجّه عبر عدة مزوّدين بدل تثبيت واحد.

```
/gw                    # or F5
```

```json
{
  "gateway": {
    "enabled": true,
    "policy": "quality",
    "chain": ["anthropic", "openrouter", "deepseek"],
    "failure_threshold": 3
  }
}
```

`policy` إما `cost` أو `speed` أو `quality`. ويُتجاوَز المزوّد الذي يفشل ثلاث
مرات متتالية لمدة دقيقة. ويعرض سطر الحالة `GW: Quality` عند تشغيله،
و`GW: Disable` عند إيقافه.

---

## الإبصار

تعيد بعض الأدوات صورًا — `browse look`، وكل لقطة شاشة من `computer`. وتحتاج
هذه نموذجًا يستطيع الرؤية. وتستطيع ذلك كل عائلات Claude وGPT-4o الحالية؛
ومعظم النماذج المفتوحة لا تستطيع.

إن كنت تنوي استخدام [الشاشة](computer.md)، فتحقق أولًا من أن للنموذج عينين،
وإلا سُلِّم صورة لا يستطيع قراءتها وسيخمّن.

---

## ما يكلف

```
/cost
```

راجع [التكلفة](cost.md) للتخزين المؤقت والميزانيات وسبب أحيانًا نطاق الإنفاق
لا يُفرَض.
