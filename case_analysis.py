"""The same analytical functions serve the app, batch results and a notebook."""
import pandas as pd
from analysis_core import (compare_prices, period_metrics, horizon_table, check_price_target,
                           resolve_target, resolve_deadline, deadline_performance)

IMPORT_VERSION = "2026-11-15.8"


def comparison_dates(row, histories):
    """One shared date set keeps asset and benchmark returns comparable."""
    frames = [histories["asset"], *histories["benchmarks"].values()]
    if any(frame.index.has_duplicates for frame in frames):
        raise ValueError("Duplicate price dates need review.")
    common = pd.concat([frame["Adj Close"] for frame in frames], axis=1).sort_index().dropna()
    common = common.loc[common.index > pd.Timestamp(row["publication_date"])]
    if (common <= 0).any().any():
        raise ValueError("Closing prices must be positive.")
    return common.index


def analyse_comparisons(row, histories):
    """Reuse the original pairwise math for each benchmark on identical dates."""
    dates = comparison_dates(row, histories)
    if len(dates) < 2:
        raise ValueError("Need at least two positive, overlapping daily observations.")
    results = {}
    for symbol, frame in histories["benchmarks"].items():
        # Keep the full asset frame: nominal crypto targets may be reached on
        # weekends even though SPY has no closing observation on those days.
        results[symbol] = analyse_case(row, histories["asset"], frame.reindex(dates), symbol)
    primary = next(iter(results))
    summary, periods, chart = results[primary]
    for key in ("return_basis", "history_note", "terminal_status", "terminal_source"):
        if key in histories:
            summary[key] = histories[key]
    summary["requested_benchmark_symbols"] = histories["requested"]
    summary["unavailable_benchmarks"] = histories["unavailable"]
    summary["comparisons"] = {}
    for symbol, (values, table, normalized) in results.items():
        summary["comparisons"][symbol] = {
            "return_pct": values["benchmark_return_pct"], "difference_pp": values["difference_pp"],
            "deadline_result": values["deadline_result"]}
        if symbol != primary:
            periods[symbol + "_return_pct"] = table["benchmark_return_pct"].to_numpy()
            periods["difference_vs_" + symbol + "_pp"] = table["difference_pp"].to_numpy()
            chart["Benchmark_" + symbol] = normalized["Benchmark"]
    return summary, periods, chart


def analyse_case(row, asset, benchmark, benchmark_symbol):
    prices = compare_prices(asset["Adj Close"], benchmark["Adj Close"], row["publication_date"])
    entry, last = prices.index[0], prices.index[-1]
    if entry > pd.Timestamp(row["publication_date"]) + pd.Timedelta(days=7):
        raise ValueError("The available history starts too late to represent entry after this video.")
    goal = resolve_target(row, float(asset.loc[entry, "Close"]))
    deadline, deadline_basis = resolve_deadline(row)
    target_check = check_price_target(asset, entry, last, goal["target_usd"], goal["basis"], deadline, row.get("reviewed_splits"))
    target_check.update(goal)
    target_check["approximate"] = bool(row.get("target_approximate"))
    deadline_result = deadline_performance(prices, deadline, deadline_basis)
    if row.get("deadline_basis"):
        deadline_result["label"] = "Evaluation date"
        target_check["evaluation_deadline"] = target_check["creator_deadline"]
        target_check["creator_deadline"] = None
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
        "deadline_result": deadline_result,
        "price_target": target_check, **period_metrics(prices),
    }
    return summary, horizon_table(prices), 100 * prices / prices.iloc[0]
