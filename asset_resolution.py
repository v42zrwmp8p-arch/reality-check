"""Small name/ticker lookup, plus conservative recovery of explicit buy-list items."""
from copy import deepcopy
from difflib import get_close_matches
import re

from market_data import provider_symbol

IMPORT_VERSION = "2026-11-14.8"

# Identifiers only: these mappings contain no video claims, targets or outcomes.
ASSETS = [
    ("Bitcoin", "BTC-USD", "Crypto", ["bitcoin", "btc", "bitcoin btc"]),
    ("Ethereum", "ETH-USD", "Crypto", ["ethereum", "ether", "eth"]),
    ("Solana", "SOL-USD", "Crypto", ["solana", "sol"]),
    ("Dogecoin", "DOGE-USD", "Crypto", ["dogecoin", "doge"]),
    ("XRP", "XRP-USD", "Crypto", ["xrp", "ripple"]),
    ("Cardano", "ADA-USD", "Crypto", ["cardano", "ada"]),
    ("Kadena", "KDA-USD", "Crypto", ["kadena", "kda"]),
    ("Metahero", "HERO10778-USD", "Crypto", ["metahero"]),
    ("MultiVAC", "MTV-USD", "Crypto", ["multivac"]),
    ("Apple", "AAPL", "Equity", ["apple", "apple inc"]),
    ("Microsoft", "MSFT", "Equity", ["microsoft", "microsoft corporation"]),
    ("NVIDIA", "NVDA", "Equity", ["nvidia", "nvidia corporation"]),
    ("Tesla", "TSLA", "Equity", ["tesla", "tesla inc"]),
    ("Amazon", "AMZN", "Equity", ["amazon", "amazon com"]),
    ("Marvell Technology", "MRVL", "Equity", ["marvell", "marvell technology", "marvell technology inc"]),
    ("Micron Technology", "MU", "Equity", ["micron", "micron technology", "micron technology inc"]),
    ("Taiwan Semiconductor", "TSM", "Equity", ["taiwan semiconductor", "taiwan semiconductor manufacturing", "taiwan semiconductor manufacturing company", "tsmc"]),
    ("Crocs", "CROX", "Equity", ["crocs", "crocs inc"]),
]


