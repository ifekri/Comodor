# Spec: توسعه‌ی MCP — resources، prompts، sampling، OAuth

> **EN summary:** Comodor's MCP support is tools-only (both stdio and Streamable HTTP, hand-written). Hermes's MCP integration covers resources, prompts, sampling, OAuth for HTTP servers, schema caching, and a stdio watchdog. Most real-world value for Comodor users is in resources (read-only context like logs/datasets) and prompts (slash-invocable templates); sampling and OAuth are rarer. This spec closes the gap incrementally: resources + prompts in v1, OAuth in v2, sampling only on demand. Priority **P2**, effort **M–L**.

## قابلیت در hermes چطور است

مرجع: `tools/mcp_tool.py`، `mcp_oauth.py`، `mcp_schema_cache.py`، `mcp_stdio_watchdog.py`.

- همه‌ی قابلیت‌های MCP: tools، resources (خواندنی با URI)، prompts (قالب‌های قابل صدا)، sampling (سرور از مدل سرور-میزبان استعلام می‌کند)، OAuth (authorization code + refresh)، schema cache، watchdog برای stdio های هنگ‌کرده، ردact خطاها (ghp_/sk-/Bearer).

## جای آن در Comodor

- موجود: `mcp/protocol.py` (stdio JSON-RPC)، `mcp/http.py` (Streamable HTTP)، `mcp/manager.py`، مکانیزم tool registry (`tools/mcp.py`).
- جدید: گسترش `mcp/manager.py` با resources/prompts و `mcp/oauth.py`.

## طراحی پیشنهادی

```
v1 — resources:
  ابزار:  mcp_list_resources(server) / mcp_read_resource(server, uri) — SAFE
  در /mcp پنل: منابع هر سرور + «این سرور X منبع دارد» (کشف lazy مثل tools)
  استفاده‌ی هوشمند: resources فهرست‌شده در briefing کوتاه (فقط نام‌ها) تا مدل
  بدانند چه چیزی برای خواندن هست — بدون خواندن پیش‌فرض
v1 — prompts:
  هر prompt سرور به یک دستور local مپ شود: comodor prompt <server>/<name> [args]
  یا در TUI /mcp-prompt — متن قالب به‌عنوان پیام کاربر تزریق (شفاف)
v2 — OAuth:
  فقط برای HTTP servers؛ authorization-code + PKCE با سرور loopback (الگوی
  oauth.py موجود OpenRouter!) + refresh token در ~/.comodor/mcp-tokens/ (0600)
v2 — sampling:
  پیش‌فرض رد؛ کانفیگ per-server mcp.servers.<name>.allow_sampling=false؛
  هر sampling request گیت مجوز بگیرد (مدل جاری با سقف توکن)
 watchdog: timeout برای stdio (الگوی hermes) — سرور بی‌پاسخ → kill + وضعیت در /mcp
 ردact خطاها: الگوهای ghp_/sk-/Bearer در پیام‌های خطای MCP (redact.py)
```

- **اولویت‌بندی واقعی:** بررسی بازار نشان می‌دهد ۹۰٪ سرورهای مفید tools دارند؛ resources برای سرورهای داده (sqlite، filesystem، postgres) ارزش واقعی دارد — همان ۱۲ سرور catalogue موجود خوب‌اند.

## نقشه‌ی پیاده‌سازی

1. `mcp/manager.py`: متدهای `resources/list|read` و `prompts/list|get` روی دو ترنسپورت.
2. ابزارهای SAFE دوگانه + کش فهرست (mtime cache الگوی hermes).
3. `/mcp` گسترش + `comodor mcp resources|prompts` CLI.
4. v2: `mcp/oauth.py` reuse `providers/oauth.py` (PKCE loopback — از قبل نوشته شده).
5. watchdog + redact.
6. تست: fake MCP server (existing support file) با resource و prompt؛ sampling رد پیش‌فرض؛ OAuth flow با سرور تست.

## پذیرش و تست

- سرور sqlite MCP: tools کار کند + منابع دیتابیس فهرست و خوانده شوند.
- prompt سرور در TUI قابل اجرا باشد.
- سرور با توکن منقضی → پیام روشن و لینک دوباره-auth، نه crash خاموش.
- sampling بدون صریح‌کردن → رد.
