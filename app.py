"""Run with: python -m streamlit run app.py"""
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
import json
import pandas as pd
import streamlit as st
from import_runtime import import_flow

APP_VERSION = "2026-11-14.13"
tiktok_mode = import_flow(APP_VERSION)
from market_data import load_examples, provider_symbol, download_history, get_comparison_histories, comparison_symbols
from case_analysis import analyse_comparisons
from analysis_core import positive_number
from charts import comparison_chart
from tracker_ui import sync_tracker, storage_message, track_button, tracker_mode

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Reality Check", layout="wide", initial_sidebar_state="collapsed")
st.markdown("<style>.block-container{max-width:1120px;padding-top:2rem;padding-bottom:3rem}h1{letter-spacing:-.035em}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=3600, show_spinner=False)
def live_history(symbol, publication_date, end_date):
    return download_history(symbol, publication_date, end_date)


def histories(row, force_live=False):
    return get_comparison_histories(row, force_live, fetch=live_history)


def discard_outdated_comparisons():
    for key in ("manual_result", "tt_result"):
        stored = st.session_state.get(key)
        if not stored or not stored.get("result"):
            continue
        row = stored["row"]
        expected = comparison_symbols(row["symbol"], row["asset_type"])
        summary = stored["result"][0]
        recorded = summary.get("requested_benchmark_symbols", [summary.get("benchmark_symbol")])
        if set(recorded) != set(expected):
            st.session_state.pop(key, None)


def usd(value):
    number = f"{value:,.2f}".rstrip("0").rstrip(".") if value >= 1 else f"{value:.6g}"
    return "USD " + number


def show_recommendation(row):
    st.subheader(row["asset"])
    if not row.get("curated"):
        st.caption(f"Recommendation date: {row['publication_date']} · {row['symbol']}")
        return
    creator = row.get("creator") or "Your entry"
    date_label = "Statement" if row.get("case_type") == "context" else "Published"
    st.caption(f"{creator} · {date_label} {row['publication_date']} · {row['symbol']}")
    if row.get("case_note"):
        st.caption(row["case_note"])
    st.write(row.get("projection") or "No prediction text entered.")
    if row.get("evidence"):
        with st.expander("Source excerpt"):
            st.text(row["evidence"])
    if row.get("case_type") != "context":
        horizon = row.get("time_frame") or "Not specified"
        st.caption(f"Creator's time frame: {horizon}")
    reach = []
    for key, label in [("followers", "followers"), ("video_views", "video views")]:
        value = row.get(key)
        if value not in (None, ""):
            reach.append(f"{int(float(value)):,} {label}")
    if reach:
        st.caption(" · ".join(reach))
    link = row.get("video_url", "")
    if urlparse(link).scheme in {"http", "https"}:
        st.link_button("Source and context" if row.get("case_type") == "context" else "Original post", link)


def show_nikola():
    status = json.loads((ROOT / "nikola_status.json").read_text(encoding="utf-8"))
    st.divider()
    st.subheader("Shares cancelled")
    st.metric("Confirmed terminal share value", "$0.00")
    st.write("Nikola's existing common shares were cancelled without a distribution for those equity interests under its liquidation plan.")
    st.caption("The complete daily history from this video's date has not yet been connected. The historical chart and period returns remain unavailable.")
    st.link_button("Official FINRA notice", status["source"])


def benchmark_label(symbol):
    return "Bitcoin" if symbol == "BTC-USD" else "S&P 500 ETF (SPY)"


def show_results(row, result, source):
    summary, periods, normalized = result
    primary = summary["benchmark_symbol"]
    comparisons = summary.get("comparisons") or {primary: {
        "return_pct": summary["benchmark_return_pct"], "difference_pp": summary["difference_pp"],
        "deadline_result": summary["deadline_result"]}}
    benchmark = benchmark_label(primary)
    st.divider()
    st.subheader("What happened next")
    st.caption(f"Simulated entry: {summary['entry_date']} · Last common close: {summary['latest_close_date']} · {source}")
    for missing in summary.get("unavailable_benchmarks", []):
        st.warning(f"{benchmark_label(missing)} comparison is unavailable. Showing the available comparison.")
    window = summary["deadline_result"]
    deadline_label = window.get("label", "Forecast deadline")
    additional = {"Benchmark_" + symbol: benchmark_label(symbol) for symbol in comparisons if symbol != primary}
    st.altair_chart(comparison_chart(normalized, row["symbol"], benchmark, window, additional), width="stretch")
    if window["status"] == "elapsed":
        values = window["metrics"]
        if len(comparisons) == 1:
            st.markdown(f"**By {deadline_label.lower()} ({window['deadline']}):** "
                        f"asset **{values['asset_return_pct']:+.2f}%**, "
                        f"benchmark **{values['benchmark_return_pct']:+.2f}%**, "
                        f"difference **{values['difference_pp']:+.2f} pp**.")
        else:
            st.markdown(f"**By {deadline_label.lower()} ({window['deadline']}):** asset **{values['asset_return_pct']:+.2f}%**.")
            for symbol, comparison in comparisons.items():
                metrics = comparison["deadline_result"]["metrics"]
                st.markdown(f"{benchmark_label(symbol)}: **{metrics['benchmark_return_pct']:+.2f}%** · "
                            f"Difference: **{metrics['difference_pp']:+.2f} pp**.")
        st.caption(f"Closing observation used: {window['observation_date']}. {window['basis']}.")
    elif window["status"] == "not_covered":
        future = pd.Timestamp(window["deadline"]).date() > date.today()
        message = "The forecast horizon is still running." if future else "Update prices to check whether later observations are available."
        st.info(f"Forecast deadline: {window['deadline']}. It lies beyond the shown history. {message}")
        st.caption(window["basis"] + ". No future performance has been estimated.")
    elif window["status"] == "before_entry":
        st.info(f"Forecast deadline: {window['deadline']}. It precedes the simulated entry, so no holding-period return is available by that deadline.")
    st.markdown("**Latest available results**")
    if len(comparisons) == 1:
        metrics = [("Asset return", f"{summary['asset_return_pct']:+.2f}%"),
                   (f"{benchmark} return", f"{summary['benchmark_return_pct']:+.2f}%"),
                   ("Difference", f"{summary['difference_pp']:+.2f} pp"),
                   ("Largest fall", f"{summary['max_drawdown_pct']:.2f}%")]
        for column, (label, value) in zip(st.columns(4), metrics):
            column.metric(label, value)
    else:
        returns = [("Asset return", f"{summary['asset_return_pct']:+.2f}%")]
        returns += [(f"{benchmark_label(symbol)} return", f"{values['return_pct']:+.2f}%") for symbol, values in comparisons.items()]
        differences = [(f"Difference vs {'Bitcoin' if symbol == 'BTC-USD' else symbol}", f"{values['difference_pp']:+.2f} pp") for symbol, values in comparisons.items()]
        differences.append(("Largest fall", f"{summary['max_drawdown_pct']:.2f}%"))
        for items in (returns, differences):
            for column, (label, value) in zip(st.columns(3), items):
                column.metric(label, value)
    if "BTC-USD" in comparisons and "SPY" in comparisons:
        st.caption("Bitcoin is the crypto comparison here; SPY provides a broad equity-market comparison.")
    elif "BTC-USD" in comparisons:
        st.caption("Bitcoin is the comparison asset here; it is not a broad crypto-market index.")
    last = pd.Timestamp(summary["latest_close_date"])
    if last < pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=7):
        st.info(f"This series ends on {last:%d %b %Y}. Its subsequent performance has not been assessed.")
    st.subheader("Results over time")
    fields = ["period", "observation_date", "asset_return_pct", "benchmark_return_pct", "difference_pp"]
    names = {"period": "Period", "observation_date": "Observation date", "asset_return_pct": "Asset return (%)",
             "benchmark_return_pct": "Benchmark return (%)", "difference_pp": "Difference (pp)"}
    if len(comparisons) > 1:
        primary_short = "Bitcoin" if primary == "BTC-USD" else primary
        names.update(benchmark_return_pct=primary_short + " return (%)", difference_pp="Difference vs " + primary_short + " (pp)")
        for symbol in comparisons:
            if symbol != primary:
                fields += [symbol + "_return_pct", "difference_vs_" + symbol + "_pp"]
                names[symbol + "_return_pct"] = symbol + " return (%)"
                names["difference_vs_" + symbol + "_pp"] = "Difference vs " + symbol + " (pp)"
    display = periods[fields].rename(columns=names)
    st.dataframe(display, hide_index=True, width="stretch", column_config={
        names[field]: st.column_config.NumberColumn(format="%+.2f") for field in fields[2:]})
    st.caption("Cumulative returns from entry.")
    st.download_button("Download period results", periods.to_csv(index=False),
                       file_name=f"{row.get('case_id', 'manual')}_periods.csv", mime="text/csv")
    target = summary["price_target"]
    if target["target_usd"] is not None:
        amount = usd(target["target_usd"])
        mark = "~" if target.get("approximate") else ""
        if target["target_type"] == "multiple":
            multiple = target["target_value"]
            st.subheader(f"Target: {mark}{multiple:g}× ({amount})")
            if target["reference_type"] == "entry":
                st.caption("Reference: simulated entry price.")
        else:
            st.subheader(f"Target: {mark}{amount}")
        st.write(("Approximate level: " if target.get("approximate") else "") + target["status"])
        if target.get("creator_deadline"):
            st.caption("Creator deadline: " + target["creator_deadline"])
        if target.get("evaluation_deadline"):
            st.caption("Evaluation date: " + target["evaluation_deadline"])
        if target.get("first_intraday_high_date"):
            st.caption("First reached: " + target["first_intraday_high_date"])
        if target.get("first_closing_price_date"):
            st.caption("First close at target or above: " + target["first_closing_price_date"])


