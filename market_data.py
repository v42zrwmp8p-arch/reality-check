"""Read saved observations or request new daily USD histories with yfinance."""
from pathlib import Path
from math import isfinite
import re
import pandas as pd
from analysis_core import validated_split_review

ROOT = Path(__file__).resolve().parent
IMPORT_VERSION = "2026-11-14.14"
CRYPTO_SYMBOLS = {"HERO": "HERO10778-USD", "KDA": "KDA-USD", "MTV": "MTV-USD"}


def load_examples(path=None):
    path = Path(path) if path else ROOT / "predictions.csv"
    data = pd.read_csv(path, keep_default_na=False)
    required = {"creator", "publication_date", "asset", "symbol", "asset_type", "projection", "time_frame", "video_url"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError("Missing table columns: " + ", ".join(sorted(missing)))
    records = []
    for _, series in data.iterrows():
        row = series.to_dict()
        date = pd.to_datetime(row["publication_date"], errors="raise")
        row["publication_date"] = str(date.date())
        if row["asset_type"] not in {"Equity", "ETF", "Crypto"}:
            raise ValueError("Asset type must be Equity, ETF or Crypto.")
        for field in ["target_usd", "target_value", "reference_price", "horizon_value"]:
            row[field] = float(row[field]) if row.get(field) not in (None, "") else None
            if row[field] is not None and (not isfinite(row[field]) or row[field] <= 0):
                raise ValueError(f"{field} must be a positive finite number or blank.")
        if not row.get("case_id"):
            video = row["video_url"].split("?")[0].rstrip("/").split("/")[-1]
            row["case_id"] = video + "-" + row["symbol"].replace(" ", "").replace("/", "-")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.^-]{0,160}", str(row["case_id"])):
            raise ValueError("Case IDs may contain letters, numbers, dots, underscores and hyphens, without spaces or slashes.")
        for field in ["followers", "video_views"]:
            if row.get(field) not in (None, ""):
                value = float(row[field])
                if not pd.notna(value) or value < 0 or value == float("inf"):
                    raise ValueError("Followers and video views must be nonnegative numbers or blank.")
                row[field] = int(value)
        row["curated"] = True
        row["reviewed_splits"] = validated_split_review(row.get("reviewed_splits"))
        records.append(row)
    if len({r["case_id"] for r in records}) != len(records):
        raise ValueError("Two rows have the same case ID. Use a distinct ID for each video and asset.")
    return records


def provider_symbol(symbol, asset_type):
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.=_^-]{0,39}", symbol):
        raise ValueError("Enter a valid Yahoo Finance ticker, such as AAPL or KDA-USD.")
    if asset_type == "Crypto":
        return CRYPTO_SYMBOLS.get(symbol, symbol if "-" in symbol else symbol + "-USD")
    return symbol


def comparison_symbol(symbol, asset_type):
    """Compare Bitcoin with SPY, and other crypto with Bitcoin."""
    return comparison_symbols(symbol, asset_type)[0]


def comparison_symbols(symbol, asset_type):
    """Other crypto has both a crypto reference and a broad equity reference."""
    symbol = provider_symbol(symbol, asset_type)
    return ["BTC-USD", "SPY"] if asset_type == "Crypto" and symbol != "BTC-USD" else ["SPY"]


def saved_history(symbol, publication_date):
    path = ROOT / "prices" / f"{symbol}.csv"
    if not path.exists():
        return None
    frame = pd.read_csv(path, index_col="Date", parse_dates=True).sort_index()
    usable = frame.loc[frame.index > pd.Timestamp(publication_date), "Adj Close"].dropna()
    if len(usable) < 2 or usable.index[0] > pd.Timestamp(publication_date) + pd.Timedelta(days=7):
        return None
    return frame


def download_history(symbol, publication_date, end_date):
    import yfinance as yf
    yf.set_tz_cache_location(str(ROOT / ".market_cache"))
    frame = yf.download(symbol, start=publication_date, end=end_date, interval="1d",
                        auto_adjust=False, actions=True, threads=False, progress=False,
                        multi_level_index=False, keepna=True, timeout=15)
    if frame is None or frame.empty:
        raise ValueError(f"No daily prices returned for {symbol}. Check the ticker and date.")
    metadata = yf.Ticker(symbol).get_history_metadata()
    currency = metadata.get("currency") if metadata else None
    if currency != "USD":
        raise ValueError(f"This first version compares USD listings. Currency for {symbol}: {currency or 'not verified'}. Choose a USD listing or ADR.")
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    frame.index.name = "Date"
    if "Adj Close" not in frame:
        raise ValueError("Adjusted closing prices are missing; comparable returns cannot be calculated.")
    return frame, metadata.get("longName") or metadata.get("shortName") or symbol


def get_case_histories(row, force_live=False, fetch=download_history):
    """Shared data path for the app, batch analysis and a future report notebook."""
    supplied = row.get("provider_symbols") or row["symbol"]
    symbol = provider_symbol(supplied.split("|")[0], row["asset_type"])
    benchmark_symbol = comparison_symbol(symbol, row["asset_type"])
    if not force_live:
        asset = saved_history(symbol, row["publication_date"])
        benchmark = saved_history(benchmark_symbol, row["publication_date"])
        if asset is not None and benchmark is not None:
            return asset, benchmark, benchmark_symbol, "Saved data snapshot"
    end = pd.Timestamp.now(tz="UTC").date().isoformat()
    asset, _ = fetch(symbol, row["publication_date"], end)
    benchmark, _ = fetch(benchmark_symbol, row["publication_date"], end)
    return asset, benchmark, benchmark_symbol, "New Yahoo Finance download"


def get_comparison_histories(row, force_live=False, fetch=download_history):
    """Load the asset and each requested comparison independently."""
    supplied = row.get("provider_symbols") or row["symbol"]
    symbol = provider_symbol(supplied.split("|")[0], row["asset_type"])
    requested = comparison_symbols(symbol, row["asset_type"])
    end = pd.Timestamp.now(tz="UTC").date().isoformat()
    used_live = False

    def read(ticker):
        nonlocal used_live
        frame = None if force_live else saved_history(ticker, row["publication_date"])
        if frame is None:
            frame, _ = fetch(ticker, row["publication_date"], end)
            used_live = True
        return frame

    asset = read(symbol)
    benchmarks, unavailable = {}, []
    for ticker in requested:
        try:
            benchmarks[ticker] = read(ticker)
        except Exception:
            unavailable.append(ticker)
    if not benchmarks:
        raise ValueError("Comparison prices are unavailable. Please try again later.")
    return {"asset": asset, "benchmarks": benchmarks, "requested": requested,
            "unavailable": unavailable,
            "source": "New Yahoo Finance download" if used_live else "Saved data snapshot"}
