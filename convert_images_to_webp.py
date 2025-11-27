import gc
import io
import logging
import os
import sys
import time
from datetime import datetime

import transaction
from PIL import Image
from ZODB.POSException import ConflictError
from plone import api
from zope.component.hooks import setSite


def safe_int(value, default):
    """Return int(value) or default if value is None/empty/invalid."""
    if value is None:
        return default
    value = str(value).strip()
    if value == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


# Read configuration from environment with safe fallbacks
QUALITY = safe_int(os.environ.get("QUALITY"), 85)
DRY_RUN = bool(safe_int(os.environ.get("DRY_RUN"), 0))

# Commit every N objects to keep transactions small
COMMIT_EVERY = 100
# Only pack database when not in DRY_RUN mode
PACK_DATABASE_AFTER = not DRY_RUN
# Plone site id, configurable via env
PLONE_SITE_ID = os.environ.get("PLONE_SITE_ID") or "Plone"

# List of portal types that may contain image fields
PORTAL_TYPES = ["Image", "News Item", "Event", "File", "Document"]


# ----------------------------------------------------------
# PROGRESS BAR
# ----------------------------------------------------------

def progress_bar(current, total, start_time, length=30):
    """Simple ASCII progress bar usable inside Zope scripts."""
    if total <= 0:
        return ""

    percent = current / float(total)
    filled = int(length * percent)
    bar = "█" * filled + "░" * (length - filled)

    elapsed = time.time() - start_time
    if current > 0:
        eta = elapsed / current * (total - current)
    else:
        eta = 0

    line = f"[{bar}] {percent * 100:5.1f}%  {current}/{total}  ETA {eta:5.1f}s"

    # Print to terminal (overwrite line)
    sys.stdout.write("\r" + line)
    sys.stdout.flush()

    return line


# ----------------------------------------------------------
# IMAGE CONVERSION
# ----------------------------------------------------------

def convert_blob_to_webp(blob_data: bytes) -> bytes | None:
    """Convert raw image blob data to WEBP bytes (lossy, with PNG alpha support)."""
    logger = logging.getLogger("webp-converter")

    try:
        img = Image.open(io.BytesIO(blob_data))

        # Preserve PNG transparency by using RGBA
        if img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        ):
            logger.info("- PNG transparency detected → RGBA lossy WebP")
            img = img.convert("RGBA")
            out = io.BytesIO()
            img.save(
                out,
                "WEBP",
                quality=QUALITY,
                method=6,
                lossless=False,
                exact=False,
            )
        else:
            # JPEG / JPG / others → RGB, no alpha channel
            img = img.convert("RGB")
            out = io.BytesIO()
            img.save(
                out,
                "WEBP",
                quality=QUALITY,
                method=6,
                lossless=False,
            )

        return out.getvalue()

    except Exception as e:
        # Log and skip images that cannot be converted
        logger.error(f"WEBP conversion failed: {e}")
        return None


# ----------------------------------------------------------
# PROCESS OBJECT
# ----------------------------------------------------------

def process_object(obj, logger: logging.Logger) -> bool:
    """Process a single Plone object and convert its image fields to WEBP."""
    from plone.namedfile.file import NamedBlobImage

    # Candidate field names on the object that might contain images
    candidate_fields = ["image", "event_image", "lead_image"]
    changed = False

    for field_name in candidate_fields:
        field_value = getattr(obj, field_name, None)
        if not field_value:
            continue

        data = getattr(field_value, "data", None)
        if not data:
            continue

        # Skip if the field is already in WEBP format
        if getattr(field_value, "contentType", "").lower() == "image/webp":
            logger.info(f"SKIP already webp: {obj.absolute_url()}")
            continue

        # Try conversion
        webp_data = convert_blob_to_webp(data)
        if not webp_data:
            logger.warning(f"Conversion failed: {obj.absolute_url()}")
            continue

        # Generate new filename with .webp extension
        filename = field_value.filename or "image"
        base = filename.rsplit(".", 1)[0]
        new_filename = f"{base}.webp"

        logger.info(
            f"CONVERT {obj.absolute_url()} → {new_filename} "
            f"(quality={QUALITY}, dry_run={DRY_RUN})"
        )

        if not DRY_RUN:
            # Replace original field with new WEBP blob
            new_image = NamedBlobImage(
                data=webp_data,
                filename=new_filename,
                contentType="image/webp",
            )
            setattr(obj, field_name, new_image)
            changed = True

    # Reindex object in catalog if it was modified
    if changed and not DRY_RUN:
        try:
            obj.reindexObject()
        except Exception:
            logger.debug(f"Reindex failed: {obj.absolute_url()}")

    return changed


