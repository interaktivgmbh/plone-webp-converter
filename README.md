# convert_images_to_webp.py

A generic, project-independent helper script for converting images
already stored in Plone to **WebP**.\
It is designed for Plone 6 / Cookieplone backends and works with both
classic Plone sites and Volto-based projects.

The script focuses exclusively on image conversion.\
Deployment decisions (start/stop lifecycle, supervisor/systemd
integration, cron jobs, etc.) are intentionally left to each project.

> **Important:** The Plone backend **must be fully stopped** before running this script.  
> Running it while the backend is active can cause conflicts, partial writes, or locked blobs.

------------------------------------------------------------------------

## Features

-   Converts existing images to WebP
-   Preserves PNG transparency (alpha channel)
-   Skips images already stored as WebP
-   Live progress bar (percentage, processed count, ETA)
-   Fully configurable via **command-line parameters**
-   Dry-run mode (no writes)
-   Optional ZODB packing after conversion
-   Batch commits for better performance on large sites

By default, the script processes these Plone content types:

-   `Image`
-   `News Item`
-   `Event`
-   `File`
-   `Document`

And inspects the following fields:

-   `image`
-   `event_image`
-   `lead_image`

------------------------------------------------------------------------

## Requirements

-   Plone backend
-   Pillow installed (already included in Plone)
-   A working **zconsole** binary

### Possible zconsole locations

| Setup            | Path                          |
|------------------|-------------------------------|
| Cookieplone / uv | `.venv/bin/zconsole`          |
| Buildout         | `bin/zconsole`                |
| Custom venv      | `<venv>/bin/zconsole`         |
| Docker           | `/plone/instance/bin/zconsole`|
---
## CLI Configuration (No Environment Variables)

 All configuration is passed through command-line arguments:

| Flag                 | Description                    | Default |
|----------------------|--------------------------------|---------|
| `--quality <int>`    | WebP quality (0–100)           | `85`    |
| `--dry-run`          | Simulate conversion, no writes | `False` |
| `--site-id <name>`   | Plone site ID                  | `Plone` |
| `--no-pack`          | Skip ZODB packing              | `False` |
| `--commit-every <n>` | Commit every N objects         | `100`   |

------------------------------------------------------------------------
## Running the Script

### Dry-run test (recommended)

``` bash
zconsole run instance/etc/zope.conf scripts/convert_images_to_webp.py --dry-run --quality=75
```

### Real conversion

``` bash
zconsole run instance/etc/zope.conf scripts/convert_images_to_webp.py --quality=85
```

------------------------------------------------------------------------

## Running via Cron

### Example: nightly at 03:00

``` cron
0 3 * * * cd /path/to/backend && .venv/bin/zconsole run instance/etc/zope.conf scripts/convert_images_to_webp.py --quality=85 >> var/log/webp_cron.log 2>&1
```

------------------------------------------------------------------------

## Safety Notes

-   Running without `--dry-run` overwrites original images\
-   Always back up `Data.fs` and blobstorage\
-   Prefer running during low-traffic times
