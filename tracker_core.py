"""Small, validated prediction records; no media, transcripts or account data."""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

from analysis_core import positive_number, resolve_deadline, resolve_target, validated_split_review
from case_analysis import analyse_comparisons, comparison_dates
from market_data import provider_symbol, history_archive

IMPORT_VERSION = "2026-11-15.1"
SCHEMA_VERSION = 1
MAX_ITEMS = 100
MAX_BYTES = 512 * 1024
TEXT_FIELDS = {"asset": 160, "creator": 100, "projection": 2000, "time_frame": 300}


def _text(value, limit):
    if not isinstance(value, str):
        raise ValueError("Tracker text fields must contain text.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"A tracker text field exceeds {limit} characters.")
    return value


def prediction_record(row):
    """Whitelist and validate facts independently of market-data availability."""
    if not isinstance(row, dict):
        raise ValueError("This prediction could not be read.")
    kind = row.get("asset_type")
    if kind not in {"Equity", "ETF", "Crypto"}:
        raise ValueError("Choose Equity, ETF or Crypto before tracking.")
    symbol = provider_symbol(str(row.get("symbol") or ""), kind)
    try:
        published = date.fromisoformat(str(row.get("publication_date")))
    except (TypeError, ValueError):
        raise ValueError("Enter a valid publication date before tracking.") from None
    if published > date.today():
        raise ValueError("The publication date cannot be in the future.")
    result = {name: _text(row.get(name) or "", limit) for name, limit in TEXT_FIELDS.items()}
    result["asset"] = result["asset"] or symbol
    result["target_basis"] = _text(row.get("target_basis") or "", 400)
    result["deadline_basis"] = _text(row.get("deadline_basis") or "", 400)
    result["reviewed_splits"] = validated_split_review(row.get("reviewed_splits"))
    if history_archive(row):
        result["history_archive"] = row["history_archive"]
    result["time_frame"] = result["time_frame"] or "Not specified"
    raw_url = _text(row.get("video_url") or "", 1000)
    if raw_url:
        try:
            parsed = urlsplit(raw_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port:
                raise ValueError
            # Tracking parameters are unnecessary for the source reference.
            raw_url = urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))
        except ValueError:
            raise ValueError("Use an HTTPS source link without login details.") from None
    target_type = row.get("target_type") or ("price" if row.get("target_usd") not in (None, "") else "none")
    result.update(symbol=symbol, asset_type=kind, publication_date=published.isoformat(),
                  video_url=raw_url, target_type=target_type, target_value=None,
                  target_approximate=False, reference_type=None, reference_price=None,
                  deadline=None, horizon_value=None, horizon_unit=None,
                  source_kind=row.get("source_kind") if row.get("source_kind") in {"photo", "video", "article", "post"} else "video")
    if target_type != "none":
        value = row.get("target_value") if row.get("target_value") not in (None, "") else row.get("target_usd")
        if isinstance(value, bool):
            raise ValueError("Enter a numeric target value.")
        result["target_value"] = positive_number(value, "Target value")
        result["target_approximate"] = row.get("target_approximate") is True
        if target_type == "multiple":
            result["reference_type"] = row.get("reference_type") or "entry"
            if result["reference_type"] == "creator":
                if isinstance(row.get("reference_price"), bool):
                    raise ValueError("Enter a numeric reference price.")
                result["reference_price"] = positive_number(row.get("reference_price"), "Creator reference price")
    if row.get("deadline") not in (None, ""):
        try:
            result["deadline"] = date.fromisoformat(str(row["deadline"])).isoformat()
        except (TypeError, ValueError):
            raise ValueError("Enter a valid forecast deadline.") from None
    elif row.get("horizon_value") not in (None, ""):
        if isinstance(row["horizon_value"], bool):
            raise ValueError("Enter a numeric time-frame length.")
        amount = positive_number(row["horizon_value"], "Time-frame length")
        if amount > 36500:
            raise ValueError("The time frame is too long for this tracker.")
        result.update(horizon_value=amount, horizon_unit=str(row.get("horizon_unit") or ""))
    resolve_target(result, 1.0)
    try:
        resolve_deadline(result)
    except (OverflowError, pd.errors.OutOfBoundsDatetime):
        raise ValueError("The forecast deadline is outside the supported range.") from None
    # An edit to a source's target updates its existing entry. Different posts
    # and assets stay distinct; manual entries also use creator and claim.
    identity = [raw_url, symbol, kind] if raw_url else [symbol, kind, published.isoformat(), result["creator"], result["projection"]]
    tracker_id = sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]
    result.update(tracker_id=tracker_id, case_id="tracked-" + tracker_id, curated=False)
    stamp = row.get("saved_at")
    try:
        parsed_stamp = datetime.fromisoformat(str(stamp))
        if parsed_stamp.tzinfo is None:
            raise ValueError
        stamp = parsed_stamp.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["saved_at"] = stamp
    return result


def tracker_records(value):
    """Validate the whole list before accepting an upload/browser snapshot."""
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError(f"A tracker can contain up to {MAX_ITEMS} predictions.")
    records = {}
    for item in value:
        record = prediction_record(item)
        records[record["tracker_id"]] = record
    return list(records.values())


def tracker_document(records):
    return {"schema_version": SCHEMA_VERSION, "items": tracker_records(records)}


def read_tracker(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError("Choose a tracker JSON file smaller than 512 KB.")
    try:
        document = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("This is not a readable tracker JSON file.") from None
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Choose a Reality Check tracker backup.")
    return tracker_records(document.get("items"))


def forecast_status(row, today=None):
    today = today or date.today()
    deadline, _ = resolve_deadline(row)
    if not deadline:
        return "Tracking", row.get("time_frame") or "No deadline"
    remaining = (date.fromisoformat(deadline) - today).days
    if remaining > 0:
        return "Tracking", f"{remaining} day{'s' if remaining != 1 else ''} left · {deadline}"
    return "Deadline reached", deadline


def forecast_label(row):
    target = row.get("target_type")
    mark = "~" if row.get("target_approximate") else ""
    if target == "multiple":
        return f"{mark}{row['target_value']:g}×"
    if target == "price":
        value = row["target_value"]
        amount = f"{value:,.2f}".rstrip("0").rstrip(".") if value >= 1 else f"{value:.6g}"
        return f"{mark}USD {amount}"
    return row.get("projection") or "No numeric target"


def tracker_comparison(row, histories, today=None):
    """Use the existing analysis, and keep brand-new records without a return."""
    today = today or date.today()
    if date.fromisoformat(row["publication_date"]) >= today:
        return None, "Tracking starts when daily closing prices after publication are available."
    data = histories(row, force_live=True)
    if len(comparison_dates(row, data)) < 2:
        return None, "Not enough daily closing prices after publication yet. Check back later."
    return analyse_comparisons(row, data), data["source"]