def show_method():
    with st.expander("How the comparison works"):
        st.write("The simulated purchase uses the first common closing price after publication. All chart lines start at 100 and use common observation dates.")
        st.write("Returns use adjusted USD closing prices, including vendor split and dividend adjustments. The largest fall is the maximum drawdown across those closing observations.")
        st.write("Stocks, ETFs and Bitcoin are compared with the S&P 500 ETF (SPY). Other crypto is compared with both Bitcoin and SPY. Price targets are checked separately from investment returns.")
        st.write("A price multiple uses either the simulated entry close or an explicitly supplied creator reference. For example, 2× means a 100% price gain and 10× means a 900% gain.")
        st.write("A precise covered deadline is marked in the chart; the later history remains visible. A stated duration is measured from publication.")
        st.caption("Market data: Yahoo Finance via yfinance. Original sources are linked, not hosted. Trading costs and taxes are excluded.")
        st.caption("Video imports use speech and sampled screen text. Photo imports read the images and caption. Review names, tickers and dates. Publication dates use UTC.")
        st.caption("If a post has already been analysed, the app can reuse the saved result for up to 24 hours.")
        st.caption("Edits stay private and media files are deleted after processing. Groq usage limits apply.")
        st.caption("App version: " + APP_VERSION)


def example_mode():
    st.subheader("Iconic market calls")
    try:
        examples = load_examples()
    except (ValueError, FileNotFoundError) as exc:
        st.error(str(exc))
        return
    if not examples:
        st.info("No examples have been added to the table yet.")
        return
    by_id = {row["case_id"]: row for row in examples}
    if st.session_state.get("case_selector") not in by_id:
        st.session_state.pop("case_selector", None)
    default = next((i for i, row in enumerate(examples) if row["case_id"] == "roaring-kitty-gme-20200804"), 0)
    case_id = st.selectbox("Choose a case", list(by_id), index=default,
        format_func=lambda key: f"{by_id[key].get('case_title') or (by_id[key]['asset'] + ' — ' + by_id[key]['creator'])} · {by_id[key]['publication_date']}", key="case_selector")
    row = by_id[case_id]
    show_recommendation(row)
    if row.get("case_type") == "context":
        st.info("Context case: no share-price return is calculated for this statement.")
        return
    if row["symbol"] in {"VTIQ / NKLA", "VTIQ", "NKLA", "NKLAQ"}:
        show_nikola()
        return
    track_button(lambda: row, key="curated_track")
    if st.button("Update prices", key="update_prices"):
        live_history.clear()
        st.session_state["live_case"] = case_id
    try:
        with st.spinner("Preparing the comparison…"):
            data = histories(row, st.session_state.get("live_case") == case_id)
            result = analyse_comparisons(row, data)
        show_results(row, result, data["source"])
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        st.error("The market-data request did not complete. Please try again; the saved examples remain available when their data are present.")
    if st.session_state.get("live_case") == case_id:
        if st.button("Use saved snapshot", key="use_snapshot"):
            st.session_state.pop("live_case", None)
            st.rerun()


