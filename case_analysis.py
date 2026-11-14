"""The same analytical functions serve the app, batch results and a notebook."""
import pandas as pd
from analysis_core import (compare_prices, period_metrics, horizon_table, check_price_target,
                           resolve_target, resolve_deadline, deadline_performance)


def analyse_case(row, asset, benchmark, benchmark_symbol):
    prices = compare_prices(asset["Adj Close"], benchmark["Adj Close"], row["publication_date"])
    entry, last = prices.index[0], prices.index[-1]
    if entry > pd.Timestamp(row["publication_date"]) + pd.Timedelta(days=7):
        raise ValueError("The available history starts too late to represent entry after this video.")
    goal = resolve_target(row, float(asset.loc[entry, "Close"]))
    deadline, deadline_basis = resolve_deadline(row)
    target_check = check_price_target(asset, entry, last, goal["target_usd"], goal["basis"], deadline)
    target_check.update(goal)
    summary = {
        "asset": row["asset"], "symbol": row["symbol"], "asset_type": row["asset_type"],
        "case_id": row.get("case_id", "manual"), "publication_date": row["publication_date"],
        "creator": row.get("creator", ""), "projection": row.get("projection", ""),
        "creator_time_frame": row.get("time_frame", "Not specified"), "video_url": row.get("video_url", ""),
        "entry_date": str(entry.date()), "latest_close_date": str(last.date()),
        "benchmark_symbol": benchmark_symbol, "observations": len(prices),
        "entry_close_usd": float(asset.loc[entry, "Close"]),
        "latest_close_usd": float(asset.loc[last, "Close"]),
        "forecast_deadline": deadline, "deadline_basis": deadline_basis,
        "deadline_result": deadline_performance(prices, deadline, deadline_basis),
        "price_target": target_check, **period_metrics(prices),
    }
    return summary, horizon_table(prices), 100 * prices / prices.iloc[0]
