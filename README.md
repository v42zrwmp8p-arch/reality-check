# Reality Check

A Python prototype that compares a TikTok investment recommendation with what
happened afterwards. Choose a curated example, enter a USD stock/ETF/crypto ticker
and publication date, or import a public TikTok link for review. The app shows a full-history chart, cumulative returns,
benchmark differences, drawdown and fixed holding periods.

The four modes are **Import TikTok**, **Manual Entry**, **My Tracker**, then
**Case Database**. A new visit starts with Import TikTok. Prices and targets use short labels; supporting methodology
is kept in the expandable explanation.

## Release consistency

Release `2026-11-14.13` checks that Streamlit's entry script and all twelve
helpers use the same release. A mismatch reloads the helpers in dependency
order once; ordinary widget reruns keep the shared queue and cache. An
incomplete deployment is not silently treated as a current import. Old source
results are isolated by engine v8. The dependency file also changed to request
a fresh Community Cloud deployment. Existing pinned dependencies are retained.

The reported combination of new menu labels and the old no-result message
suggested stale imported code; this has not been directly confirmed on the
deployment host. A regression test reproduces stale helpers in one running
Python process and checks recovery, shared queue preservation and normal reruns.

**Import details** shows the active release and offers **Download import
report**: the exact JSON body sent for extraction (including the source text
and prompt), actual returned content, response ID, finish reason, parsing
status, detected assets and final counts. It excludes Authorization headers,
API keys, task objects and private edits. The transcript and report remain
available if extraction fails after successful speech recognition.
This makes a remaining real model failure inspectable instead of guessing
from successful transcription alone. Live model accuracy is still separate
from these runtime and simulated-response tests.

## Iconic market calls

Release `2026-11-14.13` focuses **Case Database** on selected memorable market
calls, with the heading **Iconic market calls**. The database remains the last
navigation item; new visits still start with Import TikTok. Automatic import
still supports TikTok only. The nine active cases are:

- Roaring Kitty / GameStop, 4 August 2020: the dated original YouTube description
  explicitly states a bullish view. No numeric target or exact horizon is
  invented from the longer video. The chart starts on 5 August 2020.
- Jim Cramer / Coinbase, 13 April 2021: CNBC's original YouTube description
  recommends buying some at the following day's direct listing, ideally below
  USD 475. That purchase-price ceiling is not treated as a forecast target.
  The first simulated entry is the 14 April 2021 closing price.
- Cathie Wood / ARK Invest / Tesla, 19 March 2021: ARK's expected-value price
  target was USD 3,000 for 2025. The 25 August 2022 three-for-one split makes
  that USD 1,000 on the saved series' share basis. The original target stays
  visible in the description. Year-end 2025 is explicitly our evaluation
  convention for the model year, rather than an exact day attributed to ARK.
- Anthony Pompliano / Bitcoin, 24 June 2019: the original Pomp Letter gives
  a USD 100,000 target by 31 December 2021 and around 70-75% confidence. The case
  shows positive returns by that deadline while the target was not reached.
- Jim Cramer / Bear Stearns, 11 March 2008: a context-only record. The linked
  23 March CNN interview explains that the reassurance concerned broker-held
  customer funds. No share-price forecast, simulated equity return or tracker
  entry is inferred. A contemporary 17 March report corroborates the statement
  date; it is distinct from the linked interview's publication date.
- Nikola Motors: the retained original case, with the separate cancelled-share
  status and documented historical-price gap.
- Metahero, Kadena and MultiVAC: the three retained original crypto predictions,
  each with the supplied 10x target.

Home Depot, Lowe's, Crocs, Marvell, TSM and Micron were removed from the active
CSV. The original ten-row dataset is retained only in
`test_fixtures/original_predictions.csv`, with its price files, for regression
checks. Existing personal tracker records are not deleted.

These are hypothetical investments after the public statement, not reconstructions
of the creators' own trades, option positions or portfolio profit. Each case has
an original source link, a short excerpt and an explanation of its learning point.
Sources and verification notes are recorded in `case_sources.json`. Historical
follower/view counts are left blank rather than invented. Other examples retain
the supplied counts. The selected cases do not constitute a representative sample.

