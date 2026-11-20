"""The removable TikTok import flow for the existing Streamlit app."""
from datetime import date
from copy import deepcopy
import json
import os
import re
import time

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from case_analysis import analyse_comparisons
from tiktok_import import ImportProblem, clean_tiktok_url, metadata_details, reviewed_case, normalise_timing
from video_pipeline import ENGINE_VERSION, submit_import

IMPORT_VERSION = "2026-11-15.10"


def service_key():
    value = os.environ.get("GROQ_API_KEY", "")
    if not value:
        try:
            value = st.secrets.get("GROQ_API_KEY", "")
        except (FileNotFoundError, StreamlitSecretNotFoundError):
            value = ""
    return value.strip() if isinstance(value, str) else ""


def clear_import(clear_link=False):
    for key in list(st.session_state):
        if key in {"tt_import", "tt_result", "tt_choice"} or key.startswith("tt_review_"):
            del st.session_state[key]
    if clear_link:
        st.session_state["tt_link"] = ""


def use_screen_target(prefix, value, original):
    st.session_state[prefix + "price_value"] = f"{value:g}"
    # Keep an explicitly chosen correction consistent with the extracted summary.
    def replace(match):
        amount = float(match["amount"].replace(",", ""))
        return match["prefix"] + f"{value:g}" if amount == original else match[0]
    st.session_state[prefix + "claim"] = re.sub(
        r"(?P<prefix>\$|USD\s+)(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?![\d,])",
        replace, st.session_state.get(prefix + "claim", ""))


def use_ticker_match(prefix, candidate, index):
    st.session_state[prefix + "asset"] = candidate["asset"]
    st.session_state[prefix + "symbol"] = candidate["symbol"]
    st.session_state[prefix + "kind"] = candidate["asset_type"]
    # Keep the recommendation that owns this button selected.
    st.session_state["tt_choice"] = index
    state = st.session_state.get("tt_import")
    if state:
        state["drafts"][index].update(candidate)


def add_recommendation():
    state = st.session_state["tt_import"]
    state["drafts"].append({"asset": "", "symbol": None, "asset_type": "Unknown", "claim": "", "target_type": "none"})
    st.session_state["tt_choice"] = len(state["drafts"]) - 1
    st.session_state.pop("tt_result", None)


def recommendation_changed():
    st.session_state.pop("tt_result", None)


def start_import(url, key, refresh=False):
    task, reused = submit_import(url, key, refresh=refresh)
    clear_import()
    st.session_state["tt_import"] = {"engine": ENGINE_VERSION, "url": url, "task": task,
                                    "status": "pending", "reused": reused}


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
        state.update(deepcopy(result.get("data", {})))
        state.update(status="error", error=result["error"], retry_at=task.retry_at)
    st.rerun()


def job_status(state):
    if state["status"] == "error":
        st.error(state["error"])
        if time.time() < state["retry_at"]:
            poll_import()
    elif state["status"] == "pending":
        poll_import()


def import_report(state):
    """Export only public-source diagnostics, never keys, tasks or private edits."""
    return {"import_version": IMPORT_VERSION, "analysis_version": state.get("import_version"),
            "engine": state.get("engine"), "video_url": state["url"],
            "post_url": state["url"], "source_kind": state.get("source_kind", "video"),
            "photo_text": state.get("photo_text"), "photo_count": state.get("photo_count"),
            "status": state.get("status"), "error": state.get("error"),
            "failed_stage": state.get("failed_stage"),
            "provider_error": state.get("provider_error"), "compatibility_mode": state.get("compatibility_mode", False),
            "analysed_at": state.get("analysed_at"), "transcript": state.get("transcript"),
            "extraction_checks": state.get("extraction_checks", []),
            "post_processing_targets": [{field: row.get(field) for field in ["asset", "symbol", "asset_type", "target_type", "target_value", "target_approximate", "reference_price", "currency", "target_recovered", "target_review", "time_frame"]} for row in state.get("raw_drafts", [])],
            "extraction_result_count": len(state.get("raw_drafts", [])),
            "review_list_count": len(state.get("drafts", []))}


def transcript_section(state):
    photo = state.get("source_kind") == "photo"
    with st.expander("Extracted text" if photo else "Transcript"):
        st.text((state.get("source_text") or state.get("transcript")) or ("No readable text was detected." if photo else "No speech was detected."))
    diagnostic_section(state)


def diagnostic_section(state):
    with st.expander("Import details"):
        st.caption("Import version: " + IMPORT_VERSION)
        st.download_button("Download import report", json.dumps(import_report(state), indent=2),
                           file_name="import-report.json", mime="application/json", key="tt_report")


