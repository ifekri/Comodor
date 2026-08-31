# Spec: computer use چند-پلتفرمی (macOS + Linux)

> **EN summary:** Comodor's `computer` tool is Windows-only (`desktop/win32.py` via ctypes) — on macOS/Linux the tool simply isn't offered, which a Windows user never notices but a Mac user absolutely does. Hermes ships desktop control via `cua-driver` (background, no focus stealing). This spec adds macOS ( Quartz via ctypes — like the existing win32.py approach, no dependencies) and Linux X11 (Xlib/XTest via ctypes; Wayland explicitly unsupported with an honest message). The overlay/guard/permission architecture ports directly since it is already backend-abstracted (`desktop/screen.py:backend()`). Priority **P2** (large user segment, but heavy testing burden), effort **L**.

## قابلیت در hermes چطور است

- toolset `computer_use` با `cua-driver` — کنترل دسکتاپ پس‌زمینه‌ای (بدون دزدیدن focus)؛ گیت runtime؛ در TUI فقط وقتی backend موجود.

## جای آن در Comodor

- Comodor از قبل architecture بهتری دارد: facade `desktop/__init__.py` + `screen.py:backend()` که روی پلتفرم ناپشتیبانی `NotSupported` می‌دهد؛ overlay و guard و permission مکانیزم‌ها backend-agnostic اند. کافی است backend بنویسیم.
- جدید: `desktop/quartz.py` (macOS)، `desktop/x11.py` (Linux).

## طراحی پیشنهادی

```
macOS (desktop/quartz.py — ctypes روی ApplicationServices/CoreGraphics):
  screen: CGGetActiveDisplayList + CGDisplayCreateImage → موجودی png.py
  mouse/keys: CGEventCreateMouseEvent/KeyboardEvent (post to HID event tap)
  نکته: post به event tap جلوی «stealth» را نمی‌گیرد ولی از focus-steal کمتر
  ضرر دارد؛ permission لازم: Accessibility (System Settings) — پیام راهنمای
  روشن با لینک صفحه تنظیمات + چک خودکار (AXIsProcessTrusted)
  screen recording permission برای screenshots (چک با CGPreflightScreenCaptureAccess)
Linux X11 (desktop/x11.py — ctypes روی libX11/libXtst):
  screen: XGetImage + XGetDefaultRootWindow؛ mouse: XTestFakeMotionEvent…
  Wayland: NotSupported با پیام صادقانه («Wayland پشتیبانی نمی‌شود؛ X11 اجرا کنید»)
  — هیچ half-پشتیبانی دروغین
keys: همان جدول ترجمه‌ی win32.py به keysyms X
guard/overlay: guard همان (permission هر بار چک)؛ overlay برای macOS با
  NSWindow شفاف (ctypes/AppKit) — v1 اگر سنگین شد: فقط نشانگر terminal-side
  بدون overlay روی-صفحه (صادقانه در UI گفته شود)
سقف‌ها: همان screenshot_tokens=1600 و keep_screenshots=2
```

- **پرچم تبلیغاتی:** «comodor computer on all three OSes with zero dependencies» — هیچ رقیبی این ادعا با stdlib ندارد؛ hermes به cua-driver (وابستگی) تکیه دارد.
- اولویت‌بندی داخل spec: macOS اول (پایگاه کاربر بزرگ‌تر بین توسعه‌دهندگان)؛ X11 دوم؛ Wayland هرگز با پیام شفاف.

## نقشه‌ی پیاده‌سازی

1. `desktop/quartz.py`: display، screenshot (CGImage → png.py)، mouse، keys، چک permissions.
2. `screen.py:backend()`: macOS → quartz؛ لایه‌ی انتخاب backend گسترش.
3. overlay v1: رد یا پیام؛ v2: AppKit window.
4. `desktop/x11.py` با همان interface.
5. تست: unit با mock های ctypes (بدون دسکتاپ واقعی در CI)؛ دستی: چک‌لیست روی هر OS (تست‌های `test_real_desktop.py` الگو بگیرند).
6. `doctor.py`: چک permission های macOS و کتابخانه‌های X11 با remedy.

## پذیرش و تست

- روی macOS بدون permission → پیام راهنمای exact (کدام Settings page) نه خطای خام.
- کلیک/تایپ درست روی هر دو backend (چک‌لیست دستی مستند در docs).
- روی Wayland → پیام شفاف، ابزار advertise نشود.
- رفتار Windows موجود regression نکند.
