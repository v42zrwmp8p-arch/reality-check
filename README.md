# Reality Check

A Python prototype that compares a TikTok investment recommendation with what
happened afterwards. Choose a curated example, enter a USD stock/crypto ticker
and publication date, or import a public TikTok link for review. The app shows a full-history chart, cumulative returns,
benchmark differences, drawdown and fixed holding periods.

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

**Import TikTok** now uses direct public-video retrieval plus Groq. It has no
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

Paste a public TikTok video/share URL and press **Analyse video**. This prototype
supports completed clips up to three minutes and downloaded videos up to 50 MB.
It does not use login cookies, proxies or access-bypass mechanisms. TikTok may
reject requests from some hosting environments even when a link works elsewhere.
No supported recommendations produces an empty result, not an invented stock.

The analysis runs in a bounded background queue: two active tasks and up to
eight queued/running tasks. Progress is shown while it runs. A Groq usage limit
produces a waiting message, using the provider's retry time when supplied;
there is no automatic retry loop. Press **Analyse video** again when available.
Successful transcription is retained as a checkpoint if prediction extraction
hits a limit, so that retry does not transcribe the same audio again.
Speech and prediction models have separate account-level quotas. Free does not
mean unlimited or guaranteed availability. Check current limits in your Groq
console and https://console.groq.com/docs/rate-limits.

Review one detected asset at a time. Dates/creator identity come from video
metadata. A missing date or uncertain ticker must be completed by the user.
Numeric targets, currencies, reference prices and horizons stay editable. Vague
time frames retain their original wording without an invented deadline. Only
long stock/crypto comparisons and upside forecasts are supported in this version.

The transcript is available directly after analysis. OCR samples up to sixteen
frames with English text recognition. Small text, logos, briefly visible names
and complex graphics can be missed; this is not full visual video understanding.
If OCR fails, the interface clearly says the result uses speech only.

Source-derived results for the same public video and connection are reused
across visitors in server memory for up to 24 hours, with at most 32 entries.
Concurrent requests for the same source share work. User corrections, checked
cases and market results stay session-local and are never written to that shared
source cache or to the curated CSV. Cache contents disappear on a server restart.
**Clear this import** clears your view/edits, not the shared public-source cache.
Original video, audio and frame files are temporary and deleted after processing,
including on failure. Groq's own data-processing policy applies separately.
A checked case can be downloaded as JSON; the app does not rehost videos.

Direct video retrieval, audio conversion and 16-frame OCR were exercised on
the supplied 63-second Crocs/Marvell video in development. An intermediate
certificate-store problem was fixed by using the system trust store, without
disabling TLS verification. OCR found some but not all relevant names/numbers.
A real Groq request and deployment-host retrieval still require a live app check. API and
UI tests use labelled simulated provider responses, not a hidden real API key.
Technical integration does not establish copyright/platform/privacy permission.
The planned course prototype runs for two weeks; removal remains a later code change.

The import is isolated in `tiktok_import.py`, `video_pipeline.py` and
`tiktok_ui.py`. Removing its import, mode option and call from `app.py`, plus
these helper modules, removes the feature without reverting unrelated work.

## Add more examples

Edit `predictions.csv`, save it and reload the app. Use one row per video and
asset. A new row's `case_id` can be blank to generate an ID from its video link
and symbol, or you can provide a unique ID. Different videos about the same
stock remain separate cases. There is no fixed ten-example limit.

Targets belong to individual recommendations: `target_type` is `none`, `price`
or `multiple`; `target_value` contains the price or factor. Multiples use
`reference_type=entry`, or `reference_type=creator` with a `reference_price`.
For example, the Crocs record uses 3 times a USD 106 reference. A 2x multiple
means a 100% price increase, and 10x means 900%. Free-text claims are not parsed
for numerical targets. Existing `target_usd` inputs remain readable for legacy data.

An exact deadline can be recorded in `deadline`. Alternatively, supply
`horizon_value` and `horizon_unit` (days, weeks, months or years), measured from
publication. The ten-year TSM/Micron horizons resolve to 21 December 2034.
Vague statements such as next few weeks are preserved without an invented date.

The initial collection has ten records. Nine have saved daily price histories
through 12 November 2026. Nikola remains visible with a documented cancellation
outcome and a clearly labelled historical-data gap. Existing examples work from
their saved snapshot; new cases and **Update prices** request data from Yahoo.

## Method

- The simulated entry is the first common daily close after publication.
- Investment returns use adjusted USD closing prices; both chart lines start at 100.
- Equities use SPY as a broad US equity ETF comparison. Crypto uses Bitcoin,
  which is a comparison asset rather than a broad crypto-market index.
- Holding periods are 1, 3, 6 and 12 months, then complete annual anniversaries,
  plus the latest common closing observation. Returns are cumulative from entry.
- Price targets are checked separately from dividend-adjusted investment returns.
- A covered forecast deadline is marked in the full-history chart, with the
  return and benchmark difference up to that date highlighted separately.
  Later observations remain visible. Future or uncovered deadlines are labelled
  without extending or estimating the price history.
- A forecast without a deadline is not declared false merely because a chosen
  observation period has ended. The ten-year TSM and Micron horizons are still running.
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
python -m unittest test_mvp.py test_tiktok_import.py test_video_pipeline.py test_tiktok_ui.py
```

All ten curated views and the manual target/reference/deadline flows passed
Streamlit AppTest checks. The import has additional API-boundary and AppTest
checks with clearly labelled test fixtures. The table was tested with twenty records. Charts
with elapsed and future deadlines were rendered for visual inspection.
A live-browser QA pass was not available in the development environment. See `TEST_REPORT.txt` and
`README.txt` for details, and `NIKOLA_NOTES.txt` for the historical-source search.

The manual interface uses structured targets and an optional deadline. Creator,
video link and free-text claim fields are retained in curated records rather
than requested in the manual form. `charts.py` supplies the chart annotation.
