import gc
import logging
import sys
import time
from argparse import ArgumentParser
from io import BytesIO
from typing import Any, Dict, Optional

import transaction
from PIL import Image, ImageSequence
from Products.CMFPlone.Portal import PloneSite
from ZODB.POSException import ConflictError
from plone import api
from plone.namedfile.file import NamedBlobImage
from zope.component.hooks import setSite

DEFAULT_OPTIONS = {
    "quality": {
        "default": 85,
        "type": int,
        "help": "WebP quality (0–100). Default: 85.",
    },
    "dry-run": {
        "default": False,
        "action": "store_true",
        "help": "Simulate conversion; do not write any data.",
    },
    "site-id": {
        "default": "Plone",
        "type": str,
        "help": "Plone site ID. Default: 'Plone'.",
    },
    "no-pack": {
        "default": False,
        "action": "store_true",
        "help": "Skip ZODB packing after conversion.",
    },
    "commit-every": {
        "default": 100,
        "type": int,
        "help": "Commit transaction every N processed objects. Default: 100.",
    },
}

PORTAL_TYPES = ["Image", "News Item", "Event", "File", "Document"]


def pack_database(logger: logging.Logger, portal: PloneSite) -> None:
    """Pack the ZODB database."""
    try:
        conn = portal._p_jar
        db = conn.db()
        logger.info("Packing ZODB...")
        db.pack()
        logger.info("ZODB pack completed.")
    except Exception as exc:
        logger.error("ZODB pack failed: %s", exc)


def progress_bar(current: int, total: int, start_time: float, length: int = 30) -> str:
    """Render terminal progress bar."""
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


def convert_blob_to_webp(
    blob_data: bytes, config: Dict[str, Any], logger: logging.Logger
) -> Optional[bytes]:
    """Convert a blob to WebP format."""
    try:
        img = Image.open(BytesIO(blob_data))
        fmt = (img.format or "").upper()

        if fmt == "GIF":
            if getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1:
                frames = []
                durations = []

                for frame in ImageSequence.Iterator(img):
                    fr = frame.convert("RGBA")
                    frames.append(fr)

                    d = frame.info.get("duration")
                    if d is None:
                        d = img.info.get("duration", 100)
                    durations.append(d)

                loop = img.info.get("loop", 0)

                out = BytesIO()
                frames[0].save(
                    out,
                    "WEBP",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=loop,
                    quality=config["quality"],
                    method=6,
                    lossless=False,
                )
                return out.getvalue()

            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")

            out = BytesIO()
            img.save(out, "WEBP", quality=config["quality"], method=6, lossless=False)
            return out.getvalue()

        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            logger.info("PNG transparency detected; converting with alpha channel")
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        out = BytesIO()
        img.save(out, "WEBP", quality=config["quality"], method=6, lossless=False)
        return out.getvalue()

    except Exception as exc:
        logger.error("WebP conversion failed: %s", exc)
        return None


def process_object(obj: Any, config: Dict[str, Any], logger: logging.Logger) -> bool:
    """Process a single Plone content object."""
    fields = ["image", "event_image", "lead_image"]
    changed = False

    for field in fields:
        field_value = getattr(obj, field, None)
        if not field_value or not getattr(field_value, "data", None):
            continue

        content_type = (getattr(field_value, "contentType", "") or "").lower()

        if content_type == "image/webp":
            logger.info("Skip (already WebP): %s", obj.absolute_url())
            continue

        webp_data = convert_blob_to_webp(field_value.data, config, logger)
        if not webp_data:
            logger.warning("Failed to convert %s", obj.absolute_url())
            continue

        base = (field_value.filename or "image").rsplit(".", 1)[0]
        new_filename = f"{base}.webp"

        logger.info(
            "Convert %s -> %s (quality=%s dry_run=%s)",
            obj.absolute_url(),
            new_filename,
            config["quality"],
            config["dry_run"],
        )

        if not config["dry_run"]:
            new_img = NamedBlobImage(
                data=webp_data,
                filename=new_filename,
                contentType="image/webp",
            )
            setattr(obj, field, new_img)
            changed = True

    if changed and not config["dry_run"]:
        try:
            obj.reindexObject()
        except ConflictError:
            transaction.abort()
            logger.error("ConflictError reindexing %s", obj.absolute_url())
        except Exception as exc:
            logger.debug("Reindex failed (%s): %s", obj.absolute_url(), exc)

    return changed


def convert_all_images(config: Dict[str, Any], logger: logging.Logger) -> None:
    """Walk catalog, convert images, batch commit."""
    portal = api.portal.get()
    catalog = api.portal.get_tool("portal_catalog")
    brains = catalog.unrestrictedSearchResults(portal_type=PORTAL_TYPES)

    total = len(brains)
    if total == 0:
        logger.info("No relevant objects found.")
        return

    logger.info("--------------------------------------------------")
    logger.info("Starting WebP conversion")
    logger.info("Config: %s", config)
    logger.info("Total objects: %s", total)
    logger.info("--------------------------------------------------")

    processed = skipped = failed = 0
    start_time = time.time()

    for idx, brain in enumerate(brains, 1):
        if idx == 1 or idx == total or idx % 50 == 0:
            logger.info(progress_bar(idx, total, start_time))

        try:
            obj = brain._unrestrictedGetObject()
        except ConflictError:
            failed += 1
            transaction.abort()
            logger.error("ConflictError loading %s", brain.getPath())
            continue
        except Exception as exc:
            failed += 1
            logger.error("Failed to load %s: %s", brain.getPath(), exc)
            continue

        try:
            changed = process_object(obj, config, logger)
        except ConflictError:
            failed += 1
            transaction.abort()
            logger.error("ConflictError processing %s", brain.getPath())
            continue
        except Exception as exc:
            failed += 1
            logger.error("Failed to process %s: %s", brain.getPath(), exc)
            continue

        if changed:
            processed += 1
        else:
            skipped += 1

        if idx % config["commit_every"] == 0 and not config["dry_run"]:
            transaction.commit()
            portal._p_jar.cacheMinimize()
            gc.collect()
            logger.info("Committed at object %s", idx)

    sys.stdout.write("\n")
    sys.stdout.flush()

    if not config["dry_run"]:
        transaction.commit()
        portal._p_jar.cacheMinimize()
        gc.collect()

    logger.info("--------------------------------------------------")
    logger.info(
        "DONE - converted=%s  skipped=%s  failed=%s",
        processed,
        skipped,
        failed,
    )
    logger.info("--------------------------------------------------")

    if not config["dry_run"] and not config["no_pack"]:
        pack_database(logger, portal)


def get_config() -> Dict[str, Any]:
    parser = ArgumentParser()

    for key, opts in DEFAULT_OPTIONS.items():
        parser.add_argument(f"--{key}", dest=key.replace("-", "_"), **opts)

    args, _unknown = parser.parse_known_args()

    return {
        "quality": args.quality,
        "dry_run": args.dry_run,
        "site_id": args.site_id,
        "no_pack": args.no_pack,
        "commit_every": args.commit_every,
    }


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s  %(message)s",
        handlers=[logging.StreamHandler()],
        force=True,
    )
    return logging.getLogger(__name__)


def main(app: Any) -> None:
    logger = setup_logging()
    config = get_config()

    site = app[config["site_id"]]
    setSite(site)

    logger.info("Using site: /%s", config["site_id"])
    convert_all_images(config, logger)


if __name__ == "__main__":
    if "app" not in globals():
        sys.exit(1)
    main(app)
