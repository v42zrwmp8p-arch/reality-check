"""Shared calculations for the examples, a future notebook and the website."""
import pandas as pd
from math import isfinite, isclose
from datetime import date
import json

IMPORT_VERSION = "2026-11-15.9"


def validated_split_review(value):
    """Explicit reviewed event dates/ratios, never an automatic price adjustment."""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError("Reviewed split events must be valid JSON.") from None
    if not isinstance(value, dict) or not 1 <= len(value) <= 10:
        raise ValueError("Reviewed split events need dates and positive ratios.")
    result = {}
    for day, ratio in value.items():
        try:
            day = date.fromisoformat(day).isoformat()
        except (TypeError, ValueError):
            raise ValueError("Use valid dates for reviewed split events.") from None
        if isinstance(ratio, bool):
            raise ValueError("Use numeric reviewed split ratios.")
        result[day] = positive_number(ratio, "Reviewed split ratio")
    return result


def positive_number(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a positive number.")
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a positive finite number.")
    return number


def resolve_target(row, entry_price):
    """Resolve an explicit price or multiple; never infer a target from prose."""
    legacy = row.get("target_usd")
    kind = row.get("target_type") or ("price" if legacy not in (None, "") else "none")
    result = {"target_type": kind, "target_value": None, "target_usd": None,
              "reference_type": None, "reference_price": None,
              "basis": "No numeric price target specified"}
    if kind == "none":
        return result
    value = row.get("target_value")
    if kind == "price":
        value = positive_number(value if value not in (None, "") else legacy, "Target price")
        result.update(target_value=value, target_usd=value,
                      basis=row.get("target_basis") or "Explicit USD price target")
        return result
    if kind != "multiple":
        raise ValueError("Target type must be none, price or multiple.")
    multiple = positive_number(value, "Target multiple")
    if multiple <= 1:
        raise ValueError("An upside price multiple must be greater than 1, for example 2 or 10.")
    reference_type = row.get("reference_type") or "entry"
    if reference_type == "entry":
        reference = positive_number(entry_price, "Entry price")
        basis = f"{multiple:g} times the simulated entry close"
    elif reference_type == "creator":
        reference = positive_number(row.get("reference_price"), "Creator reference price")
        basis = f"{multiple:g} times the creator's stated USD {reference:g} reference"
    else:
        raise ValueError("Reference type must be entry or creator.")
    target = positive_number(reference * multiple, "Calculated target price")
    result.update(target_value=multiple, target_usd=target, reference_type=reference_type,
                  reference_price=reference, basis=row.get("target_basis") or basis)
    return result


def resolve_deadline(row):
    """A stated date takes precedence over a structured duration after publication."""
    value = row.get("deadline")
    if value not in (None, ""):
        try:
            deadline = pd.Timestamp(value).normalize().tz_localize(None)
        except (TypeError, ValueError):
            raise ValueError("Use a valid forecast deadline date.")
        if pd.isna(deadline):
            raise ValueError("Use a valid forecast deadline date.")
        basis = row.get("deadline_basis") or "Specified end date"
    elif row.get("horizon_value") not in (None, ""):
        amount = positive_number(row["horizon_value"], "Time-frame length")
        unit = str(row.get("horizon_unit", "")).strip().lower().rstrip("s")
        if not amount.is_integer() or unit not in {"day", "week", "month", "year"}:
            raise ValueError("A time frame needs a whole number of days, weeks, months or years.")
        deadline = pd.Timestamp(row["publication_date"]) + pd.DateOffset(**{unit + "s": int(amount)})
        basis = f"Derived from {int(amount)} {unit}(s) after publication"
    else:
        return None, "No precise deadline supplied"
    if deadline < pd.Timestamp(row["publication_date"]):
        raise ValueError("The forecast deadline must be on or after publication.")
    return str(deadline.date()), basis


def deadline_performance(prices, deadline, basis="Specified end date"):
    result = {"deadline": deadline, "basis": basis, "status": "not_specified",
              "observation_date": None, "metrics": None}
    if deadline is None:
        return result
    end = pd.Timestamp(deadline)
    if end < prices.index[0]:
        result["status"] = "before_entry"
    elif end > prices.index[-1]:
        result["status"] = "not_covered"
    else:
        sample = prices.loc[:end]
        result.update(status="elapsed", observation_date=str(sample.index[-1].date()),
                      metrics=period_metrics(sample))
    return result


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


def check_price_target(frame, entry_date, last_date, target_usd, basis, deadline=None, reviewed_splits=None):
    """Check a nominal USD target separately from dividend-adjusted returns."""
    deadline = pd.Timestamp(deadline) if deadline else None
    result = {"target_usd": target_usd, "basis": basis,
              "close_comparison_version": 1,
              "creator_deadline": None if deadline is None else str(deadline.date())}
    if target_usd is None:
        result["status"] = "No numeric price target specified"
        return result
    target_usd = positive_number(target_usd, "Target price")
    result["target_usd"] = target_usd
    full_window = frame.loc[entry_date:last_date]
    end = min(pd.Timestamp(last_date), deadline) if deadline is not None else last_date
    window = frame.loc[entry_date:end]
    if window.empty:
        result["status"] = "Deadline precedes the simulated entry"
        return result
    observed = {}
    if "Stock Splits" in full_window:
        observed = {str(pd.Timestamp(day).date()): float(value) for day, value in full_window["Stock Splits"].dropna().items() if value != 0}
    review = validated_split_review(reviewed_splits)
    if observed or review:
        matches = (review is not None and observed.keys() == review.keys()
                   and all(isclose(value, review[day], rel_tol=1e-9) for day, value in observed.items()))
        if not matches:
            result["status"] = "Manual split adjustment required before target evaluation"
            return result
        result["split_adjustment_reviewed"] = True
    close = window.iloc[-1]["Close"]
    if pd.notna(close) and isfinite(float(close)) and float(close) > 0:
        close = float(close)
        result["close_comparison"] = {
            "date": str(window.index[-1].date()), "close_usd": close,
            "difference_usd": close - target_usd,
            "difference_pct": 100 * (close / target_usd - 1),
            "period": "deadline" if deadline is not None and deadline <= pd.Timestamp(last_date) else "latest",
        }
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