Saved Yahoo Finance chart observations were added for TSLA. All thirteen
pre-update price files remain byte-identical. The earlier release added GME
and COIN and prepended older rows to BTC-USD and SPY without changing any
existing observation. Current hashes are recorded in `project_info.json`.
Seven active cases have saved comparisons through 12 November 2026; Nikola
is status-only and Bear Stearns is context-only.

The Cathie record explicitly lists the reviewed split date and ratio. Target
evaluation proceeds only if those events exactly match the observed history;
unreviewed, mismatched or additional splits retain the manual-review guard.
This metadata and the evaluation convention survive saving to My Tracker.
The normal import/manual target calculation is unchanged.

All 119 tests pass, including active-case membership, source/date consistency,
split safety, context-only handling, stale database selection recovery, all nine
database views, tracker preservation and seven-case batch export. Automated
requests use saved data or simulated responses. Hosted rendering has not been
independently verified here.

## Crypto comparisons

Release `2026-11-14.11` shows other cryptocurrencies against both Bitcoin and
the S&P 500 ETF (SPY), simultaneously. The chart has three lines rebased to 100;
latest results, forecast-deadline results, period tables and downloads contain
separate returns and differences for each reference. Bitcoin itself uses SPY
only. Stocks and ETFs also use SPY. No benchmark selector is required.

All displayed series share the same entry date, observation dates and cutoff.
SPY non-trading dates are excluded from the paired return/drawdown observations.
Nominal crypto price targets still use the full asset history between entry and
cutoff/deadline, so a weekend target hit is retained. The original pairwise
return, horizon, drawdown and target functions are reused for each reference;
no new return formula is introduced.

`get_comparison_histories` loads the asset and references independently.
`analyse_comparisons` aligns them and calls the original pairwise analysis.
The app and batch exporter use this shared path. The legacy single-reference
`get_case_histories` and `analyse_case` functions remain available. If a reference
cannot be fetched, the app shows the available reference with an explicit
warning; it does not invent a missing line or difference. If neither reference
is available or common history is insufficient, no return is produced.

Old single-reference altcoin session results are discarded. Saved tracker facts
are not rewritten and automatically use the current comparisons when opened.
The source-import engine/cache stays at v8; the change needs no new TikTok
transcription. The release guard now covers case_analysis/charts as well.

The current suite includes ten dual-reference checks: three-series
alignment and arithmetic, both deadline differences, chart labels, a weekend
target hit, saved-data routing, missing-reference behavior, batch exports,
manual/import/tracker UI and old-result invalidation. Requests in automated
tests are simulated or use saved observations. Existing observations are
preserved; the special-case section documents the added price history. Hosted browser output has not been independently
verified here.

## My Tracker

Release `2026-11-14.9` removes the Backup / transfer section and its download,
upload and restore controls. The caption is simply "Saved in this browser."
Existing browser records and the optional manual source fields are retained.
The shared import engine/cache identity stays at v8 because this is a UI change.

Release `2026-11-14.8` adds a personal **My Tracker** area. **Track this
prediction** saves the selected, reviewed TikTok recommendation or the current
manual entry without calculating returns or requiring available market data.
Calculated curated examples can also be saved. Re-saving the same post and
asset updates its target/details instead of adding a duplicate; different posts
and assets stay separate. Manual entries include optional creator, source link
and prediction text so the stored tip can be identified later.

Records are stored in this browser's localStorage, without a login or new API
key/database service. They survive ordinary page refreshes and later visits on
the same app origin/browser. They do not automatically sync across devices or
browser profiles, and clearing site data removes them. The interface has no
backup, upload or transfer controls. Up to 100 predictions are supported. Browser storage errors are shown, and a save is
acknowledged only after the frontend confirms the write. The browser copy is
read before each update so unrelated records added by another tab are preserved;
another open tab loads fresh state on reload or its next save. This is a small
MVP store, without account-based sync or transactional multi-tab guarantees.

