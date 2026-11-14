"""The removable TikTok import flow for the existing Streamlit app."""
from datetime import date
from copy import deepcopy
import json
import os
import time

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from case_analysis import analyse_case
from tiktok_import import ImportProblem, clean_tiktok_url, metadata_details, reviewed_case
from video_pipeline import ENGINE_VERSION, submit_import


def service_key():
    value = os.environ.get("GROQ_API_KEY", "")
    if not value:
        try:
            value = st.secrets.get("GROQ_API_KEY", "")
        except (FileNotFoundError, StreamlitSecretNotFoundError):
            value = ""
    return value.strip() if isinstance(value, str) else ""


def clear_import():
    for key in list(st.session_state):
        if key in {"tt_import", "tt_result", "tt_choice"} or key.startswith("tt_review_"):
            del st.session_state[key]


def _same_link(value, expected):
    try:
        return clean_tiktok_url(value) == expected
    except ImportProblem:
        return False


@st.fragment(run_every=2)
def poll_import():
    state = st.session_state.get("tt_import")
    if (not state or st.session_state.get("mode") != "Import TikTok"
            or not _same_link(st.session_state.get("tt_link", ""), state["url"])):
        return
    if state["status"] == "error":
        if time.time() >= state["retry_at"]:
            st.rerun()
        st.caption(f"You can retry in about {max(1, int(state['retry_at'] - time.time()))} seconds.")
        return
    task = state["task"]
    if not task.future.done():
        st.info(task.progress)
        return
    result = task.future.result()
    if result["ok"]:
        state.update(deepcopy(result["data"]), status="completed")
    else:
        state.update(status="error", error=result["error"], retry_at=task.retry_at)
    st.rerun()


def job_status(state):
    if state["status"] == "error":
        st.error(state["error"])
        if time.time() < state["retry_at"]:
            poll_import()
    elif state["status"] == "pending":
        poll_import()


def transcript_section(state):
    with st.expander("Transcript"):
        st.text(state.get("transcript") or "No speech was detected.")
        st.caption("Speech recognition may mishear names and numbers. Check important details against the original video.")
    with st.expander("Sampled screen text"):
        st.text(state.get("screen_text") or "No readable screen text was detected.")
        st.caption(state.get("screen_note", ""))


def review_fields(state):
    drafts = state["drafts"]
    choice = st.selectbox("Choose a detected recommendation", range(len(drafts)),
                          format_func=lambda i: str(drafts[i].get("asset") or f"Recommendation {i + 1}"), key="tt_choice")
    draft = drafts[choice]
    details = metadata_details(state["metadata"])
    prefix = "tt_review_" + str(choice) + "_"
    st.subheader("Review the extracted details")
    st.caption("These are AI suggestions. Correct the asset, date, target and time frame before calculating. A suggested ticker is not independently verified.")
    if draft.get("evidence"):
        st.text("Suggested supporting excerpt: " + str(draft["evidence"]))
    if draft.get("evidence_time"):
        st.caption("Approximate video timestamp: " + str(draft["evidence_time"]))
    a, b = st.columns(2)
    asset = a.text_input("Asset name", value=str(draft.get("asset") or ""), key=prefix + "asset")
    symbol = b.text_input("Yahoo Finance ticker", value=str(draft.get("symbol") or ""), key=prefix + "symbol")
    a, b, c = st.columns([1, 1, 2])
    kinds = ["Choose asset type", "Equity", "Crypto"]
    kind = a.selectbox("Asset type", kinds, index=kinds.index(draft.get("asset_type")) if draft.get("asset_type") in kinds else 0, key=prefix + "kind")
    published = b.date_input("Publication date", value=details["publication_date"], max_value=date.today(), key=prefix + "published")
    creator = c.text_input("Creator", value=details["creator"], key=prefix + "creator")
    claim = st.text_area("Extracted prediction", value=str(draft.get("claim") or ""), height=85, key=prefix + "claim")

    labels = {"none": "No numeric target", "price": "Price target (USD)", "multiple": "Price multiple"}
    target_type = st.selectbox("Target type", list(labels), format_func=labels.get,
                              index=list(labels).index(draft.get("target_type")) if draft.get("target_type") in labels else 0,
                              key=prefix + "target_type")
    target_value, reference_price, reference_type, currency = None, None, None, None
    if target_type != "none":
        default_value = draft.get("target_value") if draft.get("target_type") == target_type else None
        target_value = st.text_input("Target price (USD)" if target_type == "price" else "Target multiple", value=str(default_value) if default_value is not None else "", key=prefix + target_type + "_value")
        if target_type == "multiple":
            st.caption("2× = doubling (+100%); 10× = tenfold (+900%).")
            refs = {"entry": "Simulated entry price", "creator": "Creator reference price"}
            reference_type = st.selectbox("Reference price", list(refs), format_func=refs.get,
                                         index=1 if draft.get("reference_price") is not None else 0, key=prefix + "reference_type")
            if reference_type == "creator":
                reference_price = st.text_input("Creator reference price (USD)", value=str(draft.get("reference_price") or ""), key=prefix + "reference_price")
            else:
                st.caption("The entry close is your comparison reference when the creator did not give one.")
        if target_type == "price" or reference_type == "creator":
            currency = st.selectbox("Currency of the stated price", ["Other / unclear", "USD"],
                                    index=1 if draft.get("currency") == "USD" else 0, key=prefix + "currency")

    time_frame = st.text_input("Stated time frame", value=str(draft.get("time_frame") or ""), key=prefix + "time_frame")
    deadline_default = None
    try:
        deadline_default = date.fromisoformat(str(draft.get("deadline")))
    except ValueError:
        pass
    duration = draft.get("horizon_value")
    duration_valid = isinstance(duration, int) and not isinstance(duration, bool) and duration > 0 and draft.get("horizon_unit") in {"days", "weeks", "months", "years"}
    window_options = ["Not specified / vague", "Exact deadline", "Duration from publication"]
    mode = st.selectbox("Time-frame type", window_options,
                        index=1 if deadline_default else 2 if duration_valid else 0, key=prefix + "window_type")
    deadline, horizon_value, horizon_unit = None, None, None
    if mode == "Exact deadline":
        deadline = st.date_input("Forecast deadline", value=deadline_default, key=prefix + "deadline")
    elif mode == "Duration from publication":
        a, b = st.columns(2)
        horizon_value = a.text_input("Time-frame length", value=str(duration) if duration_valid else "", key=prefix + "duration")
        units = ["days", "weeks", "months", "years"]
        horizon_unit = b.selectbox("Time-frame unit", units, index=units.index(draft["horizon_unit"]) if duration_valid else 2, key=prefix + "unit")
    else:
        st.caption("Vague wording is retained without inventing an exact deadline.")
    values = {"asset": asset, "symbol": symbol, "asset_type": kind, "publication_date": published,
              "creator": creator, "claim": claim, "target_type": target_type, "target_value": target_value,
              "reference_type": reference_type, "reference_price": reference_price, "currency": currency,
              "time_frame": time_frame, "deadline": deadline.isoformat() if deadline else None,
              "horizon_value": horizon_value, "horizon_unit": horizon_unit,
              "evidence": draft.get("evidence"), "evidence_time": draft.get("evidence_time")}
    return values, mode, choice


