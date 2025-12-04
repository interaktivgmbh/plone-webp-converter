# convert_images_to_webp.py

A script to convert images already stored in Plone to WebP.

The script is **project-independent** and works with **any Plone 6 backend**
(Cookieplone/uv, Buildout, custom venv, Docker).
It performs only the image conversion — all deployment logic (start/stop,
cron automation, etc.) lives outside the script.

---

## What the script does

- Converts existing image fields to WebP
- Preserves PNG transparency (alpha channel)
- Skips images already stored as WebP
- Shows a live progress bar (percent, count, ETA)
- Allows dry-run mode to verify changes without writing anything
- Supports configurable WebP quality

By default, these Plone content types are scanned:

- `Image`
- `News Item`
- `Event`
- `File`
- `Document`

The script checks these fields:

- `image`
- `event_image`
- `lead_image`

---

## Requirements

- Plone 6 backend (Volto or Classic)
- Pillow (already included in Plone)
- A working `zconsole` binary

Your backend may provide `zconsole` at:

| Setup               | Path                          |
|--------------------|-------------------------------|
| Cookieplone / uv   | `.venv/bin/zconsole`          |
| Buildout           | `bin/zconsole`                |
| Custom venv        | `<venv>/bin/zconsole`         |
| Docker image       | `/plone/instance/bin/zconsole` (example) |

Find it via:

```bash
find . -type f -name "zconsole"
```

---

## Configuration (environment variables)

The script reads three simple environment variables:

- **QUALITY**
  WebP quality (0–100)
  Default: `85`

- **DRY_RUN**
  `1` → simulate conversion (no writes)
  `0` → real conversion
  Default: `0`

- **PLONE_SITE_ID**
  Plone site to operate on
  Default: `Plone`

If none are set, defaults are used.

---

## One-off execution

### 1. Find your zconsole path

Example (Cookieplone):

```bash
.venv/bin/zconsole
```

Example (Buildout):

```bash
bin/zconsole
```

Use whichever exists.

---

### 2. Dry-run test (recommended)

```bash
cd /path/to/backend

DRY_RUN=1 QUALITY=75   <path-to-zconsole> run instance/etc/zope.conf scripts/convert_images_to_webp.py
```

---

### 3. Real conversion

```bash
DRY_RUN=0 QUALITY=85   <path-to-zconsole> run instance/etc/zope.conf scripts/convert_images_to_webp.py
```

The script prints everything to stdout
(progress bar, converted objects, skipped items, errors).

---

## Cron job with backend start/stop

If your project requires temporarily shutting down the backend during
conversion (e.g. to avoid blob conflicts), this can be automated via the
accompanying `run_webp_job.sh`.

Example cronjob (runs daily at 03:00):

```cron
0 3 * * * /path/to/backend/scripts/run_webp_job.sh
```

The provided `run_webp_job.sh`:

- stops the backend (runwsgi)
- executes the WebP converter via zconsole
- restarts the backend
- writes all output to:

```
backend/var/log/webp_cron.log
```

To run it manually:

```bash
DRY_RUN=1 QUALITY=80 ./scripts/run_webp_job.sh
```

You may override:

```bash
DRY_RUN=1 QUALITY=50 LOGFILE=/custom/log/path ./scripts/run_webp_job.sh
```

---

## Operational notes & safety

- With `DRY_RUN=0` the script **overwrites original images**.
  There is no built-in backup or undo.
- Always create a backup of:
  - `Data.fs`
  - blob directory
- The initial run may take significant time depending on object count and image sizes.
- Always start with a **dry run** and review the logfile.
- Ideally run during low traffic times (e.g. late night).