def review_fields(state):
    drafts = state["drafts"]
    # Keep selection and per-asset edits when other recommendations hide their widgets.
    # clear_import still removes this session state before a different source is loaded.
    # Fixed labels: a chosen ticker match renames the draft, and a changed
    # option label would make Streamlit treat the selector as a new widget and
    # fall back to the first recommendation on the next click.
    labels = state.setdefault("choice_labels", [])
    labels.extend(str(drafts[i].get("asset") or f"Recommendation {i + 1}") for i in range(len(labels), len(drafts)))
    choice = st.selectbox("Choose a detected recommendation", range(len(drafts)),
                          format_func=lambda i: labels[i],
                          key="tt_choice", persist_state="session", on_change=recommendation_changed)
    draft = normalise_timing(drafts[choice])
    details = metadata_details(state["metadata"])
    prefix = "tt_review_" + str(choice) + "_"
    st.subheader("Review the extracted details")
    st.caption("Check the details before calculating.")
    for index, candidate in enumerate(draft.get("ticker_suggestions", [])):
        st.button(f"Use {candidate['asset']} ({candidate['symbol']})", key=prefix + f"match_{index}",
                  on_click=use_ticker_match, args=(prefix, candidate, choice))
    if draft.get("evidence"):
        with st.expander("Source excerpt"):
            st.text(str(draft["evidence"]))
            if draft.get("evidence_time"):
                st.caption(str(draft["evidence_time"]))
    a, b = st.columns(2)
    asset = a.text_input("Asset name", value=str(draft.get("asset") or ""), key=prefix + "asset", persist_state="session")
    with b.container(key=prefix + "ticker_field"):
        symbol = st.text_input("Yahoo Finance ticker (required)", value=str(draft.get("symbol") or ""),
                               placeholder="Select a match above or enter a ticker",
                               key=prefix + "symbol", persist_state="session")
        if not symbol.strip():
            # Keep empty values flowing to Python so Calculate cannot reuse an old ticker.
            st.markdown(f"""<style>
.st-key-{prefix}ticker_field [data-baseweb="input"] {{
    border-color: #c62828 !important;
}}
.st-key-{prefix}ticker_field input {{
    outline: 2px solid #c62828 !important;
    outline-offset: -2px;
    border-radius: 0.5rem;
}}
</style>""", unsafe_allow_html=True)
            message = ("Select a suggested match above or enter a ticker to continue."
                       if draft.get("ticker_suggestions") else "Enter a ticker to continue.")
            st.caption(":red[" + message + "]")
    a, b, c = st.columns([1, 1, 2])
    kinds = ["Choose asset type", "Equity", "Crypto", "ETF"]
    kind = a.selectbox("Asset type", kinds, index=kinds.index(draft.get("asset_type")) if draft.get("asset_type") in kinds else 0, key=prefix + "kind", persist_state="session")
    published = b.date_input("Publication date", value=details["publication_date"], max_value=date.today(), key=prefix + "published", persist_state="session")
    creator = c.text_input("Creator", value=details["creator"], key=prefix + "creator", persist_state="session")
    claim = st.text_area("Extracted prediction", value=str(draft.get("claim") or ""), height=85, key=prefix + "claim", persist_state="session")

    labels = {"none": "No numeric target", "price": "Price target (USD)", "multiple": "Price multiple"}
    target_type = st.selectbox("Target type", list(labels), format_func=labels.get,
                              index=list(labels).index(draft.get("target_type")) if draft.get("target_type") in labels else 0,
                              key=prefix + "target_type", persist_state="session")
    target_value, reference_price, reference_type, currency = None, None, None, None
    target_approximate = False
    target_review = draft.get("target_review") if target_type == "price" else None
    if target_type != "none":
        default_value = draft.get("target_value") if draft.get("target_type") == target_type else None
        if target_review:
            if not str(st.session_state.get(prefix + "price_value", "")).strip():
                st.warning("Conflicting target values. Check the original post, then choose or enter a target.")
                readings = ", ".join(f"{price:g}" for price in target_review["screen_values"])
                st.caption(f"Extracted: {target_review['extracted_value']:g} · Screen text: {readings}")
                suggestions = ([target_review["suggested_value"]] if target_review.get("suggested_value") is not None
                               else target_review["screen_values"][:4])
                for index, value in enumerate(suggestions):
                    st.button(f"Use {value:g}", key=prefix + f"screen_target_{index}",
                              on_click=use_screen_target, args=(prefix, value, target_review["extracted_value"]))
            default_value = None
        target_value = st.text_input("Target price (USD)" if target_type == "price" else "Target multiple", value=str(default_value) if default_value is not None else "", key=prefix + target_type + "_value", persist_state="session")
        if target_review and not target_value.strip():
            st.caption(":red[Choose or enter a checked target to continue.]")
        target_approximate = st.checkbox("Approximate target", value=bool(draft.get("target_approximate")), key=prefix + "approximate", persist_state="session")
        if target_type == "multiple":
            refs = {"entry": "Simulated entry price", "creator": "Creator reference price"}
            reference_type = st.selectbox("Reference price", list(refs), format_func=refs.get,
                                         index=1 if draft.get("reference_price") is not None else 0, key=prefix + "reference_type", persist_state="session")
            if reference_type == "creator":
                reference_price = st.text_input("Creator reference price (USD)", value=str(draft.get("reference_price") or ""), key=prefix + "reference_price", persist_state="session")
        if target_type == "price" or reference_type == "creator":
            with st.container(key=prefix + "currency_field"):
                currency = st.selectbox("Currency of the stated price", ["Other / unclear", "USD"],
                                        index=1 if draft.get("currency") == "USD" else 0, key=prefix + "currency", persist_state="session")
                if currency != "USD":
                    st.markdown(f"<style>.st-key-{prefix}currency_field [role='combobox']"
                                "{outline:2px solid #c62828;outline-offset:2px;border-radius:0.4rem;}</style>",
                                unsafe_allow_html=True)
                    st.caption(":red[Confirm USD to check this target.]")

    deadline_default = None
    try:
        deadline_default = date.fromisoformat(str(draft.get("deadline")))
    except ValueError:
        pass
    duration = draft.get("horizon_value")
    duration_valid = isinstance(duration, int) and not isinstance(duration, bool) and duration > 0 and draft.get("horizon_unit") in {"days", "weeks", "months", "years"}
    year_text = re.fullmatch(r"\s*(?:(?:by|for|in|during)\s+)?(?:the\s+year\s+)?(20\d{2})\s*",
                             str(draft.get("time_frame") or ""), re.I)
    window_options = ["Not specified / vague", "Exact deadline", "Duration from publication", "Forecast year"]
    mode = st.selectbox("Time-frame type", window_options,
                        index=1 if deadline_default else 2 if duration_valid else 3 if year_text else 0, key=prefix + "window_type", persist_state="session")
    deadline, horizon_value, horizon_unit, deadline_basis = None, None, None, None
    if mode == "Exact deadline":
        deadline = st.date_input("Forecast deadline", value=deadline_default, key=prefix + "deadline", persist_state="session")
        time_frame = "By " + deadline.isoformat() if deadline else ""
    elif mode == "Duration from publication":
        a, b = st.columns(2)
        horizon_value = a.text_input("Time-frame length", value=str(duration) if duration_valid else "", key=prefix + "duration", persist_state="session")
        units = ["days", "weeks", "months", "years"]
        horizon_unit = b.selectbox("Time-frame unit", units, index=units.index(draft["horizon_unit"]) if duration_valid else 2, key=prefix + "unit", persist_state="session")
        time_frame = f"{horizon_value} {horizon_unit} after publication" if horizon_value else ""
    elif mode == "Forecast year":
        year = st.number_input("Forecast year", min_value=1900, max_value=2200,
                               value=int(year_text[1]) if year_text else date.today().year,
                               step=1, key=prefix + "year", persist_state="session")
        deadline = date(year, 12, 31)
        deadline_basis = f"Year-end evaluation for the stated forecast year {year}"
        time_frame = f"{year} (year-end evaluation)"
        st.caption("Evaluated on 31 December of the selected year.")
    else:
        time_frame = st.text_input("Stated time frame", value=str(draft.get("time_frame") or ""), key=prefix + "time_frame", persist_state="session")
        if time_frame.strip():
            st.caption("Select a deadline or duration to apply a time limit.")
    values = {"asset": asset, "symbol": symbol, "asset_type": kind, "publication_date": published,
              "source_kind": state.get("source_kind", "video"),
              "creator": creator, "claim": claim, "target_type": target_type, "target_value": target_value,
              "target_approximate": target_approximate,
              "target_needs_review": bool(target_review and not str(target_value or "").strip()),
              "reference_type": reference_type, "reference_price": reference_price, "currency": currency,
              "time_frame": time_frame, "deadline": deadline.isoformat() if deadline else None,
              "deadline_basis": deadline_basis,
              "horizon_value": horizon_value, "horizon_unit": horizon_unit,
              "evidence": draft.get("evidence"), "evidence_time": draft.get("evidence_time")}
    return values, mode, choice


