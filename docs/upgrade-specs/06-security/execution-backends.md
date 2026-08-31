# Spec: Backendهای اجرای ایزوله برای shell

> **EN summary:** Comodor runs `run_shell` on the host with a permission gate, checkpoints, and a hardened Docker *image* — but no runtime isolation choice: you either trust the machine or containerize your whole session. ابزار مرجع supports seven terminal backends (local, Docker, SSH, Singularity, Modal, Daytona, Vercel Sandbox) selectable per task, so an agent can test "what if this command runs in a clean container" or work on a remote box. This spec adds Docker and SSH backends first (the two that matter to 95% of users), behind the existing DANGEROUS gate, with a per-project config. Modal/Daytona are explicitly out of scope (vendor lock-in contradicts Comodor's self-hosted ethos). Priority **P2**, effort **M–L**.

## قابلیت در ابزار مرجع چطور است

مرجع: `tools/environments/` (docker.py، ssh.py، modal.py، …).

- ۷ backend؛ انتخاب per-task؛ Docker با hardening: `--cap-drop ALL` (+ DAC_OVERRIDE/CHOWN/FOWNER re-add)، `no-new-privileges`، `--pids-limit 256`، tmpfs سخت‌گیرانه، root read-only، سقف cpu/mem/disk؛ persistent mode با bind-mount `/workspace`.
- backend container → کل چک‌های approval رد می‌شوند (مرز ایزوله همان container است) — الگوی مهم.

## جای آن در Comodor

- موجود: `tools/shell.py` (اجرا با subprocess)، `safety/permissions.py`، `config.py` (لایه‌ی پروژه)، Dockerfile/`docker-compose.yml` (الگوی hardening موجود برای کپی).
- جدید: `src/comodor/safety/backends.py` + `shell.py` به‌عنوان dispatcher.

## طراحی پیشنهادی

```
کانفیگ (project-layer — .comodor/config.json):
  shell.backend=host          # host | docker | ssh
  shell.docker.image=python:3.13-slim
  shell.docker.mount_workspace=true    # ./ → /workspace:ro? (پیش‌فرض ro؛ rw گزینه)
  shell.docker.harden=true
  shell.ssh.host/user/port/key_path   # key از ~/.ssh فقط خواندنی، هرگز کپی
گیت‌ها:
  - docker: حتی در حالت auto-approve، harden=true اجباری؛ اگر docker daemon
    socket در دسترس نیست → خطای روشن
  - ssh: اتصال اول با تأیید fingerprint (TOFU + نمایش hash)؛ هرگز password prompt
    تعاملی از داخل ایجنتی
  - backend docker/ssh → لایه‌ی DEFAULT_DENY همان بماند (دفاع عمقی)
    ولی approval های آدم ساده‌تر (ایزوله بودن به کاربر یادآوری شود)
انتخاب پویا: دستور /backend در TUI؛ در prompt مدل پیشنهاد بدهد «این را در
  container امتحان کن» (فقط پیشنهاد، خودش عوض نکند)
خروجی: همان قرارداد shell فعلی (exit/stdout/stderr، سقف‌ها، overflow)
checkpoint: فایل‌های host با backend docker mount-rw — snapshot همان مسیر
  (bind-mount زیر workspace است)
```

- **چرا نه Modal/Daytona/Vercel:** وابستگی به سرویس تجاری و کلید ابری؛ در تضاد با «ابزار مال خودت». اگر روزی بخواهد، آداپتور راحت است چون interface یکی است.
- Singularity/HPC هم niche است — skip.

## نقشه‌ی پیاده‌سازی

1. `safety/backends.py`: interface (start/run/stream/stop) + آداپتور host (wrap فعلی).
2. آداپتور docker: `docker run --rm` با پرچم‌های hardening (کپی از docker-compose موجود)؛ انتقال cwd به mount.
3. آداپتور ssh: `ssh -o BatchMode` اجرای دستور + streaم خروجی؛ fingerprint TOFU.
4. dispatcher در `shell.py` + نمایش backend فعال در status bar.
5. تست: docker mock با docker-py؟ — نه: subprocess به docker CLI و تست با فیک parse خروجی؛ تست harden flags؛ ssh با سرور تست محلی.

## پذیرش و تست

- `shell.backend=docker` → `run_shell "pip install x"` داخل container اجرا و host دست‌نخورده.
- harden flags در هر invocation حاضر باشند (تست inspect با docker inspect).
- ssh: قطع شبکه → خطای روشن، نه hang؛ fingerprint تغییر کرده → رد و هشدار.
- با backend غیر host، `verify.py` و checkpoints همچنان کار کنند.
