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

**Import TikTok** is a normal third app mode, with no feature toggle. It needs
a Supadata account and API key. In Streamlit Community Cloud, open your app's
**Settings → Secrets**, add the following and save:

```toml
SUPADATA_API_KEY = "replace-with-your-supadata-key"
```

Keep the actual key in Streamlit's secrets, not in GitHub or a chat message.
For local use, the same setting can go in an untracked `.streamlit/secrets.toml`
or the `SUPADATA_API_KEY` environment variable. Visitors need neither an API
key nor a Supadata account. Without the key, the new mode explains that its
connection is missing; the original two modes remain usable.

Paste a public TikTok video/share URL and press **Analyse video**. The server
requests platform metadata, then starts an audio/visual extraction job using an
explicit output schema. Processing progress is checked automatically while the
session is open. If a request fails or takes longer than three minutes,
**Check analysis progress** resumes that job rather than creating another one.
New import requests consume the project's provider credits. The adapter spaces
requests by at least 1.1 seconds; a shared provider quota can still be exhausted.

Review the detected recommendations and choose one asset at a time. Dates and
creator identity come from metadata; a missing date must be entered. Suggested
tickers, currencies, targets, reference prices and horizons remain editable.
Vague horizons do not acquire an invented deadline. This version supports long
stock/crypto comparisons and upside forecasts, not short/option strategies.
The checked case uses the existing shared investment calculations.

**Get transcript** is optional and consumes additional provider credits. It
uses existing captions where available and otherwise requests speech
transcription. It supports both immediate responses and processing jobs.
Extraction also considers visible text, so the investment draft does not rely
solely on audio or on the optional transcript.

Imports and transcripts are held in the current session, not written to the
curated CSV or shared disk cache. **Clear this import** removes the session
copy, including the displayed results and transcript. It does not cancel or
delete a job already held by Supadata, whose retention terms apply separately.
A checked case can be downloaded as JSON; the app does not rehost the video.

The integration has been tested with simulated API responses, not a live
Supadata account. Actual link access, extraction accuracy, account entitlement
and credit usage still require a real-key test. Technical integration does not
establish copyright, platform or data-protection permission for a given use.
The planned course prototype runs for two weeks; there is no automatic expiry.

The import is isolated in `tiktok_import.py` and `tiktok_ui.py`. To remove it
later, remove its import, mode option and call from `app.py`, then those two
modules and their tests. This preserves later changes to unrelated features.

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
python -m unittest test_mvp.py test_tiktok_import.py test_tiktok_ui.py
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