def tiktok_mode(histories, show_results, show_nikola, track_button=None, show_company_description=None):
    st.subheader("Import a TikTok recommendation")
    st.caption("Paste a video or photo link. Videos: up to 3 minutes. Photo posts: up to 15 images.")
    link = st.text_input("TikTok post link", placeholder="https://www.tiktok.com/@creator/…", key="tt_link", persist_state="session")
    key = service_key()
    if not key:
        st.info("The TikTok import service has not been connected yet. The app owner needs to complete its setup. The other two modes are ready to use.")
    state = st.session_state.get("tt_import")
    if state and state.get("engine") != ENGINE_VERSION:
        clear_import()
        state = None
    same = bool(state and _same_link(link, state["url"]))
    busy_or_ready = same and (state["status"] in {"pending", "completed"} or time.time() < state.get("retry_at", 0))
    if st.button("Analyse post", type="primary", disabled=not key or busy_or_ready, key="tt_analyse"):
        try:
            url = clean_tiktok_url(link)
            start_import(url, key)
            st.rerun()
        except ImportProblem as exc:
            st.error(str(exc))
    if not state:
        return
    if not same:
        st.info("Press Analyse post to load the changed link.")
        return
    st.button("Clear this import", key="tt_clear", on_click=clear_import, args=(True,),
              help="Clears the link, results and your edits.")
    job_status(state)
    if state["status"] != "completed":
        if state.get("source_text") or state.get("transcript"):
            transcript_section(state)
        elif state["status"] == "error":
            diagnostic_section(state)
        return
    st.link_button("Original post", state["url"])
    if state.get("reused"):
        st.caption("Loaded a saved analysis of this post.")
    transcript_section(state)
    count = len(state["drafts"])
    if state.get("source_kind") == "photo":
        st.caption(f"{state.get('photo_count', 0)} photos · {count} recommendation{'s' if count != 1 else ''} found")
    elif count:
        st.caption(f"{count} recommendation{'s' if count != 1 else ''} found")
    a, b = st.columns(2)
    a.button("Add a recommendation", key="tt_add", on_click=add_recommendation)
    can_refresh = time.time() >= state["task"].created + 30
    if b.button("Check extraction again", key="tt_refresh", disabled=not key,
                help="Rechecks the existing text without downloading or reading the post again."):
        if not can_refresh:
            st.info(f"Try again in {max(1, int(state['task'].created + 30 - time.time()))} seconds.")
        else:
            try:
                start_import(state["url"], key, refresh=True)
                st.rerun()
            except ImportProblem as exc:
                st.error(str(exc))
    if not state["drafts"]:
        st.info("No recommendation identified. Check the transcript, try again or add one manually.")
        return
    values, mode, choice = review_fields(state)
    signature = json.dumps({"url": state["url"], "choice": choice, "mode": mode, "values": values}, default=str, sort_keys=True)
    def checked_row():
        if values["target_needs_review"]:
            raise ImportProblem("Check the conflicting target before continuing.")
        if mode == "Exact deadline" and not values["deadline"]:
            raise ImportProblem("Enter the forecast deadline or choose Not specified / vague.")
        if mode == "Duration from publication" and not values["horizon_value"]:
            raise ImportProblem("Enter the stated duration or choose Not specified / vague.")
        return reviewed_case(values, state["url"])
    a, b = st.columns(2)
    needs_currency = values["target_type"] == "price" or values["reference_type"] == "creator"
    calculate = a.button("Calculate checked case", type="primary", key="tt_calculate",
                         disabled=not values["symbol"].strip() or values["target_needs_review"] or (needs_currency and values["currency"] != "USD"))
    if track_button:
        with b:
            track_button(checked_row, key="tt_track")
    if calculate:
        st.session_state.pop("tt_result", None)
        try:
            row = checked_row()
            if row["symbol"] in {"VTIQ", "NKLA", "NKLAQ"}:
                stored = {"row": row, "nikola": True}
            else:
                with st.spinner("Loading daily prices and calculating…"):
                    data = histories(row, force_live=True)
                    stored = {"row": row, "result": analyse_comparisons(row, data), "source": data["source"]}
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
        if show_company_description:
            show_company_description(row)
        st.caption(f"{row['creator'] or 'Creator not specified'} · Published {row['publication_date']} · {row['symbol']}")
        st.text(row["projection"])
        if stored.get("nikola"):
            show_nikola()
        else:
            show_results(row, stored["result"], stored["source"])
        st.download_button("Download checked case", json.dumps(row, indent=2),
                           file_name=row["case_id"] + ".json", mime="application/json")
        st.caption("Save to My Tracker to keep this prediction.")
