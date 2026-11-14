"""The removable TikTok import flow for the existing Streamlit app."""
from datetime import date
import json
import os
import time

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from case_analysis import analyse_case
from tiktok_import import (ImportProblem, SupadataClient, clean_tiktok_url, metadata_details,
                           recommendations, reviewed_case, transcript_text)


def service_key():
    value = os.environ.get("SUPADATA_API_KEY", "")
    if not value:
        try:
            value = st.secrets.get("SUPADATA_API_KEY", "")
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


@st.fragment(run_every=3)
def poll_import():
    state = st.session_state.get("tt_import")
    if (not state or st.session_state.get("mode") != "Import TikTok"
            or not _same_link(st.session_state.get("tt_link", ""), state["url"])):
        return
    for kind in ["extract", "transcript"]:
        task = state.get(kind)
        if not task or task["status"] != "pending" or task.get("paused"):
            continue
        if time.monotonic() - task["started"] > 180:
            task.update(paused=True, error="Processing is taking longer than expected. Check progress again without starting another analysis.")
            st.rerun()
        try:
            result = SupadataClient(service_key()).job(kind, task["id"])
            if result["status"] == "completed":
                if kind == "extract":
                    state["drafts"] = recommendations(result)
                else:
                    task["text"] = transcript_text(result)
                task["status"] = "completed"
                st.rerun()
            st.info("Analysing the video…" if kind == "extract" else "Preparing the transcript…")
        except ImportProblem as exc:
            task.update(paused=True, error=str(exc))
            st.rerun()


def job_status(state):
    pending = False
    for kind in ["extract", "transcript"]:
        task = state.get(kind)
        if not task or task["status"] != "pending":
            continue
        if task.get("paused"):
            st.warning(task["error"])
            if st.button("Check analysis progress" if kind == "extract" else "Check transcript progress", key="tt_retry_" + kind):
                task.update(paused=False, started=time.monotonic())
                st.rerun()
        else:
            pending = True
    if pending:
        poll_import()


def transcript_section(state, key):
    task = state.get("transcript")
    if task and task["status"] == "completed":
        with st.expander("Transcript"):
            st.text(task["text"])
            st.caption("Transcription may contain errors. Check important numbers against the original video.")
    elif not task:
        if st.button("Get transcript", key="tt_transcribe", help="Optional: uses additional video-service credits. Existing captions are used when available; otherwise speech is transcribed."):
            try:
                with st.spinner("Requesting the transcript…"):
                    result = SupadataClient(key).start_transcript(state["url"])
                if result.get("jobId"):
                    state["transcript"] = {"id": result["jobId"], "status": "pending", "started": time.monotonic()}
                else:
                    state["transcript"] = {"status": "completed", "text": transcript_text(result)}
                st.rerun()
            except ImportProblem as exc:
                st.error(str(exc))


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
    st.caption("Paste a public video link. Supadata analyses its audio and visible text; you review the details before calculating. Each new analysis uses project credits.")
    link = st.text_input("TikTok video link", placeholder="https://www.tiktok.com/@creator/video/…", key="tt_link")
    key = service_key()
    if not key:
        st.info("The video import service has not been connected yet. The app owner needs to complete its setup. The other two modes are ready to use.")
    state = st.session_state.get("tt_import")
    same = bool(state and _same_link(link, state["url"]))
    if st.button("Analyse video", type="primary", disabled=not key or same, key="tt_analyse"):
        try:
            url = clean_tiktok_url(link)
            client = SupadataClient(key)
            with st.spinner("Reading video details and starting the analysis…"):
                metadata = client.metadata(url)
                if metadata.get("platform") not in {None, "tiktok"} or metadata.get("type") not in {None, "video"}:
                    raise ImportProblem("Choose a TikTok video rather than a photo or carousel post.")
                job_id = client.start_analysis(url)
            clear_import()
            st.session_state["tt_import"] = {"url": url, "metadata": metadata,
                                            "extract": {"id": job_id, "status": "pending", "started": time.monotonic()}}
            st.rerun()
        except ImportProblem as exc:
            st.error(str(exc))
    if not state:
        return
    if not same:
        st.info("Press Analyse video to load the changed link.")
        return
    if st.button("Clear this import", key="tt_clear", help="Removes this session's imported details and transcript. It does not cancel processing already started at the external provider."):
        clear_import()
        st.rerun()
    job_status(state)
    if state["extract"]["status"] != "completed":
        return
    st.link_button("Original video", state["url"])
    transcript_section(state, key)
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
        st.caption("This import stays in your current session. It is not added to the curated collection. Clearing it removes the app's session copy; the provider has its own retention policy.")