The saved record is a whitelist: asset, ticker/type, publication date, creator,
short prediction, original link, target/reference, time frame and saved time.
Curated split-review and evaluation-basis metadata are retained when present.
Video/audio/images, full transcripts/OCR, import reports, API keys and downloaded
price histories are excluded. These records are independent of the shared
24-hour source-import cache. No media is downloaded or transcribed when opening
a saved tip, and other visitors have their own browser lists.

My Tracker shows the saved list and the selected tip's comparison using the
existing return, benchmark, drawdown, horizon and price-target functions. It
requests current market history rather than the curated saved snapshot. Existing
one-hour price-request caching still applies; **Refresh prices** clears it.
There is no background polling or notification service. **Tracking** and
**Deadline reached** describe the stated horizon, not a correctness verdict.
A tip published today can be saved before any later daily close exists. Fewer
than two common closes produces a waiting state with no fabricated return.
Unavailable prices do not delete the saved tip. A selected tip can be removed.

`tracker_core.py` handles validated records and uses the existing analysis;
`tracker_ui.py` contains the Streamlit controls. A small native Streamlit v2
component (`tracker_storage.js`) bridges browser storage and Python using data
messages, without putting user content into HTML/JavaScript. Tests include
simulated AppTest storage/provider boundaries and a Node frontend contract test
for save/reopen, separate browser stores, removal and write failure. Internal
JSON-validation/merge helpers remain tested but have no exposed backup interface.
A real Chromium smoke test could not run in this execution sandbox (browser
socket creation was denied). Browser persistence on the deployed Streamlit
host has therefore not been independently verified here.

## Photo posts

Release `2026-11-14.7` accepts full TikTok links containing `/photo/` in the
same **Import TikTok** field. Press **Analyse post**. It reads every image
with English Tesseract OCR and adds the post caption, then sends that text to
the same Groq prediction model. It does not transcribe background music or
show/rehost the images. No additional API key or provider account is needed.

This path uses pinned `gallery-dl==1.32.20` for anonymous public post metadata
and supplied CDN image addresses. The prototype accepts up to 15 images,
8 MB per image, 50 MB total and 12,000 combined text characters. Oversized,
incomplete or unreadable imports stop with a message rather than returning
an unmarked partial carousel. Blocked public data is not bypassed with login,
cookies, proxies or automated challenges. Use full `/photo/` links; short
photo-share links have not been verified. Existing video/share handling remains.

**Extracted text** shows the caption and numbered image text. Multiple detected
picks use the same review selector, ticker lookup, editable fields and
comparison code as video picks. Supporting excerpts can refer to **Photo N**.
Publication dates come from platform metadata in UTC, not dates printed in
images. Shown stock prices and historical chart gains are not future targets.
The extraction prompt retains older forecasts as originally presented.

Photo files are temporary and removed even if processing fails. Only text and
safe metadata enter the existing source-result cache. Extraction retries and
**Check extraction again** reuse that text. Reports include source kind, photo
count, extracted text and actual model diagnostics without CDN image URLs.

The supplied drewhelpss photo post was fetched using this integrated reader:
all five images downloaded and OCR read PLTR, AVGO, SOUN and TSLA. Temporary
media cleanup was checked. The model/API and UI photo tests use explicitly
simulated responses. No new live Groq response or Streamlit-host photo retrieval
has been independently verified; public TikTok access remains host-dependent.

## ETF recommendations

Release 2026-11-14.6 fixes an overly narrow extraction scope. The supplied
v5 ETF report shows two successful requests returning empty arrays while the
system prompt explicitly allowed only individual stocks and crypto. ETFs
are now allowed in the prompt and schema, as a distinct ETF asset type in
import review, manual entry, CSV loading and Yahoo search suggestions.

A conservative source fallback recognizes literal ETF ticker introductions
within an explicit suggestion to buy/hold ETFs, including a later reference
to the previously shown ETF. It does not use a fixed list of fund symbols.
It excludes holding-company mentions, explicit negative advice and explicit
leveraged/inverse context; it invents no target from historical performance.
The recorded source now recovers XLE, XLV and SMH even when replaying its real
empty model response, with no extra API request. Other explicit ticker examples
(VYM/VTI) are tested as well. This is source recovery, not a new live model test.

