"""Run with: python -m streamlit run app.py"""
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
import json
import pandas as pd
import streamlit as st
from market_data import load_examples, provider_symbol, download_history, get_case_histories
from case_analysis import analyse_case
from analysis_core import positive_number
from charts import comparison_chart
from tiktok_ui import tiktok_mode

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Reality Check", layout="wide", initial_sidebar_state="collapsed")
st.markdown("<style>.block-container{max-width:1120px;padding-top:2rem;padding-bottom:3rem}h1{letter-spacing:-.035em}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=3600, show_spinner=False)
def live_history(symbol, publication_date, end_date):
    return download_history(symbol, publication_date, end_date)


def histories(row, force_live=False):
    return get_case_histories(row, force_live, fetch=live_history)


def show_recommendation(row):
    st.subheader(row["asset"])
    if not row.get("curated"):
        st.caption(f"Recommendation date: {row['publication_date']} · {row['symbol']}")
        return
    creator = row.get("creator") or "Your entry"
    st.caption(f"{creator} · Published {row['publication_date']} · {row['symbol']}")
    st.write(row.get("projection") or "No prediction text entered.")
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
        st.link_button("Original video", link)


def show_nikola():
    status = json.loads((ROOT / "nikola_status.json").read_text(encoding="utf-8"))
    st.divider()
    st.subheader("Shares cancelled")
    st.metric("Confirmed terminal share value", "$0.00")
    st.write("Nikola's existing common shares were cancelled without a distribution for those equity interests under its liquidation plan.")
    st.caption("The complete daily history from this video's date has not yet been connected. The historical chart and period returns remain unavailable.")
    st.link_button("Official FINRA notice", status["source"])


def show_results(row, result, source):
    summary, periods, normalized = result
    benchmark = "Bitcoin" if summary["benchmark_symbol"] == "BTC-USD" else "S&P 500 ETF (SPY)"
    st.divider()
    st.subheader("What happened next")
    st.caption(f"Simulated entry: {summary['entry_date']} · Last common close: {summary['latest_close_date']} · {source}")
    window = summary["deadline_result"]
    st.altair_chart(comparison_chart(normalized, row["symbol"], benchmark, window), width="stretch")
    if window["status"] == "elapsed":
        values = window["metrics"]
        st.markdown(f"**By forecast deadline ({window['deadline']}):** "
                    f"asset **{values['asset_return_pct']:+.2f}%**, "
                    f"benchmark **{values['benchmark_return_pct']:+.2f}%**, "
                    f"difference **{values['difference_pp']:+.2f} pp**.")
        st.caption(f"Closing observation used: {window['observation_date']}. {window['basis']}.")
    elif window["status"] == "not_covered":
        future = pd.Timestamp(window["deadline"]).date() > date.today()
        message = "The forecast horizon is still running." if future else "Update prices to check whether later observations are available."
        st.info(f"Forecast deadline: {window['deadline']}. It lies beyond the shown history. {message}")
        st.caption(window["basis"] + ". No future performance has been estimated.")
    elif window["status"] == "before_entry":
        st.info(f"Forecast deadline: {window['deadline']}. It precedes the simulated entry, so no holding-period return is available by that deadline.")
    st.markdown("**Latest available results**")
    columns = st.columns(4)
    metrics = [
        ("Asset return", f"{summary['asset_return_pct']:+.2f}%"),
        (f"{benchmark} return", f"{summary['benchmark_return_pct']:+.2f}%"),
        ("Difference", f"{summary['difference_pp']:+.2f} pp"),
        ("Largest fall", f"{summary['max_drawdown_pct']:.2f}%"),
    ]
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)
    if summary["benchmark_symbol"] == "BTC-USD":
        st.caption("Bitcoin is the comparison asset here; it is not a broad crypto-market index.")
    last = pd.Timestamp(summary["latest_close_date"])
    if last < pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=7):
        st.info(f"This series ends on {last:%d %b %Y}. Its subsequent performance has not been assessed.")
    st.subheader("Results over time")
    display = periods[["period", "observation_date", "asset_return_pct", "benchmark_return_pct", "difference_pp"]].rename(columns={
        "period": "Period", "observation_date": "Observation date",
        "asset_return_pct": "Asset return (%)", "benchmark_return_pct": "Benchmark return (%)",
        "difference_pp": "Difference (pp)",
    })
    st.dataframe(display, hide_index=True, width="stretch", column_config={
        c: st.column_config.NumberColumn(format="%+.2f") for c in ["Asset return (%)", "Benchmark return (%)", "Difference (pp)"]})
    st.caption("Every return starts at the original entry. Only elapsed periods are shown; a non-trading anniversary uses the last common close on or before that date.")
    st.download_button("Download period results", periods.to_csv(index=False),
                       file_name=f"{row.get('case_id', 'manual')}_periods.csv", mime="text/csv")
    target = summary["price_target"]
    if target["target_usd"] is not None:
        st.subheader("Price target")
        amount = f"${target['target_usd']:,.2f}" if target["target_usd"] >= 1 else f"${target['target_usd']:.6f}"
        st.write(f"**{amount}** · {target['status']}")
        if target["target_type"] == "multiple":
            multiple = target["target_value"]
            st.caption(f"{multiple:g}× means a {(multiple - 1) * 100:g}% price increase from the selected reference.")
            label = "Simulated entry close" if target["reference_type"] == "entry" else "Creator reference price"
            st.caption(f"{label}: USD {target['reference_price']:,.6f}")
        st.caption(target["basis"])
        if target.get("creator_deadline"):
            st.caption("Creator deadline: " + target["creator_deadline"])
        if target.get("first_intraday_high_date"):
            st.caption("First observed intraday touch after entry: " + target["first_intraday_high_date"])
        if target.get("first_closing_price_date"):
            st.caption("First closing price at or above target: " + target["first_closing_price_date"])


