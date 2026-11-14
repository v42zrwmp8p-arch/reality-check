"""Produce report-ready CSVs with the same functions used by the app.

Run: python analyse_examples.py (uses saved prices where they cover the case).
Run: python analyse_examples.py --refresh (requests current completed closes).
"""
from pathlib import Path
import json
import sys
import pandas as pd
from market_data import load_examples, get_case_histories
from case_analysis import analyse_case

ROOT = Path(__file__).resolve().parent


def main():
    folder = ROOT / "results"
    folder.mkdir(exist_ok=True)
    summaries, periods, states = [], [], []
    for row in load_examples():
        case_id = row["case_id"]
        if row["symbol"] in {"VTIQ / NKLA", "VTIQ", "NKLA", "NKLAQ"}:
            states.append({"case_id": case_id, "status": "Historical series incomplete; terminal share value USD 0 confirmed"})
            continue
        try:
            asset, benchmark, symbol, source = get_case_histories(row, force_live="--refresh" in sys.argv)
            summary, table, chart = analyse_case(row, asset, benchmark, symbol)
            out = folder / case_id
            out.mkdir(exist_ok=True)
            table.to_csv(out / "periods.csv", index=False)
            chart.to_csv(out / "chart_data.csv", index_label="Date")
            (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            summaries.append({k: v for k, v in summary.items() if k not in {"price_target", "deadline_result"}})
            periods.append(table.assign(case_id=case_id, symbol=row["symbol"]))
            states.append({"case_id": case_id, "status": "Calculated", "data_source": source})
        except Exception as exc:
            states.append({"case_id": case_id, "status": str(exc)})
    pd.DataFrame(summaries).to_csv(folder / "current_summary.csv", index=False)
    if periods:
        pd.concat(periods, ignore_index=True).to_csv(folder / "all_periods.csv", index=False)
    pd.DataFrame(states).to_csv(folder / "case_status.csv", index=False)
    print(f"Calculated {len(summaries)} of {len(states)} cases. Results: {folder}")


if __name__ == "__main__":
    main()