def tiktok_mode(histories, show_results, show_nikola):
    st.subheader("Import a TikTok recommendation")
    st.caption("Paste a public TikTok up to three minutes long. Groq transcribes the speech and identifies predictions; sampled screen text is read with OCR. Review the details before calculating. Shared usage limits can temporarily pause imports.")
    link = st.text_input("TikTok video link", placeholder="https://www.tiktok.com/@creator/video/…", key="tt_link")
    key = service_key()
    if not key:
        st.info("The video import service has not been connected yet. The app owner needs to complete its setup. The other two modes are ready to use.")
    state = st.session_state.get("tt_import")
    if state and state.get("engine") != ENGINE_VERSION:
        clear_import()
        state = None
    same = bool(state and _same_link(link, state["url"]))
    busy_or_ready = same and (state["status"] in {"pending", "completed"} or time.time() < state.get("retry_at", 0))
    if st.button("Analyse video", type="primary", disabled=not key or busy_or_ready, key="tt_analyse"):
        try:
            url = clean_tiktok_url(link)
            task, reused = submit_import(url, key)
            clear_import()
            st.session_state["tt_import"] = {"engine": ENGINE_VERSION, "url": url, "task": task,
                                            "status": "pending", "reused": reused}
            st.rerun()
        except ImportProblem as exc:
            st.error(str(exc))
    if not state:
        return
    if not same:
        st.info("Press Analyse video to load the changed link.")
        return
    if st.button("Clear this import", key="tt_clear", help="Clears your current view and edits. Source-derived results for this public video may remain in the shared server cache for up to 24 hours."):
        clear_import()
        st.rerun()
    job_status(state)
    if state["status"] != "completed":
        return
    st.link_button("Original video", state["url"])
    if state.get("reused"):
        st.caption("Reused an existing analysis of this public video. No new transcription or prediction request was started for this import.")
    st.caption("Source analysis time (UTC): " + state["analysed_at"])
    transcript_section(state)
    if not state["drafts"]:
        st.info("No supported stock or crypto buy/upside prediction was detected. You can still use Your own case to enter an asset and date manually.")
        return
    values, mode, choice = review_fields(state)
    signature = json.dumps({"url": state["url"], "choice": choice, "mode": mode, "values": values}, default=str, sort_keys=True)
    if st.button("Calculate checked case", type="primary", key="tt_calculate"):
        st.session_state.pop("tt_result", None)
        try:
            if mode == "Exact deadline" and not values["deadline"]:
                raise ImportProblem("Enter the forecast deadline or choose Not specified / vague.")
            if mode == "Duration from publication" and not values["horizon_value"]:
                raise ImportProblem("Enter the stated duration or choose Not specified / vague.")
            row = reviewed_case(values, state["url"])
            if row["symbol"] in {"VTIQ", "NKLA", "NKLAQ"}:
                stored = {"row": row, "nikola": True}
            else:
                with st.spinner("Loading daily prices and calculating…"):
                    asset, benchmark, benchmark_symbol, source = histories(row, force_live=True)
                    stored = {"row": row, "result": analyse_case(row, asset, benchmark, benchmark_symbol), "source": source}
            st.session_state["tt_result"] = {**stored, "signature": signature}
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("The market-data request did not complete. Check the ticker or try again later.")
    stored = st.session_state.get("tt_result")
    if stored and stored["signature"] != signature:
        st.info("Click Calculate checked case to apply the changed details.")
    elif stored:
        row = stored["row"]
        st.subheader(row["asset"])
        st.caption(f"{row['creator'] or 'Creator not specified'} · Published {row['publication_date']} · {row['symbol']}")
        st.text(row["projection"])
        if stored.get("nikola"):
            show_nikola()
        else:
            show_results(row, stored["result"], stored["source"])
        st.download_button("Download checked case", json.dumps(row, indent=2),
                           file_name=row["case_id"] + ".json", mime="application/json")
        st.caption("Your checked details stay in this session and are not added to the curated collection. Source-derived results for the public video may be reused by other visitors for up to 24 hours; your edits are not shared. Original video/audio/frame files are deleted after processing. Groq has its own data policy.")
