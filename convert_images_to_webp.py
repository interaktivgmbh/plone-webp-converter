import gc
import logging
import os
import sys
import time
from io import BytesIO
from typing import Any, Optional

import transaction
from PIL import Image
from ZODB.POSException import ConflictError
from plone import api
from plone.namedfile.file import NamedBlobImage
from zope.component.hooks import setSite

QUALITY: int = 85
DRY_RUN: bool = False

COMMIT_EVERY: int = 100
PACK_DATABASE_AFTER: bool = True

PLONE_SITE_ID: str = os.environ.get("PLONE_SITE_ID") or "Plone"

PORTAL_TYPES = ["Image", "News Item", "Event", "File", "Document"]


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_config() -> None:
    global QUALITY, DRY_RUN, PLONE_SITE_ID, PACK_DATABASE_AFTER

    QUALITY = safe_int(os.environ.get("QUALITY", QUALITY), QUALITY)
    DRY_RUN = bool(safe_int(os.environ.get("DRY_RUN", int(DRY_RUN)), int(DRY_RUN)))
    PLONE_SITE_ID = os.environ.get("PLONE_SITE_ID") or PLONE_SITE_ID
    PACK_DATABASE_AFTER = not DRY_RUN


def progress_bar(
    current: int,
    total: int,
    start_time: float,
    length: int = 30,
) -> str:
    if total <= 0:
        return ""

    percent = current / float(total)
    filled = int(length * percent)
    bar = "█" * filled + "░" * (length - filled)

    elapsed = time.time() - start_time
    eta = (elapsed / current * (total - current)) if current > 0 else 0

    line = f"[{bar}] {percent * 100:5.1f}%  {current}/{total}  ETA {eta:5.1f}s"

    sys.stdout.write("\r" + line)
    sys.stdout.flush()

    return line


def convert_blob_to_webp(blob_data: bytes) -> Optional[bytes]:
    logger = logging.getLogger("webp-converter")

    try:
        img = Image.open(BytesIO(blob_data))

        if img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        ):
            logger.info("PNG transparency detected → convert with alpha")
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        out = BytesIO()
        img.save(
            out,
            "WEBP",
            quality=QUALITY,
            method=6,
            lossless=False,
        )
        return out.getvalue()

    except Exception as exc:
        logger.error("WEBP conversion failed: %s", exc)
        return None


def process_object(obj: Any, logger: logging.Logger) -> bool:
    candidate_fields = ["image", "event_image", "lead_image"]
    changed = False

    for field_name in candidate_fields:
        field_value = getattr(obj, field_name, None)
        if not field_value:
            continue

        data = getattr(field_value, "data", None)
        if not data:
            continue

        if getattr(field_value, "contentType", "").lower() == "image/webp":
            logger.info("Skip already webp: %s", obj.absolute_url())
            continue

        webp_data = convert_blob_to_webp(data)
        if not webp_data:
            logger.warning("Conversion failed: %s", obj.absolute_url())
            continue

        filename = field_value.filename or "image"
        base = filename.rsplit(".", 1)[0]
        new_filename = f"{base}.webp"

        logger.info(
            "Convert %s → %s (quality=%s, dry_run=%s)",
            obj.absolute_url(),
            new_filename,
            QUALITY,
            DRY_RUN,
        )

        if not DRY_RUN:
            new_image = NamedBlobImage(
                data=webp_data,
                filename=new_filename,
                contentType="image/webp",
            )
            setattr(obj, field_name, new_image)
            changed = True

    if changed and not DRY_RUN:
        try:
            obj.reindexObject()
        except Exception:
            logger.debug("Reindex failed: %s", obj.absolute_url())

    return changed


def pack_database(logger: logging.Logger) -> None:
    site = api.portal.get()
    connection = site._p_jar
    db = connection.db()
    logger.info("Packing database...")
    db.pack()
    logger.info("Database packed.")


def convert_all_images(logger: logging.Logger) -> None:
    catalog = api.portal.get_tool("portal_catalog")
    brains = catalog.unrestrictedSearchResults(portal_type=PORTAL_TYPES)

    total = len(brains)
    if not brains:
        logger.info("No image-related content found.")
        return

    logger.info("--------------------------------------------------")
    logger.info("Starting image conversion")
    logger.info("QUALITY=%s", QUALITY)
    logger.info("DRY_RUN=%s", DRY_RUN)
    logger.info("TOTAL OBJECTS=%s", total)
    logger.info("--------------------------------------------------")

    processed = skipped = failed = 0
    portal = api.portal.get()
    start_time = time.time()

    for idx, brain in enumerate(brains, 1):
        pb_line = progress_bar(idx, total, start_time)
        if idx == 1 or idx == total or idx % 50 == 0:
            logger.info(pb_line)

        try:
            obj = brain._unrestrictedGetObject()
        except ConflictError:
            failed += 1
            logger.error("ConflictError loading %s", brain.getPath())
            continue
        except Exception as exc:
            failed += 1
            logger.error("Cannot load %s: %s", brain.getPath(), exc)
            continue

        try:
            changed = process_object(obj, logger)
        except ConflictError:
            failed += 1
            logger.error("ConflictError processing %s", brain.getPath())
            continue
        except Exception as exc:
            failed += 1
            logger.error("Error processing %s: %s", brain.getPath(), exc)
            continue

        if changed:
            processed += 1
        else:
            skipped += 1

        if idx % COMMIT_EVERY == 0 and not DRY_RUN:
            transaction.commit()
            portal._p_jar.cacheMinimize()
            gc.collect()
            logger.info("Committed at %s objects", idx)

    sys.stdout.write("\n")
    sys.stdout.flush()

    if not DRY_RUN:
        transaction.commit()
        portal._p_jar.cacheMinimize()
        gc.collect()

    logger.info("--------------------------------------------------")
    logger.info(
        "DONE: %s converted, %s skipped, %s failed.",
        processed,
        skipped,
        failed,
    )
    logger.info("--------------------------------------------------")

    if not DRY_RUN and PACK_DATABASE_AFTER:
        pack_database(logger)


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
        force=True,
    )
    return logging.getLogger("webp-converter")


def main(app: Any) -> None:
    logger = setup_logging()
    load_config()

    site = app[PLONE_SITE_ID]
    setSite(site)

    logger.info("Using site /%s", PLONE_SITE_ID)
    convert_all_images(logger)


if __name__ == "__main__":
    if "app" not in globals():
        sys.exit(1)

    main(app)
