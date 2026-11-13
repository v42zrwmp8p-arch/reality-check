"""Shared calculations for the examples, a future notebook and the website."""
import pandas as pd


def compare_prices(asset, benchmark, publication_date):
    """Use observed prices on common dates, starting strictly after publication."""
    if asset.index.has_duplicates or benchmark.index.has_duplicates:
        raise ValueError("Duplicate price dates need review.")
    prices = pd.concat([asset.rename("Asset"), benchmark.rename("Benchmark")], axis=1, sort=True)
    prices = prices.sort_index().dropna()
    prices = prices.loc[prices.index > pd.Timestamp(publication_date)]
    if len(prices) < 2 or (prices <= 0).any().any():
        raise ValueError("Need at least two positive, overlapping daily observations.")
    return prices


def period_metrics(prices):
    returns = prices.iloc[-1] / prices.iloc[0] - 1
    drawdown = prices["Asset"] / prices["Asset"].cummax() - 1
    return {
        "asset_return_pct": float(100 * returns["Asset"]),
        "benchmark_return_pct": float(100 * returns["Benchmark"]),
        "difference_pp": float(100 * (returns["Asset"] - returns["Benchmark"])),
        "max_drawdown_pct": float(100 * drawdown.min()),
    }


def horizon_table(prices):
    """Cumulative returns at elapsed calendar anniversaries, then the latest close."""
    start, last = prices.index[0], prices.index[-1]
    periods = [("1 month", 1), ("3 months", 3), ("6 months", 6), ("1 year", 12)]
    periods += [(f"{years} years", 12 * years) for years in range(2, last.year - start.year + 2)]
    records = []
    for label, months in periods:
        target_date = start + pd.DateOffset(months=months)
        if target_date > last:
            continue
        sample = prices.loc[:target_date]
        records.append({"period": label, "target_date": str(target_date.date()),
                        "observation_date": str(sample.index[-1].date()), **period_metrics(sample)})
    records.append({"period": "Latest available", "target_date": str(last.date()),
                    "observation_date": str(last.date()), **period_metrics(prices)})
    return pd.DataFrame(records)


def check_price_target(frame, entry_date, last_date, target_usd, basis, deadline=None):
    """Check a nominal USD target separately from dividend-adjusted returns."""
    deadline = pd.Timestamp(deadline) if deadline else None
    result = {"target_usd": target_usd, "basis": basis,
              "creator_deadline": None if deadline is None else str(deadline.date())}
    if target_usd is None:
        result["status"] = "No numeric price target specified"
        return result
    full_window = frame.loc[entry_date:last_date]
    end = min(pd.Timestamp(last_date), deadline) if deadline is not None else last_date
    window = frame.loc[entry_date:end]
    if window.empty:
        result["status"] = "Deadline precedes the simulated entry"
        return result
    if "Stock Splits" in full_window and (full_window["Stock Splits"].fillna(0) != 0).any():
        result["status"] = "Manual split adjustment required before target evaluation"
        return result
    if window.iloc[0]["Close"] >= target_usd:
        result.update({"status": "At or above target at entry close",
                       "first_intraday_high_date": None,
                       "first_closing_price_date": str(window.index[0].date())})
        return result
    after_entry = window.loc[window.index > pd.Timestamp(entry_date)]
    high_hits = after_entry.loc[after_entry["High"] >= target_usd]
    close_hits = window.loc[window["Close"] >= target_usd]
    miss_status = "Not reached by cutoff; no creator deadline specified"
    if deadline is not None:
        miss_status = "Not reached by deadline" if deadline <= pd.Timestamp(last_date) else "Not yet reached; deadline still running"
    result.update({
        "status": "Reached by cutoff" if not high_hits.empty else miss_status,
        "first_intraday_high_date": None if high_hits.empty else str(high_hits.index[0].date()),
        "first_closing_price_date": None if close_hits.empty else str(close_hits.index[0].date()),
    })
    return result
