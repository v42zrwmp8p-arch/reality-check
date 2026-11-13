"""The same analytical functions serve the app, batch results and a notebook."""
import pandas as pd
from analysis_core import compare_prices, period_metrics, horizon_table, check_price_target


def analyse_case(row, asset, benchmark, benchmark_symbol):
    prices = compare_prices(asset["Adj Close"], benchmark["Adj Close"], row["publication_date"])
    entry, last = prices.index[0], prices.index[-1]
    if entry > pd.Timestamp(row["publication_date"]) + pd.Timedelta(days=7):
        raise ValueError("The available history starts too late to represent entry after this video.")
    target, basis = None, "No numeric price target in the supplied information"
    if row.get("target_usd") is not None:
        target = float(row["target_usd"])
        basis = row.get("target_basis") or "Price target entered by the user"
    elif row["asset_type"] == "Crypto" and row.get("projection") == "10x":
        target = float(asset.loc[entry, "Close"]) * 10
        basis = "Evaluation convention: 10 times the entry close; original reference price unspecified"
    target_check = check_price_target(asset, entry, last, target, basis, row.get("deadline"))
    summary = {
        "asset": row["asset"], "symbol": row["symbol"], "asset_type": row["asset_type"],
        "case_id": row.get("case_id", "manual"), "publication_date": row["publication_date"],
        "creator": row.get("creator", ""), "projection": row.get("projection", ""),
        "creator_time_frame": row.get("time_frame", "Not specified"), "video_url": row.get("video_url", ""),
        "entry_date": str(entry.date()), "latest_close_date": str(last.date()),
        "benchmark_symbol": benchmark_symbol, "observations": len(prices),
        "entry_close_usd": float(asset.loc[entry, "Close"]),
        "latest_close_usd": float(asset.loc[last, "Close"]),
        "price_target": target_check, **period_metrics(prices),
    }
    return summary, horizon_table(prices), 100 * prices / prices.iloc[0]