def manual_mode():
    st.subheader("Manual Entry")
    st.caption("Enter an investment prediction yourself.")
    left, middle, right = st.columns([2, 1, 2])
    ticker = left.text_input("Yahoo Finance ticker", value="AAPL", key="manual_ticker", help="USD stocks, ETFs and crypto, for example AAPL, XLE or KDA-USD.")
    kind = middle.selectbox("Asset type", ["Equity", "Crypto", "ETF"], key="manual_type")
    published = right.date_input("Publication date", value=date(2023, 6, 26), max_value=date.today(), key="manual_date")
    value_input, reference_input, reference_type = None, None, None
    target_approximate = False
    with st.expander("Target and time frame (optional)"):
        target_label = st.selectbox("Target type", ["No target", "Price target (USD)", "Price multiple"], key="manual_target_type")
        if target_label == "Price target (USD)":
            value_input = st.text_input("Upside target price (USD)", placeholder="e.g. 142", key="manual_target_price")
        elif target_label == "Price multiple":
            value_input = st.number_input("Target multiple", min_value=1.000001, value=2.0, step=1.0, format="%g", key="manual_multiple")
            reference_label = st.selectbox("Reference price", ["Simulated entry price", "Creator reference price"], key="manual_reference_type")
            reference_type = "entry" if reference_label == "Simulated entry price" else "creator"
            if reference_type == "creator":
                reference_input = st.text_input("Creator reference price (USD)", placeholder="e.g. 106", key="manual_reference_price")
        if target_label != "No target":
            target_approximate = st.checkbox("Approximate target", key="manual_approximate")
        deadline = st.date_input("Forecast deadline (optional)", value=None, key="manual_deadline")
    with st.expander("Source (optional)"):
        creator = st.text_input("Creator", key="manual_creator")
        source_link = st.text_input("Original post link", key="manual_link")
        claim = st.text_area("Prediction", key="manual_claim")
    current_inputs = (ticker, kind, str(published), target_label, str(value_input), reference_type, str(reference_input), str(deadline), target_approximate, creator, source_link, claim)
    def checked_row():
        symbol = provider_symbol(ticker, kind)
        target_type = {"No target": "none", "Price target (USD)": "price", "Price multiple": "multiple"}[target_label]
        value = positive_number(value_input, "Target value") if target_type != "none" else None
        if target_type == "multiple" and value <= 1:
            raise ValueError("The upside multiple must be greater than 1.")
        reference = positive_number(reference_input, "Creator reference price") if reference_type == "creator" else None
        if deadline and deadline < published:
            raise ValueError("The deadline must be on or after publication.")
        return {"case_id": "manual-" + symbol, "asset": symbol, "symbol": symbol, "asset_type": kind,
                "publication_date": published.isoformat(), "creator": creator, "projection": claim, "video_url": source_link,
                "time_frame": deadline.isoformat() if deadline else "Not specified",
                "target_type": target_type, "target_value": value,
                "target_approximate": target_approximate,
                "reference_type": reference_type, "reference_price": reference,
                "deadline": deadline.isoformat() if deadline else None, "curated": False}
    a, b = st.columns(2)
    submitted = a.button("Calculate", type="primary", key="manual_calculate")
    with b:
        track_button(checked_row, key="manual_track")
    if submitted:
        st.session_state.pop("manual_result", None)
        try:
            row = checked_row()
            if row["symbol"] in {"NKLA", "NKLAQ", "VTIQ"}:
                st.session_state["manual_result"] = {"row": row, "nikola": True, "inputs": current_inputs}
            else:
                with st.spinner("Loading daily prices and calculating…"):
                    data = histories(row, force_live=True)
                    result = analyse_comparisons(row, data)
                st.session_state["manual_result"] = {"row": row, "result": result, "source": data["source"], "inputs": current_inputs}
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("The market-data request did not complete. Check the ticker or try again later.")
    stored = st.session_state.get("manual_result")
    if stored and stored.get("inputs") != current_inputs:
        st.info("Click Calculate to apply the changed inputs.")
    elif stored:
        show_recommendation(stored["row"])
        if stored.get("nikola"):
            show_nikola()
        else:
            show_results(stored["row"], stored["result"], stored["source"])


st.title("Reality Check")
st.write("See what happened after the recommendation.")
sync_tracker()
discard_outdated_comparisons()
legacy_modes = {"TikTok examples": "Case Database", "TikTok Case Database": "Case Database", "Your own case": "Manual Entry"}
if st.session_state.get("mode") in legacy_modes:
    st.session_state["mode"] = legacy_modes[st.session_state["mode"]]
mode = st.radio("Mode", ["Import TikTok", "Manual Entry", "My Tracker", "Case Database"], horizontal=True, label_visibility="collapsed", key="mode")
st.divider()
storage_message()
if mode == "Case Database":
    example_mode()
elif mode == "Manual Entry":
    manual_mode()
elif mode == "My Tracker":
    tracker_mode(histories, show_results, show_nikola, live_history.clear)
else:
    tiktok_mode(histories, show_results, show_nikola, track_button)
show_method()