def show_method():
    with st.expander("How the comparison works"):
        st.write("The simulated purchase uses the first common closing price after publication. Both chart lines start at 100.")
        st.write("Returns use adjusted USD closing prices, including vendor split and dividend adjustments. The largest fall is the maximum daily closing-price drawdown from an earlier peak.")
        st.write("Equities are compared with the SPY ETF; crypto with Bitcoin. Price targets are checked separately from investment returns. A forecast without a deadline is not labelled false just because a selected period has ended.")
        st.write("A price multiple uses either the simulated entry close or an explicitly supplied creator reference. For example, 2× means a 100% price gain and 10× means a 900% gain.")
        st.write("A precise covered deadline is marked in the chart; the later history remains visible. A stated duration is measured from publication. Vague time frames are retained as text without inventing an exact date.")
        st.write("The curated collection is illustrative. These examples do not establish a creator ranking or represent all financial content.")
        st.caption("Market data: Yahoo Finance via yfinance. The saved examples use the supplied TikTok notes; videos are linked, not hosted. Trading costs and investor-specific taxes are excluded.")


def example_mode():
    try:
        examples = load_examples()
    except (ValueError, FileNotFoundError) as exc:
        st.error(str(exc))
        return
    if not examples:
        st.info("No examples have been added to the table yet.")
        return
    by_id = {row["case_id"]: row for row in examples}
    default = next((i for i, row in enumerate(examples) if row["case_id"] == "7249072169680948526-MRVL"), 0)
    case_id = st.selectbox("Choose a recommendation", list(by_id), index=default,
        format_func=lambda key: f"{by_id[key]['asset']} — {by_id[key]['creator']} · {by_id[key]['publication_date']}", key="case_selector")
    row = by_id[case_id]
    show_recommendation(row)
    if row["symbol"] in {"VTIQ / NKLA", "VTIQ", "NKLA", "NKLAQ"}:
        show_nikola()
        return
    if st.button("Update prices", key="update_prices"):
        live_history.clear()
        st.session_state["live_case"] = case_id
    try:
        with st.spinner("Preparing the comparison…"):
            asset, benchmark, symbol, source = histories(row, st.session_state.get("live_case") == case_id)
            result = analyse_case(row, asset, benchmark, symbol)
        show_results(row, result, source)
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        st.error("The market-data request did not complete. Please try again; the saved examples remain available when their data are present.")
    if st.session_state.get("live_case") == case_id:
        if st.button("Use saved snapshot", key="use_snapshot"):
            st.session_state.pop("live_case", None)
            st.rerun()