Stocks and ETFs use SPY as the common comparison, rather than a category-specific
fund benchmark. USD currency and historical-coverage checks still apply.
Other crypto comparisons use both Bitcoin and SPY; Bitcoin itself uses SPY. Vague long-term wording has no
invented duration/deadline. Existing forecasts and calculations are retained.

## Request-format recovery

The supplied stockdads report fails before a model answer: the old code maps
HTTP 400 to a generic shorter-video message and discards the actual error body.
The report therefore does not establish why that particular request failed.
Release 2026-11-14.5 retains HTTP status and the provider code/type/message/
parameter/failed-generation fields in diagnostics, redacting the connection key.

A rejected chat request (HTTP 400 only) gets one alternate-format attempt with
the same Groq model and source, JSON Object Mode and lower reasoning effort.
The JSON schema is supplied in the prompt and validated locally with jsonschema
before any case is shown. A second rejection stops. Authentication, permission,
server and usage-limit errors do not trigger this switch. There is no extra
audio transcription, new provider or subscription change. This recovery is
independent of the video/stock names. Its live effect on the supplied failed
request has not been verified; test fallback outputs are explicitly simulated.

If a usage limit interrupts the alternate request, the source checkpoint and
chosen output mode are retained. A later user retry does not repeat the rejected
strict-format request or audio processing. The separately bounded empty-result
review can still run once, using the chosen output mode. Shared quotas apply to
all text calls. Raw error diagnostics are available even before speech succeeds.

The three requested method disclaimers were removed from the interface. The
saved-result sentence now uses the wording approved in the conversation.

## Approximate and conditional targets

The user's real v3 AMC report established that the stock and AMC ticker were
recognized, but the model returned no numeric target despite 'nearly a 6x'.
The recorded source and response are a credential-free regression fixture.
The prompt now explicitly supports conditional and approximate forecasts.
The `target_approximate` flag preserves that qualification in the review,
result and checked-case export.

`target_extraction.py` also recovers one clearly named future multiple for a
single identified asset if the model missed it, without another API call.
It preserves conditions and position-size wording, rejects valuation multiples,
past and teaching examples, and does not guess between assets or competing
scenarios or overwrite a conflicting target. The recorded AMC source recovers
approximately 6 times the stated USD 2.25 reference: an approximate USD 13.50
level, with no invented deadline. Currency remains subject to confirmation if
only a dollar sign is available. Other targets stay editable in review.

## Deploy online

The app is prepared for Streamlit Community Cloud. Visitors use its browser
link after deployment. Changes pushed to the connected branch update the app.

