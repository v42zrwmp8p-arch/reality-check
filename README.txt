REALITY CHECK - STREAMLIT MVP

What is included
A local Python app with two flows: curated TikTok examples and manual input.
Nine of the ten curated assets have daily-price comparisons. Nikola remains
visible with a documented cancellation outcome and an explicit historical gap.

The layout is intentionally simple: recommendation, full-period chart, four
metrics, fixed-horizon table and a separate price-target check. No videos are
uploaded, transcribed or rehosted by this version.

Start
python -m pip install -r requirements.txt
python -m streamlit run app.py

Tested with Python 3.12. See START_HERE.txt for a short German introduction.
The source can also run on Streamlit Community Cloud. See README.md for the
repository settings. Visitors then use the deployed app's browser link.

Add more examples without rebuilding the app
Edit predictions.csv, save it and reload the page. The app reads every row.
There is no fixed limit of ten examples and no hard-coded list in the interface.

Use one row per video and asset. Two different videos about the same stock are
separate cases, with independent dates, claims, targets and results.

Required columns
creator, publication_date, asset, symbol, asset_type, projection, time_frame,
video_url

Useful optional columns
- case_id: a unique identifier. Leave blank for new rows to generate it from the
  video identifier and asset symbol. Use letters/numbers, dots, underscores and
  hyphens, with no spaces or slashes. Do not copy an existing case_id unchanged.
- followers and video_views: plain numbers such as 226000, or blank if unknown.
- provider_symbols: the Yahoo Finance ticker; if blank, symbol is used.
- target_type: none, price or multiple.
- target_value: the USD price or upside factor, such as 2 or 10.
- reference_type: entry or creator for a multiple.
- reference_price: the positive USD creator reference when reference_type=creator.
- target_basis: a short source explanation of the stated or derived target.
- deadline: an optional ISO end date, with or without a numeric target.
- horizon_value and horizon_unit: optional whole-number duration from publication,
  using days, weeks, months or years. An explicit deadline takes precedence.
Legacy target_usd inputs remain readable, but the supplied CSV uses the explicit
target_type/target_value structure.

Dates use YYYY-MM-DD. Asset type is Equity or Crypto. Use valid CSV quoting for
text containing commas; a spreadsheet editor can handle this. Missing engagement
counts and forecasts stay blank/unspecified, not zero.

Targets belong to individual recommendations. A new Marvell case does not
inherit the USD 142 target from the existing video. Free-text predictions are
not interpreted as numerical targets. The manual form uses explicit target type,
value, reference and optional deadline, without Creator, Video link or Claim fields.
In the supplied records, Crocs' USD 318 target is explicitly derived from
3 times the creator's USD 106 reference. The three crypto 10x claims use ten
times the actual entry close as a disclosed convention because the notes do not
provide a reference price.

Data and refresh
The saved daily prices cover the nine successful original assets, plus SPY and
Bitcoin, through 12 November 2026. No new downloads are required for those
curated examples unless Update prices is selected.

For a new case, the app uses a saved history only if it covers the entry date.
Otherwise it requests asset and benchmark histories from Yahoo using yfinance.
New manual requests use current downloads. Downloads are cached in memory for
up to one hour; Update prices clears that cache. Current, unfinished daily
observations are excluded. The actual last common closing date is always shown.

The first version supports USD listings/ADRs and USD crypto pairs. New download
currency is checked; a non-USD instrument is not silently compared with a USD
benchmark. Historical coverage remains provider-dependent, particularly for
delisted stocks and smaller tokens. Request failures show a message, not a
fabricated zero return.

Crypto Yahoo identifiers: HERO -> HERO10778-USD; KDA -> KDA-USD; MTV -> MTV-USD.
Other crypto symbols can use their full Yahoo USD ticker, such as BTC-USD.

Method
- Enter at the first common daily close strictly after publication. A history
  beginning more than seven days after publication is rejected for this entry.
- Use adjusted closing prices for investment returns and normalization to 100.
- Return = final value / entry value - 1.
- Benchmark difference = asset return minus benchmark return, in percentage points.
- Largest fall = maximum daily closing-price drawdown from an earlier peak.
- Equities use SPY, an ETF proxy for broad US equities. Crypto uses Bitcoin as
  a comparison asset, not a broad crypto-market index. Crypto weekends remain.
- Show 1, 3, 6 and 12 months, then elapsed annual anniversaries, plus the latest
  available common close. Returns are cumulative from the original entry.
- If an anniversary is not observed, use the previous common closing observation.
- Share-price targets use daily highs and closes separately from dividend-adjusted
  returns. Entry-day intraday highs before the simulated close are not counted.
- Numeric targets require manual review when split events appear after entry,
  including splits after a stated deadline that affect the downloaded price basis.
- An absent deadline stays absent. A target not reached by the cutoff is not
  automatically a false forecast. A specific entered deadline limits the target
  test; the investment chart still shows the full available history.
- A covered deadline is marked with a vertical chart line and the returns up to
  that deadline are highlighted. A weekend deadline uses the previous common
  close, labelled with its actual date. The full later history stays visible.
- The stated ten-year horizons for TSM and Micron resolve to 21 December 2034
  and are still running. Uncovered/future deadlines have no fabricated return
  and do not extend the price chart. Vague horizons are not given exact dates.
- This is a small curated collection, not a creator ranking or representative
  survey. Original notes are not claimed as independently checked transcripts.
- Trading costs and investor-specific taxes are excluded.

Nikola
See NIKOLA_NOTES.txt and nikola_status.json. The historical series from the May
2020 video remains incomplete. FINRA confirms cancellation without a distribution
for existing equity interests. The app shows terminal share value USD 0 separately;
it does not fabricate period returns or a continuous historical price chart.

Shared code
app.py                 Streamlit interface
market_data.py         Example-table loading, symbol handling and price retrieval
case_analysis.py       Combines the data into one case's results
analysis_core.py       Return, drawdown, horizon and explicit target functions
charts.py              Full-history chart and covered-deadline annotations
analyse_examples.py    Batch CSV/JSON outputs using the same functions as the app
predictions.csv        Expandable curated database
prices/*.csv           Original saved daily observations
test_mvp.py            Focused checks of calculations and adding more examples

The same functions can be imported into the report notebook. A final notebook
and the course's PDF deliverable have not been created in this MVP step.

Reproduce CSV results
python analyse_examples.py
python analyse_examples.py --refresh

Run focused checks
python -m unittest test_mvp.py

Validation
All ten curated views passed Streamlit AppTest checks. The nine price cases
display four metrics and a horizon table; Nikola displays its separate status.
Invalid ticker/target inputs and a real AAPL download were also tested.
Explicit 2x/10x targets, creator reference prices, absolute targets and optional
deadlines were checked through the manual interface using saved market data.
Charts with elapsed and future deadlines were rendered for visual inspection.
The integrated browser-preview infrastructure was unavailable, so a live
browser QA pass has not been completed in this environment.

Sources
User-supplied TikTok Financial Advice.docx and structured example table.
Market data: Yahoo Finance via yfinance.
https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
https://docs.streamlit.io/develop/api-reference
https://www.finra.org/sites/default/files/2025-12/UPC-125-2025-NKLAQ.pdf