# ----------------------------------------------------------
# PACK DB
# ----------------------------------------------------------

def pack_database(logger: logging.Logger) -> None:
    """Pack the ZODB to reduce size after many blob changes."""
    site = api.portal.get()
    connection = site._p_jar
    db = connection.db()
    logger.info("Packing database...")
    db.pack()
    logger.info("DB packed.")


# ----------------------------------------------------------
# MAIN LOOP
# ----------------------------------------------------------

def convert_all_images(logger: logging.Logger) -> None:
    """Iterate over all matching content objects and convert image fields."""
    catalog = api.portal.get_tool("portal_catalog")
    brains = catalog.unrestrictedSearchResults(portal_type=PORTAL_TYPES)

    total = len(brains)

    if not brains:
        logger.info("No image-related content found.")
        return

    logger.info("--------------------------------------------------")
    logger.info("Starting image conversion")
    logger.info(f"QUALITY={QUALITY}")
    logger.info(f"DRY_RUN={DRY_RUN}")
    logger.info(f"TOTAL OBJECTS={total}")
    logger.info("--------------------------------------------------")

    processed = skipped = failed = 0
    portal = api.portal.get()
    start_time = time.time()

    for idx, brain in enumerate(brains, 1):
        # Update progress bar for terminal output
        pb_line = progress_bar(idx, total, start_time)
        # Log progress occasionally to avoid huge log files
        if idx == 1 or idx == total or idx % 50 == 0:
            logger.info(pb_line)

        try:
            # Load real object from the brain
            obj = brain._unrestrictedGetObject()
        except ConflictError:
            failed += 1
            logger.error(f"ConflictError loading {brain.getPath()}")
            continue
        except Exception as e:
            failed += 1
            logger.error(f"Cannot load {brain.getPath()}: {e}")
            continue

        try:
            changed = process_object(obj, logger)
        except ConflictError:
            failed += 1
            logger.error(f"ConflictError processing {brain.getPath()}")
            continue
        except Exception as e:
            failed += 1
            logger.error(f"Error processing {brain.getPath()}: {e}")
            continue

        if changed:
            processed += 1
        else:
            skipped += 1

        # Commit regularly to keep transactions small and memory under control
        if idx % COMMIT_EVERY == 0 and not DRY_RUN:
            transaction.commit()
            portal._p_jar.cacheMinimize()
            gc.collect()
            logger.info(f"Committed at {idx} objects")

    # Move to a new line after the progress bar
    sys.stdout.write("\n")
    sys.stdout.flush()

    # Final commit after processing all objects
    if not DRY_RUN:
        transaction.commit()
        portal._p_jar.cacheMinimize()
        gc.collect()

    logger.info("--------------------------------------------------")
    logger.info(f"DONE: {processed} converted, {skipped} skipped, {failed} failed.")
    logger.info("--------------------------------------------------")

    # Optionally pack the database after successful conversion
    if not DRY_RUN and PACK_DATABASE_AFTER:
        pack_database(logger)


# ----------------------------------------------------------
# LOGGER + MAIN
# ----------------------------------------------------------

def setup_logging() -> logging.Logger:
    """Configure logging to both file and stdout with a timestamped filename."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        # Fallback when __file__ is not available (e.g. in some interactive runs)
        script_dir = os.getcwd()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = os.path.join(script_dir, f"convert_images_to_webp_{timestamp}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(logfile, mode="w"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    return logging.getLogger("webp-converter")


def main(app):
    """Entry point when executed via 'bin/instance run' or 'zconsole run'."""
    logger = setup_logging()
    # Select the Plone site specified by PLONE_SITE_ID
    site = app[PLONE_SITE_ID]
    setSite(site)

    logger.info(f"Using site /{PLONE_SITE_ID}")
    convert_all_images(logger)


# Only run main() when executed inside a Zope app context (not when imported).
if "app" in globals():
    main(app)
