"""Personal browser-backed tracker, independent of the shared TikTok cache."""
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from tracker_core import (prediction_record, tracker_records,
                          forecast_status, forecast_label, tracker_comparison)

IMPORT_VERSION = "2026-11-15.8"
# Register once per process; Streamlit reruns mount the same component.
_storage = st.components.v2.component("reality_check_tracker_storage_v1",
            js=(Path(__file__).with_name("tracker_storage.js")).read_text(encoding="utf-8"))


def sync_tracker():
    st.session_state.setdefault("tracker_items", [])
    st.session_state.setdefault("tracker_request", str(uuid4()))
    st.session_state.setdefault("tracker_ready", False)
    result = _storage(data={"request_id": st.session_state["tracker_request"],
                            "operation": st.session_state.get("tracker_pending")},
                      default={"reply": None}, on_reply_change=lambda: None,
                      key="tracker_browser_storage", height=0)
    reply = result.reply
    if (not isinstance(reply, dict) or reply.get("request_id") != st.session_state["tracker_request"]
            or st.session_state.get("tracker_applied") == reply["request_id"]):
        return
    st.session_state["tracker_applied"] = reply["request_id"]
    operation = st.session_state.pop("tracker_pending", None)
    if reply.get("error"):
        st.session_state["tracker_error"] = str(reply["error"])
        st.session_state["tracker_ready"] = False
        return
    try:
        records = tracker_records(reply.get("items"))
    except ValueError:
        st.session_state["tracker_error"] = "The saved tracker could not be read. Your browser copy has not been replaced."
        st.session_state["tracker_ready"] = False
        return
    st.session_state["tracker_items"] = records
    st.session_state["tracker_ready"] = True
    st.session_state.pop("tracker_error", None)
    if operation:
        notice = "Removed from My Tracker." if operation["kind"] == "remove" else "Saved to My Tracker."
        st.session_state["tracker_notice"] = notice


def queue_change(operation):
    st.session_state["tracker_pending"] = operation
    st.session_state["tracker_request"] = str(uuid4())
    st.session_state.pop("tracker_error", None)
    st.rerun()


def track_button(row_factory, key):
    ready = st.session_state.get("tracker_ready", False) and not st.session_state.get("tracker_pending")
    if st.button("Track this prediction", key=key, disabled=not ready):
        try:
            row = prediction_record(row_factory())
            queue_change({"kind": "upsert", "items": [row]})
        except ValueError as exc:
            st.error(str(exc))


def storage_message():
    if st.session_state.get("tracker_notice"):
        st.success(st.session_state.pop("tracker_notice"))
    if st.session_state.get("tracker_error"):
        st.error(st.session_state["tracker_error"])
        if st.button("Retry tracker storage", key="tracker_retry_storage"):
            st.session_state["tracker_request"] = str(uuid4())
            st.rerun()
    elif st.session_state.get("tracker_pending"):
        st.caption("Saving your tracker…")


def tracker_mode(histories, show_results, show_nikola, clear_prices):
    st.subheader("My Tracker")
    st.caption("Saved in this browser.")
    rows = st.session_state.get("tracker_items", [])
    ready = st.session_state.get("tracker_ready", False)
    if not ready and not st.session_state.get("tracker_error"):
        st.info("Loading your tracker…")
    if not rows:
        st.info("No predictions saved yet. Choose Track this prediction after an import or manual entry.")
    else:
        by_id = {row["tracker_id"]: row for row in rows}
        st.dataframe(pd.DataFrame([{
            "Asset": row["asset"], "Creator": row["creator"] or "—",
            "Published": row["publication_date"], "Prediction": forecast_label(row),
            "Status": forecast_status(row)[0],
            "Deadline": forecast_status(row)[1],
        } for row in reversed(rows)]), hide_index=True, width="stretch")
        # A removed selection must not carry over to an unrelated prediction.
        if st.session_state.get("tracker_choice") not in by_id:
            st.session_state.pop("tracker_choice", None)
        selected = st.selectbox("Choose a tracked prediction", list(reversed(by_id)),
                    format_func=lambda key: f"{by_id[key]['asset']} · {by_id[key]['creator'] or by_id[key]['symbol']} · {by_id[key]['publication_date']}",
                    key="tracker_choice")
        row = by_id[selected]
        st.subheader(row["asset"])
        st.caption(f"{row['creator'] or 'Creator not specified'} · Published {row['publication_date']} · {row['symbol']}")
        if row.get("projection"):
            st.text(row["projection"])
        state, detail = forecast_status(row)
        st.caption(f"{state} · {detail}")
        if row.get("video_url"):
            st.link_button("Original post", row["video_url"])
        a, b = st.columns(2)
        refresh = a.button("Refresh prices", key="tracker_refresh", disabled=bool(row.get("history_archive")))
        if b.button("Remove prediction", key="tracker_remove", disabled=not ready or bool(st.session_state.get("tracker_pending"))):
            queue_change({"kind": "remove", "tracker_id": selected})
        if refresh:
            clear_prices()
        if row["symbol"] in {"VTIQ", "NKLA", "NKLAQ"}:
            show_nikola()
        else:
            try:
                with st.spinner("Loading the latest available prices…"):
                    result, source = tracker_comparison(row, histories)
                if result is None:
                    st.info(source)
                else:
                    show_results(row, result, source)
            except ValueError as exc:
                st.info(str(exc))
                st.caption("Your prediction is saved. Prices can be checked again later.")
            except Exception:
                st.info("Prices are unavailable right now. Your prediction is saved; try again later.")