def manual_mode():
    st.subheader("Check your own case")
    st.caption("Enter the asset and the date of the recommendation.")
    left, middle, right = st.columns([2, 1, 2])
    ticker = left.text_input("Yahoo Finance ticker", value="AAPL", key="manual_ticker", help="USD stocks, ADRs and crypto, for example AAPL, MRVL or KDA-USD.")
    kind = middle.selectbox("Asset type", ["Equity", "Crypto"], key="manual_type")
    published = right.date_input("Publication date", value=date(2023, 6, 26), max_value=date.today(), key="manual_date")
    value_input, reference_input, reference_type = None, None, None
    with st.expander("Target and time frame (optional)"):
        target_label = st.selectbox("Target type", ["No target", "Price target (USD)", "Price multiple"], key="manual_target_type")
        if target_label == "Price target (USD)":
            value_input = st.text_input("Upside target price (USD)", placeholder="e.g. 142", key="manual_target_price")
        elif target_label == "Price multiple":
            value_input = st.number_input("Target multiple", min_value=1.000001, value=2.0, step=1.0, format="%g", key="manual_multiple")
            st.caption("2× = doubling (+100%); 10× = tenfold (+900%).")
            reference_label = st.selectbox("Reference price", ["Simulated entry price", "Creator reference price"], key="manual_reference_type")
            reference_type = "entry" if reference_label == "Simulated entry price" else "creator"
            if reference_type == "creator":
                reference_input = st.text_input("Creator reference price (USD)", placeholder="e.g. 106", key="manual_reference_price")
        deadline = st.date_input("Forecast deadline (optional)", value=None, key="manual_deadline")
        st.caption("A deadline can be entered even without a numeric target.")
    current_inputs = (ticker, kind, str(published), target_label, str(value_input), reference_type, str(reference_input), str(deadline))
    submitted = st.button("Calculate", type="primary", key="manual_calculate")
    if submitted:
        st.session_state.pop("manual_result", None)
        try:
            symbol = provider_symbol(ticker, kind)
            target_type = {"No target": "none", "Price target (USD)": "price", "Price multiple": "multiple"}[target_label]
            value = positive_number(value_input, "Target value") if target_type != "none" else None
            if target_type == "multiple" and value <= 1:
                raise ValueError("The upside multiple must be greater than 1.")
            reference = positive_number(reference_input, "Creator reference price") if reference_type == "creator" else None
            if deadline and deadline < published:
                raise ValueError("The deadline must be on or after publication.")
            row = {"case_id": "manual-" + symbol, "asset": symbol, "symbol": symbol, "asset_type": kind,
                   "publication_date": published.isoformat(), "creator": "", "projection": "", "video_url": "",
                   "time_frame": deadline.isoformat() if deadline else "Not specified",
                   "target_type": target_type, "target_value": value,
                   "reference_type": reference_type, "reference_price": reference,
                   "deadline": deadline.isoformat() if deadline else None, "curated": False}
            if symbol in {"NKLA", "NKLAQ", "VTIQ"}:
                st.session_state["manual_result"] = {"row": row, "nikola": True, "inputs": current_inputs}
            else:
                with st.spinner("Loading daily prices and calculating…"):
                    asset, benchmark, benchmark_symbol, source = histories(row, force_live=True)
                    result = analyse_case(row, asset, benchmark, benchmark_symbol)
                st.session_state["manual_result"] = {"row": row, "result": result, "source": source, "inputs": current_inputs}
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
mode = st.radio("Mode", ["TikTok examples", "Your own case", "Import TikTok"], horizontal=True, label_visibility="collapsed", key="mode")
st.divider()
if mode == "TikTok examples":
    example_mode()
elif mode == "Your own case":
    manual_mode()
else:
    tiktok_mode(histories, show_results, show_nikola)
show_method()
