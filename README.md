# convert_images_to_webp

A generic, project-independent helper script to convert images already stored in Plone to WebP.
It is designed for Plone 6 / Cookieplone-based backends and works with both classic Plone sites and Volto projects.

---

## Features

- Converts existing images to WebP
- Supports PNG transparency (keeps alpha channel)
- Configurable quality via environment variable (`QUALITY`)
- Dry-run mode (`DRY_RUN=1`) that performs no writes
- Batch commits and optional database packing
- Live progress bar in the terminal (including ETA and processed object count)

By default, the script processes the following content types:

- `Image`
- `News Item`
- `Event`
- `File`
- `Document`

and checks the following fields on those objects:

- `image`
- `event_image`
- `lead_image`

---

## Progress display

While running, the script shows a live progress bar in the terminal:

- current progress in percent
- number of objects processed so far
- estimated time remaining (ETA)
- graphical bar display (██████░░░░…)
- every 50 objects an additional progress line is written to the logfile

Example terminal output:

```bash
[██████████░░░░░░░░░░░░░░░]  34.2%  171/500  ETA 12.4s
```

The display is updated continuously while the script runs and finishes with a clean newline.

---

## Requirements

- Plone 6
- Working backend environment with `make` and `zconsole`
- Pillow installed in the backend (covered by Plone dependencies)
- Typical Cookieplone/uv-style backend structure, e.g.:
  - `backend/.venv`
  - `backend/instance/etc/zope.conf`
  - `backend/instance/etc/zope.ini`
  - `backend/scripts/convert_images_to_webp.py`
  - `backend/scripts/run_webp_job.sh`

---

## Configuration (environment variables)

The script reads its configuration from environment variables:

- `QUALITY`
  JPEG/WebP quality (0–100)
  Default: `85`

- `DRY_RUN`
  `1` → dry run only, no changes written
  `0` → (default) real conversion, changes are persisted

- `PLONE_SITE_ID`
  Plone site id to operate on (default: `Plone`)

Examples:

```bash
QUALITY=70 DRY_RUN=1 make convert-images-to-webp
QUALITY=80 make convert-images-to-webp
```

---

## Makefile integration

```make
.PHONY: convert-images-to-webp
convert-images-to-webp: $(VENV_FOLDER) instance/etc/zope.ini ## Convert all stored images to WEBP
	@$(BIN_FOLDER)/zconsole run instance/etc/zope.conf ./scripts/convert_images_to_webp.py
```

### Running via Makefile

From the backend folder:

```bash
cd backend
make convert-images-to-webp
```

### With custom quality:

```bash
QUALITY=70 make convert-images-to-webp
```

### Dry-run mode (log only, no changes):

```bash
DRY_RUN=1 make convert-images-to-webp
```

---

## Direct execution via zconsole (without make)

```bash
cd backend
. .venv/bin/activate
QUALITY=75 DRY_RUN=1 .venv/bin/zconsole run instance/etc/zope.conf ./scripts/convert_images_to_webp.py
```

---

## Behavior

### Normal mode (`DRY_RUN=0`)

- Images are converted to WebP
- The image fields are replaced with new `NamedBlobImage` values
- Objects are reindexed in the catalog
- `transaction.commit()` is called regularly in batches
- At the end, the ZODB is packed (`db.pack()`)

### Dry-run mode (`DRY_RUN=1`)

- All matching objects are iterated
- Conversion is simulated, including decoding the images
- No changes are written
- No commits, no database packing
- The logfile shows exactly which objects/fields would be converted

---

## Important notes

- The script overwrites original image data – there is no automatic backup.
- Before using it in production, always create a backup of `Data.fs` and the blob storage.
- Typical nightly execution (e.g. at 03:00) is handled via cron/systemd and not part of the Python script itself.

---

## Automated WebP cron job (`run_webp_job.sh`)

In addition to the Python script, there is a shell script that automates the full workflow:

1. Stop the backend (runwsgi process)
2. Run `convert_images_to_webp.py` via zconsole
3. Restart the backend via runwsgi
4. Log all steps to a dedicated logfile

Project path:

- `backend/scripts/run_webp_job.sh`

The script derives the backend path dynamically from its own location, so it works on different systems without hard-coded paths.

### Make the script executable

From the backend folder:

```bash
cd backend
chmod +x scripts/run_webp_job.sh
```

Optional dry-run test:

```bash
DRY_RUN=1 QUALITY=80 ./scripts/run_webp_job.sh
```

Inspect the log output:

```bash
tail -n 100 var/log/webp_cron.log
```

---

## Setting up a cron job

The automatic execution can be handled via cron (or a systemd timer).
Choose a time with low traffic, for example 03:00 at night.

### Example cron job (production, daily at 03:00)

```bash
0 3 * * * DRY_RUN=0 QUALITY=85 /path/to/backend/scripts/run_webp_job.sh >> /path/to/backend/var/log/webp_cron.log 2>&1
```

Explanation:

- `0 3 * * *` → run every day at 03:00
- `DRY_RUN=0` → real conversion, changes are persisted
- `QUALITY=85` → WebP quality, can be adjusted per project
- `run_webp_job.sh` → stops the backend, runs the converter, restarts the backend
- `>> … 2>&1` → append all output (STDOUT + STDERR) to the log file

### Example cron job for an initial test (dry-run)

```bash
0 3 * * * DRY_RUN=1 QUALITY=80 /path/to/backend/scripts/run_webp_job.sh >> /path/to/backend/var/log/webp_cron.log 2>&1
```

In this mode:

- all objects are iterated and images decoded
- no changes are written
- no database packing is performed
- this is ideal for validating configuration and paths

---

## Operations & recommendations

- Always create a recent backup of `Data.fs` and the blob storage before using the script in production.
- While the job is running, the backend will be temporarily unavailable (stopped and restarted).
- Runtime depends directly on the number and size of stored images.
- The logfile `backend/var/log/webp_cron.log` should be monitored regularly and rotated/archived as needed.
