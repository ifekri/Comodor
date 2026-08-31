# Spec: API Server سازگار با OpenAI

> **EN summary:** ابزار مرجع can expose itself as an OpenAI-compatible `/v1/chat/completions` endpoint so any existing frontend (Open WebUI, LobeChat, LibreChat, IDEs) can drive the agent. Comodor's web UI is its own custom protocol — great for its panel, invisible to the ecosystem. This spec adds a stdlib `ThreadingHTTPServer` route (reusing the web server's auth model: loopback bind, per-run token, HttpOnly cookie equivalent via `Authorization: Bearer`) that maps OpenAI requests onto `agent/loop.py` and streams back SSE. Priority **P1**, effort **M**.

## قابلیت در ابزار مرجع چطور است

- `ابزار مرجع serve` یک endpoint سازگار با OpenAI ارائه می‌دهد؛ فرانت‌ندهای استاندارد بدون تغییر وصل می‌شوند.
- پشتیبانی از streaming (SSE) و non-streaming؛ مپ کردن tool-call ها به فرمت OpenAI در حد امکان (ایجنتی درونی hidden است).

## جای آن در Comodor

- موجود و مستقیم قابل‌استفاده: `web/server.py` (ThreadingHTTPServer، توکن per-run، سقف بدنه‌ی ۱ مگابایت، بندهای امنیتی)، `net/sse.py` (کلاس SSE آماده)، `agent/loop.py`، `session/store.py`.
- جدید: `src/comodor/api/` با `server.py` (حالت دوم همان web server یا سرور جدا `comodor serve`)، `openai_schema.py` (تبدیل پیام‌ها)، `session_map.py`.

## طراحی پیشنهادی

```
CLI:     comodor serve [--host 127.0.0.1] [--port 8787] [--token ...]
API:     POST /v1/chat/completions        (stream + non-stream)
         GET  /v1/models                  (فهرست مدل‌های کانفیگ‌شده)
         POST /v1/chat/completions با headers: Authorization: Bearer <token>
کانفیگ:  api.enabled=false, api.bind=127.0.0.1, api.token_ttl="per-run",
         api.allow_tools=false, api.max_turns=8
```

- **معناشناسی ایجنتی:** هر request یک «turn واحد» باشد — ایجنتی loop درون `max_turns` محدود می‌دود و فقط پاسخ نهایی به فرمت OpenAI برگردد؛ tool-call ها هرگز به کلاینت leak نشوند (مگر `api.allow_tools=true` که پاسخ ناتمام با tool_calls برمی‌گردد).
- **جلسه:** کلاینت‌های OpenAI stateless اند؛ session continuity با هدر اختیاری `X-Comodor-Session` (مقدار = session id برگشتی در پاسخ قبلی) — بدون کوکی، بدون حالت پنهان.
- **امنیت:** همان قانون web: bind پیش‌فرض loopback، غیر-loopback با هشدار صریح؛ توکن مقایسه‌ی constant-time؛ سقف بدنه؛ لاگ بدون token.
- streaming با `net/sse.py` و فرمت `data: {...}\n\n` استاندارد + `data: [DONE]`.
- مودهای act/chat از طریق فیلد غیراستاندارد `comodor: {"mode": "plan"}` پذیرفته شود — خارج از schema، کلاینت‌های استاندارد نشکند.

## نقشه‌ی پیاده‌سازی

1. `api/openai_schema.py` — مپ messages (system/user/assistant/tool) → فرمت داخلی `providers/base.py`؛ رد قطعات پشتیبانی‌نشده با پیام روشن.
2. `api/handlers.py` — ۲ endpoint؛ غیر-blocking از طریق نخ worker (الگوی web/session.py).
3. streaming: chunk های متن از StreamEvent در loop → delta های OpenAI.
4. CLI `serve` + یکپارچگی `doctor.py` (چک پورت و توکن).
5. تست: curl ساده، streaming، جلسه‌ی stateful با هدر، احراز توکن، سقف بدنه.

## پذیرش و تست

- Open WebUI با تنظیم «OpenAI-compatible base URL» به `comodor serve` وصل شود و chat + streaming کار کند.
- بدون توکن → 401 constant-time؛ بدنه‌ی ۲ مگابایتی → 413.
- `max_turns` سر رود → پاسخ نهایی با یادداشت بریده‌شدن، نه هنگ.
