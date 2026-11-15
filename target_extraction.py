"""Conservative recovery of an explicit future multiple missed by the model."""
from copy import deepcopy
import re

from asset_resolution import ASSETS, known_asset

IMPORT_VERSION = "2026-11-15.7"
WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def recover_visual_tables(rows, text, transcript=""):
    """Recover explicit ticker / NOW $price / year $target stock-pick slides.

    A narrow literal-text fallback, with no ticker list and no image inference.
    Conflicting readings are left for review. A year never becomes an invented
    day, and a dollar sign alone does not confirm USD for a newly recovered pick.
    """
    if not re.search(r"(?:top|best).{0,80}stocks?", text, re.I | re.S):
        return rows
    negation = r"\b(?:hypothetical|historical|backtest|avoid|sell|(?:not|never|don't|do\s+not|shouldn't)\s+(?:to\s+)?buy)\b"
    if re.search(negation, transcript + " " + text[:500], re.I):
        return rows
    blocks = re.split(r"\[(\d{2}:\d{2}|Photo \d+)\]\s*", text)
    found = {}
    for index in range(1, len(blocks) - 1, 2):
        stamp, body = blocks[index:index + 2]
        if re.search(negation, body, re.I):
            continue
        full_body = body
        if "[Highlighted text]\n" in body:
            body = body.split("[Highlighted text]\n", 1)[1].split("[Other text]", 1)[0]
        symbols = set(re.findall(r"(?m)^\s*([A-Z]{1,6})\.?\s*$", body))
        symbols -= {"NOW", "USD", "TOP", "ETF", "BUY", "SELL", "YTD", "ALL", "THE"}
        if not symbols:
            other = full_body.split("[Other text]", 1)[-1]
            symbols = set(re.findall(r"(?m)^\s*([A-Z]{2,6})\.?\s*$", other))
            symbols -= {"NOW", "USD", "TOP", "ETF", "BUY", "SELL", "YTD", "ALL", "THE"}
        current = {float(value) for value in re.findall(
            r"\bNOW[^\n$\d]{0,5}\$\s*(\d+(?:\.\d+)?)", full_body, re.I)}
        targets = {(year, float(value)) for year, value in re.findall(
            r"(?m)^\s*(20\d{2})\s*[:;-]?[^\n$]{0,6}\$\s*(\d+(?:\.\d+)?)\s*$", full_body)}
        if len(symbols) != 1 or len(current) != 1 or len(targets) != 1:
            continue
        symbol = next(iter(symbols))
        year, target = next(iter(targets))
        reference = next(iter(current))
        if not 0 < reference < target:
            continue
        found.setdefault(symbol, []).append((reference, year, target, stamp, body))
    result = deepcopy(rows)
    for symbol, sightings in found.items():
        if len({item[:3] for item in sightings}) != 1:
            continue
        reference, year, target, stamp, body = sightings[0]
        identity = known_asset(symbol, "Equity") or {"asset": symbol, "symbol": symbol, "asset_type": "Equity"}
        canonical = identity["symbol"]
        matches = [row for row in result if row.get("symbol") in {symbol, canonical}
                   or str(row.get("asset") or "").strip().upper() == symbol
                   or (known_asset(row.get("asset"), "Equity") or {}).get("symbol") == canonical
                   or (len(symbol) > 1 and re.search(
            r"\b" + re.escape(symbol) + r"\b", str(row.get("evidence") or "")))]
        if not matches:
            matches = [{**identity, "claim": f"Shown with a ${target:g} price target for {year}.",
                        "target_type": "none", "currency": None, "deadline": None,
                        "horizon_value": None, "horizon_unit": None}]
            result.extend(matches)
        for row in matches:
            if not row.get("symbol"):
                row["symbol"] = canonical
            if row.get("target_type") in (None, "none"):
                row.update(target_type="price", target_value=target, target_approximate=False,
                           reference_price=reference)
            if not row.get("time_frame") and not row.get("deadline") and not row.get("horizon_value"):
                row["time_frame"] = year
            if not row.get("evidence"):
                row.update(evidence=" ".join(body.split()[-20:]), evidence_time=stamp)
    return result