1. Open [Streamlit Community Cloud](https://share.streamlit.io/) and sign in with
   the GitHub account that owns this repository.
2. Allow Streamlit to access this private repository.
3. Select **Create app**, then **Yup, I have an app**.
4. Enter these settings:

| Setting | Value |
| --- | --- |
| Repository | `v42zrwmp8p-arch/reality-check` |
| Branch | `main` |
| Main file path | `app.py` |
| Python version, under Advanced settings | `3.12` |

5. Click **Deploy**. The curated and manual modes do not require an app API key.
   The TikTok import connection is configured separately below.
6. Use the app's sharing settings to choose its viewers. A private source
   repository does not require making the source code public to share the app.

The GitHub repository and the running app are separate: uploading the source
does not itself publish the website.

## Connect TikTok import

**Import TikTok** now uses direct public-post retrieval plus Groq. It has no
feature toggle, automatic expiry, Supadata requests or paid fallback provider.
The server transcribes speech with `whisper-large-v3-turbo`, reads sampled
on-screen text with Tesseract, and extracts structured predictions with
`openai/gpt-oss-20b`. Investment calculations remain in the original shared code.

Use a Groq **Free** account without enabling a paid upgrade/payment method. In
Streamlit Community Cloud, open **Settings → Secrets**, add this and save:

```toml
GROQ_API_KEY = "replace-with-your-groq-key"
```

After the new code is deployed, the old `SUPADATA_API_KEY` entry can be removed.
It is ignored by this version. Keep the actual key in Streamlit secrets, never
in GitHub or chat. Local use can read an untracked `.streamlit/secrets.toml` or
`GROQ_API_KEY` environment variable. Visitors do not need their own account.
The app cannot inspect your billing tier: a paid Groq account can incur usage
charges. The code never upgrades an account or changes billing settings.

Deployment installs Python dependencies from `requirements.txt` and FFmpeg /
Tesseract from `packages.txt`. This dependency change triggers a server rebuild.
On a local computer, install those system tools separately if using video import.

Paste a public TikTok video/photo link and press **Analyse post**. This prototype
supports completed clips up to three minutes and downloaded videos up to 50 MB.
It does not use login cookies, proxies or access-bypass mechanisms. TikTok may
reject requests from some hosting environments even when a link works elsewhere.
No supported recommendations produces an empty result, not an invented stock.

Extraction includes buy lists and bullish picks without a numeric target.
A small identifier registry can recover known name+ticker pairs explicitly
introduced as buy-list items. It does not treat customer/competitor mentions
as picks, invent an unnamed teaser, or supply price targets from an asset name.
An otherwise empty result receives one extra model check. This is bounded
and remains subject to the same Groq usage limits.

The analysis runs in a bounded background queue: two active tasks and up to
eight queued/running tasks. Progress is shown while it runs. A Groq usage limit
produces a waiting message, using the provider's retry time when supplied;
there is no retry loop. Only HTTP 400 chat requests receive the bounded
output-format switch described above. Press **Analyse post** again when available.
Successful transcription is retained as a checkpoint if prediction extraction
hits a limit, so that retry does not transcribe the same audio again.
Speech and prediction models have separate account-level quotas. Free does not
mean unlimited or guaranteed availability. Check current limits in your Groq
console and https://console.groq.com/docs/rate-limits.

Review one detected asset at a time. Publication dates come from post metadata
in UTC; creator handles come from the canonical post link when available,
with nonnumeric metadata as a fallback. Internal numeric account IDs are hidden.
Known identifiers, including Bitcoin -> BTC-USD, are filled independently of
the model. Similar spellings such as Marvel/Marvell require confirmation.
For other missing identifiers, a bounded Yahoo search offers candidates;
search failure leaves manual entry available. A search result is not silently
selected. A missing date or uncertain ticker must be completed by the user.
Numeric targets, currencies, reference prices and horizons stay editable. Vague
time frames retain their original wording without an invented deadline. Only
long stock/ETF/crypto comparisons and upside forecasts are supported in this version.

The transcript is available directly after analysis. OCR samples up to sixteen
frames with English text recognition. Small text, logos, briefly visible names
and complex graphics can be missed; this is not full visual video understanding.
The OCR text is not shown in the interface; the transcript remains available.
OCR failure does not prevent speech-only analysis.

Source-derived results for the same public post and connection are reused
across visitors in server memory for up to 24 hours, with at most 32 entries.
Concurrent requests for the same source share work. User corrections, checked
cases and market results stay session-local and are never written to that shared
source cache or to the curated CSV. Cache contents disappear on a server restart.
**Clear this import** clears the link, result and edits, not the shared
public-source cache. **Check extraction again** reuses the transcript/OCR and
reruns the extraction, without downloading or transcribing the same video
again. It is limited to one new run per 30 seconds per cached post/connection.
**Add a recommendation** creates a session-local editable item when a pick
was missed; it does not assert that the model found one. The engine version
changed so the previous version's cached failures are not reused.
Original video, audio, frame and photo files are temporary and deleted after processing,
including on failure. Groq's own data-processing policy applies separately.
A checked case can be downloaded as JSON; the app does not rehost videos or photos.

Direct video retrieval, audio conversion and 16-frame OCR were exercised on
the supplied 63-second Crocs/Marvell video in development. An intermediate
certificate-store problem was fixed by using the system trust store, without
disabling TLS verification. OCR found some but not all relevant names/numbers.
A real Groq request and deployment-host retrieval still require a live app check. API and
UI tests use labelled simulated provider responses, not a hidden real API key.
Technical integration does not establish copyright/platform/privacy permission.
The planned course prototype runs for two weeks; removal remains a later code change.

The import is isolated in `tiktok_import.py`, `asset_resolution.py`, `target_extraction.py`, `photo_import.py`, `video_pipeline.py` and
`tiktok_ui.py`. Removing its import, mode option and call from `app.py`, plus
these helper modules, removes the feature without reverting unrelated work.

## Add more examples

Edit `predictions.csv`, save it and reload the app. Use one row per public
source and asset. A new row's `case_id` can be blank to generate an ID from its video link
and symbol, or you can provide a unique ID. Different videos about the same
stock remain separate cases. There is no fixed ten-example limit.

Targets belong to individual recommendations: `target_type` is `none`, `price`
or `multiple`; `target_value` contains the price or factor. Multiples use
`reference_type=entry`, or `reference_type=creator` with a `reference_price`.
A 2x multiple
means a 100% price increase, and 10x means 900%. Curated table free-text claims are not parsed
for numerical targets. Existing `target_usd` inputs remain readable for legacy data.

An exact deadline can be recorded in `deadline`. Alternatively, supply
`horizon_value` and `horizon_unit` (days, weeks, months or years), measured from
publication.
Vague statements such as next few weeks are preserved without an invented date.

The collection has nine records. Seven have saved daily comparisons through
12 November 2026. Nikola Motors shows its cancellation outcome and historical
data gap. Bear Stearns is a context-only statement with no stock return.
Calculated examples work from their saved snapshot; new cases and
**Update prices** request data from Yahoo.

## Method

- The simulated entry is the first common daily close after publication.
- Investment returns use adjusted USD closing prices; all chart lines start at 100.
- Stocks, ETFs and Bitcoin use the S&P 500 ETF (SPY) as a comparison. Other
  crypto uses Bitcoin, which is not a broad crypto-market index. Comparisons
  use common observation dates; Bitcoin-versus-SPY excludes SPY non-trading dates.
- Holding periods are 1, 3, 6 and 12 months, then complete annual anniversaries,
  plus the latest common closing observation. Returns are cumulative from entry.
- Price targets are checked separately from dividend-adjusted investment returns.
- A covered forecast deadline is marked in the full-history chart, with the
  return and benchmark difference up to that date highlighted separately.
  Later observations remain visible. Future or uncovered deadlines are labelled
  without extending or estimating the price history.
- A forecast without a deadline is not declared false merely because a chosen
  observation period has ended. The ARK year-end evaluation convention is labelled
  separately from an exact creator deadline.
- The curated examples are illustrative and do not establish a creator ranking.

## Shared Python code

`analysis_core.py` contains the mathematical functions. `case_analysis.py`
combines them into a case result. Both `app.py` and `analyse_examples.py` use
these functions, so the same calculations can also be imported into a notebook.

## Optional local use

Tested with Python 3.12:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Generate CSV results or run focused checks:

```bash
python analyse_examples.py
python -m unittest test_iconic_cases.py test_special_cases.py test_dual_crypto.py test_bitcoin_benchmark.py test_tracker.py test_photo_import.py test_etf_import.py test_format_recovery.py test_target_extraction.py test_import_runtime.py test_mvp.py test_tiktok_import.py test_asset_resolution.py test_video_pipeline.py test_tiktok_ui.py
```

All nine curated views and the manual target/reference/deadline flows passed
Streamlit AppTest checks. The import has additional API-boundary and AppTest
checks with clearly labelled test fixtures. The table was tested with twenty records. Charts
with elapsed and future deadlines were rendered for visual inspection.
A live-browser QA pass was not available in the development environment. See `TEST_REPORT.txt` and
`README.txt` for details, and `NIKOLA_NOTES.txt` for the historical-source search.

The manual interface uses structured targets and an optional deadline. Its
optional source fields identify a saved tracker entry. `charts.py` supplies
the chart annotation.