def _name(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def known_asset(name, kind=None):
    normalized = _name(name)
    for label, symbol, asset_type, aliases in ASSETS:
        if normalized in aliases + [_name(symbol)] and (kind in (None, "Unknown", asset_type)):
            return {"asset": label, "symbol": symbol, "asset_type": asset_type}
    return None


def search_candidates(name, kind):
    """Bounded best-effort Yahoo search; uncertain matches are never auto-selected."""
    import yfinance as yf
    try:
        quotes = yf.Search(name, max_results=5, news_count=0, lists_count=0,
                           include_cb=False, recommended=0,
                           enable_fuzzy_query=True, timeout=5).quotes
    except Exception:
        return []
    matches = []
    for quote in quotes:
        symbol = quote.get("symbol", "")
        quote_type = quote.get("quoteType")
        asset_type = {"CRYPTOCURRENCY": "Crypto", "EQUITY": "Equity", "ETF": "ETF"}.get(quote_type)
        if not asset_type or kind not in (None, "Unknown", asset_type):
            continue
        if asset_type == "Crypto" and not symbol.endswith("-USD"):
            continue
        if asset_type in {"Equity", "ETF"} and quote.get("exchange") not in {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "PNK", "OQB", "OQX"}:
            continue
        try:
            symbol = provider_symbol(symbol, asset_type)
        except (ValueError, AttributeError):
            continue
        label = quote.get("longname") or quote.get("shortname") or symbol
        candidate = {"asset": str(label), "symbol": symbol, "asset_type": asset_type}
        if not any(item["symbol"] == symbol for item in matches):
            matches.append(candidate)
    return matches[:5]


def spelling_suggestions(name, kind):
    normalized = _name(name)
    if len(normalized) < 5:
        return []
    aliases = {alias: {"asset": label, "symbol": symbol, "asset_type": asset_type}
               for label, symbol, asset_type, names in ASSETS
               if kind in (None, "Unknown", asset_type) for alias in names}
    result = []
    for alias in get_close_matches(normalized, aliases, n=3, cutoff=0.82):
        candidate = aliases[alias]
        if candidate not in result:
            result.append(candidate)
    return result


def complete_drafts(rows, lookup=search_candidates):
    """Fill unambiguous identifiers, offering uncertain spelling matches for review."""
    output, searches = [], 0
    for original in rows:
        row = deepcopy(original)
        kind = row.get("asset_type", "Unknown")
        match = known_asset(row.get("asset"), kind)
        if match:
            row.update(match)
        elif suggestions := spelling_suggestions(row.get("asset"), kind):
            # Similar names are suggestions, not silently corrected identities.
            row["symbol"] = None
            row["ticker_suggestions"] = suggestions
        elif row.get("symbol"):
            try:
                row["symbol"] = provider_symbol(row["symbol"], kind)
            except (ValueError, AttributeError):
                row["symbol"] = None
        if not row.get("symbol") and not row.get("ticker_suggestions") and searches < 6:
            query = str(row.get("asset") or "").strip()[:100]
            if query:
                searches += 1
                row["ticker_suggestions"] = deepcopy(lookup(query, kind))
        output.append(row)
    return output


def explicit_buy_list_candidates(transcript):
    """Recover only known name+ticker pairs introduced as items in a clear buy list.

    This deliberately does not guess assets from every company mentioned. It is
    a fallback for explicit list items, not general investment-language parsing.
    """
    text = re.sub(r"\[\d+:\d+\]\s*", "", transcript)
    intro = text[:450]
    if not re.search(r"\b(?:top|best|favou?rite)\b.{0,50}\b(?:stocks?|coins?|cryptocurrencies)\b.{0,35}\bto\s+(?:buy|own|hold)\b", intro, re.I):
        return []
    if re.search(r"\b(?:never|avoid|hypothetical|fictional|don't|do not|not recommending|shouldn't)\b", intro, re.I):
        return []
    horizon, unit, stated = None, None, None
    if re.search(r"\b(?:for\s+)?(?:the\s+)?next\s+decade\b", intro, re.I):
        horizon, unit, stated = 10, "years", "next decade"
    else:
        duration = re.search(r"\b(?:for\s+)?(?:the\s+)?next\s+(\d{1,2})\s+(years?|months?|weeks?|days?)\b", intro, re.I)
        if duration and int(duration[1]) > 0:
            horizon, unit, stated = int(duration[1]), duration[2].lower().rstrip("s") + "s", duration[0]
    rows, seen = [], set()
    pattern = r"\bticker(?:\s+symbol)?\s*[:$-]?\s*([A-Z][A-Z0-9.-]{0,14})\b"
    marker = r"\b(?:number\s+(?:one|two|three|\d+)|(?:next|first|second|third|last)\s+(?:stock|coin|pick)|we\s+have|my\s+(?:pick|choice))\b"
    for mention in re.finditer(pattern, text):
        symbol = mention[1].rstrip(".")
        # Use only the sentence introducing this ticker, not an earlier list item.
        left = text[max(0, mention.start() - 220):mention.start()]
        left = re.split(r"[.!?]", left)[-1]
        if not re.search(marker, left, re.I) or re.search(r"\b(?:not|avoid|sell|short|hypothetical)\b", left, re.I):
            continue
        for label, expected, kind, aliases in ASSETS:
            if expected != symbol or symbol in seen:
                continue
            words = " " + _name(left) + " "
            if not any(" " + alias + " " in words for alias in aliases):
                continue
            snippet = " ".join((left.strip() + " " + mention[0]).split()[-20:])
            rows.append({"asset": label, "symbol": symbol, "asset_type": kind,
                         "claim": f"Included among the creator's stocks to buy" + (f" for the {stated}." if stated else "."),
                         "evidence": snippet, "evidence_time": None,
                         "target_type": "none", "target_value": None, "reference_price": None,
                         "currency": None, "time_frame": stated, "deadline": None,
                         "horizon_value": horizon, "horizon_unit": unit})
            seen.add(symbol)
    return rows


def explicit_etf_candidates(transcript):
    """Recover literal ETF tickers in an explicit suggestion to buy/hold ETFs.

    This uses source wording, not a fixed list of funds. Holdings mentioned
    inside an ETF are not turned into separate recommendations.
    """
    text = " ".join(re.sub(r"\[\d+:\d+\]\s*", "", transcript).split())
    positive = (r"\byou\s+(?:can|could|should|may)\b.{0,80}\b(?:buy|hold|own|invest\s+in)\b.{0,35}\bETFs?\b"
                r"|\b(?:buy|hold|own)\s+these\s+ETFs?\b|\bETFs?\s+to\s+buy\b")
    if not re.search(positive, text, re.I):
        return []
    if re.search(r"\b(?:don't|do not|never|avoid|not)\s+(?:buy(?:ing)?|own(?:ing)?|hold(?:ing)?|invest(?:ing)?\s+in)\s+(?:\w+\s+){0,2}ETFs?\b", text, re.I):
        return []
    rows, seen = [], set()
    for mention in re.finditer(r"\bticker(?:\s+symbol)?\s*[:$-]?\s*([A-Z][A-Z0-9.-]{0,14})\b", text):
        symbol = mention[1].rstrip(".")
        before = text[max(0, mention.start() - 140):mention.start()]
        if re.search(r"\b(?:leveraged|inverse|short|bear)\b", before, re.I):
            continue
        directly_named = re.search(r"\bETF\s*[,;:]?\s*(?:with\s+)?$", before, re.I)
        earlier_one = rows and re.search(r"\b(?:the\s+)?one\s+before\b(?:\s+\w+){0,9}\s*$", before, re.I)
        if symbol in seen or not (directly_named or earlier_one):
            continue
        evidence = " ".join((before + mention[0]).split()[-20:])
        rows.append({"asset": symbol, "symbol": symbol, "asset_type": "ETF",
                     "claim": "Named as an ETF example in a discussion of buying ETFs.",
                     "evidence": evidence, "evidence_time": None,
                     "target_type": "none", "target_value": None, "target_approximate": False,
                     "reference_price": None, "currency": None,
                     "time_frame": "long term" if re.search(r"\blong[ -]term\b", text, re.I) else None,
                     "deadline": None, "horizon_value": None, "horizon_unit": None})
        seen.add(symbol)
    return rows