MULTIPLE = re.compile(
    r"\b(?:(?P<qualifier>nearly|almost|about|around|roughly|approximately|up\s+to)\s+(?:an?\s+)?)?"
    r"(?P<value>\d+(?:\.\d+)?|two|three|four|five|six|seven|eight|nine|ten)\s*"
    r"(?:x\b|×(?!\w)|-?fold\b|times\b)", re.I)


def _names(row):
    names = {str(row.get("asset") or ""), str(row.get("symbol") or "").removesuffix("-USD")}
    for _, symbol, _, aliases in ASSETS:
        if row.get("symbol") == symbol:
            names.update(aliases)
    return [name for name in names if len(name) >= 2]


def recover_multiple(rows, transcript, screen_text=""):
    """Only one named asset and one supported future multiple; no scenario guessing."""
    result = deepcopy(rows)
    if len(result) != 1:
        return result
    row = result[0]
    if row.get("target_type") not in {None, "none", "multiple"}:
        return result
    text = " ".join(re.sub(r"\[\d+:\d+\]\s*", "", transcript).split())
    candidates = []
    for match in MULTIPLE.finditer(text):
        raw = match["value"].lower()
        value = float(WORDS[raw]) if raw in WORDS else float(raw)
        if value <= 1:
            continue
        before = text[max(0, match.start() - 350):match.start()]
        lead = re.split(r"[.!?]\s+", before)[-1]
        after = text[match.end():match.end() + 60]
        if not any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", lead, re.I) for name in _names(row)):
            continue
        if not re.search(r"\b(?:could|may|might|can|will|would)\b.{0,160}\b(?:rise|reach|rally|run|gain|grow|increase|surge|up|be|return)\b", lead, re.I):
            continue
        if re.search(r"\b(?:not|never|won't|cannot|can't|unlikely|impossible|for example|imagine|suppose|hypothetical|fictional)\b", lead, re.I):
            continue
        if re.match(r"\s*(?:(?:its|the|forward|trailing|annual|current)\s+)*(?:earnings|sales|revenue|ebitda|leverage|leveraged|etf|p/e)\b", after, re.I):
            continue
        if re.search(r"\b(?:if you (?:had )?bought|if (?:we|I) (?:had )?bought|would have|could have)\b", lead, re.I):
            continue
        if re.search(r"\b(?:previously|already|historically)\b", lead[-90:], re.I):
            continue
        tail = re.split(r"(?<=[.!?])\s+", text[match.end():])[0]
        context = (lead + match[0] + tail).strip()
        candidates.append((value, bool(match["qualifier"]), context, match.start()))
    if len(candidates) != 1:
        return result
    value, approximate, context, position = candidates[0]
    existing = row.get("target_value")
    if row.get("target_type") == "multiple":
        try:
            if float(existing) != value:
                return result
        except (TypeError, ValueError):
            return result
    else:
        row.update(target_type="multiple", target_value=value, target_recovered=True)
    if row.get("reference_price") is None:
        # A stated current price may anchor the same named forecast. Past highs
        # without current-price wording are not used as a reference.
        prices = list(re.finditer(r"\b(?:trades?|trading|current price)\b[^.!?]{0,110}?\$\s*(\d[\d,]*(?:\.\d+)?)", text[:position], re.I))
        if prices and position - prices[-1].end() < 500:
            row["reference_price"] = float(prices[-1][1].replace(",", ""))
            row["currency"] = "USD" if re.search(r"\bUSD\b", transcript + " " + screen_text) else None
    row["target_approximate"] = bool(row.get("target_approximate")) or approximate
    # Retain the actual conditional wording rather than upgrading it to a promise.
    previous_claim = str(row.get("claim") or "").strip()
    row["claim"] = context
    if previous_claim and previous_claim.casefold().rstrip(".") not in context.casefold():
        row["claim"] += " " + previous_claim[0].upper() + previous_claim[1:].rstrip(".") + "."
    row["evidence"] = " ".join(context.split()[-20:])
    return result
