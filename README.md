# Reality Check

A Python prototype that compares a TikTok investment recommendation with what
happened afterwards. Choose a curated example or enter a USD stock/crypto ticker
and publication date. The app shows a full-history chart, cumulative returns,
benchmark differences, drawdown and fixed holding periods.

## Deploy online

The app is prepared for Streamlit Community Cloud. Deployment has not yet been
completed. Visitors will use a browser link once it is deployed.

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

5. Click **Deploy**. No app API key or secrets file is required for this prototype.
6. Use the app's sharing settings to choose its viewers. A private source
   repository does not require making the source code public to share the app.

The GitHub repository and the running app are separate: uploading the source
does not itself publish the website.

## Add more examples

Edit `predictions.csv`, save it and reload the app. Use one row per video and
asset. A new row's `case_id` can be blank to generate an ID from its video link
and symbol, or you can provide a unique ID. Different videos about the same
stock remain separate cases. There is no fixed ten-example limit.

Known or derived numeric price targets belong to individual records through
`target_usd` and `target_basis`; they are not inherited by other videos about
the same stock. Optional deadlines can be recorded in a `deadline` column.

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
python -m unittest test_mvp.py
```

All ten views and a real manual AAPL request passed Streamlit AppTest checks.
The expandable table was tested with twenty records. A visual browser QA pass
was not available in the development environment. See `TEST_REPORT.txt` and
`README.txt` for details, and `NIKOLA_NOTES.txt` for the historical-source search.
