# convert_images_to_webp.py

A generic, project-independent helper script for converting images already stored in Plone to WebP.
It is designed for Plone 6 / Cookieplone backends and works with both classic Plone sites and Volto-based projects.

The script focuses exclusively on image conversion.
Deployment decisions (start/stop lifecycle, supervisor/systemd integration, cron jobs, etc.) are intentionally left to each project.

---

## Features

- Converts existing images to WebP
- Converts GIFs to WebP (static and animated)
  Note: animated GIFs converted to WebP may appear non-animated in some Plone previews (e.g. folder listings or image pickers).
  When embedded on a page, they render normally as animated images.
- Preserves PNG transparency (alpha channel)
- Skips images already stored as WebP
- Live progress bar (percentage, processed count, ETA)
- Fully configurable via command-line parameters
- Dry-run mode (no writes)
- Optional ZODB packing after conversion
- Batch commits for better performance on large sites
- Optional suppression of noisy Pillow/Plone image-sniffer warnings
- Optional Pillow feature check (useful for Docker/container debugging)

By default, the script processes these Plone content types:

- `Image`
- `News Item`
- `Event`
- `File`
- `Document`

And inspects the following fields:

- `image`
- `event_image`
- `lead_image`

---

## Requirements

- Plone backend
- Pillow installed (already included in Plone)
- A working zconsole binary

### Container note (Pillow / native libraries)

On some Docker images, Pillow can be installed but compiled without support for certain formats (e.g. WebP).
If the conversion or image scales/previews behave unexpectedly, run the script with `--pillow-check` and verify that `webp`, `jpg`, and `zlib` are `True`.
If `webp=False`, the container likely needs the corresponding system libraries (e.g. libwebp + rebuild/reinstall Pillow).

### Possible zconsole locations

| Setup            | Path                           |
|------------------|--------------------------------|
| Cookieplone / uv | `.venv/bin/zconsole`           |
| Buildout         | `bin/zconsole`                 |
| Custom venv      | `<venv>/bin/zconsole`          |
| Docker           | `/plone/instance/bin/zconsole` |

---

## CLI Configuration (No Environment Variables)

All configuration is passed through command-line arguments:

| Flag                      | Description                                                            | Default |
|---------------------------|------------------------------------------------------------------------|---------|
| `--quality <int>`         | WebP quality (0–100)                                                   | `85`    |
| `--dry-run`               | Simulate conversion, no writes                                         | `False` |
| `--site-id <name>`        | Plone site ID                                                          | `Plone` |
| `--no-pack`               | Skip ZODB packing                                                      | `False` |
| `--commit-every <n>`      | Commit every N objects                                                 | `100`   |
| `--quiet-sniffer-warnings`| Suppress the known noisy warning `PIL can not recognize the image ...` | `False` |
| `--pillow-check`          | Log Pillow feature support (`webp/jpg/zlib`) at startup                | `False` |

---

## Running the Script

### Dry-run test (recommended)

```bash
zconsole run instance/etc/zope.conf scripts/convert_images_to_webp.py --dry-run --quality=75
```

### Real conversion

```bash
zconsole run instance/etc/zope.conf scripts/convert_images_to_webp.py --quality=85
```

### Quiet logs (optional)

If your logs contain frequent warnings like:

`PIL can not recognize the image. Image is probably broken or of a non-supported format.`

but images still convert correctly, you can suppress this specific, known noisy message:

```bash
zconsole run instance/etc/zope.conf scripts/convert_images_to_webp.py --quality=85 --quiet-sniffer-warnings
```

### Pillow feature check (especially for Docker)

```bash
zconsole run instance/etc/zope.conf scripts/convert_images_to_webp.py --pillow-check --dry-run
```

Expected output contains something like:

`Pillow features: {'webp': True, 'jpg': True, 'zlib': True}`

---

## Running via Cron

### Example: nightly at 03:00

```cron
0 3 * * * cd /path/to/backend && .venv/bin/zconsole run instance/etc/zope.conf scripts/convert_images_to_webp.py --quality=85 >> var/log/webp_cron.log 2>&1
```

---

## Safety Notes

- Running without `--dry-run` overwrites original images
- Always back up `Data.fs` and blobstorage
- Prefer running during low-traffic times
- Consider running `--pillow-check` once in containerized environments to confirm WebP support
