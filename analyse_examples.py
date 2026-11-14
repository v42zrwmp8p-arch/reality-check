"""Produce report-ready CSVs with the same functions used by the app.

Run: python analyse_examples.py (uses saved prices where they cover the case).
Run: python analyse_examples.py --refresh (requests current completed closes).
"""
from pathlib import Path
import json
import sys
import pandas as pd
from market_data import load_examples, get_comparison_histories
from case_analysis import analyse_comparisons

ROOT = Path(__file__).resolve().parent


def main():
    folder = ROOT / "results"
    folder.mkdir(exist_ok=True)
    summaries, periods, states = [], [], []
    for row in load_examples():
        case_id = row["case_id"]
        if row.get("case_type") == "context":
            states.append({"case_id": case_id, "status": "Context case; no share-price return calculated"})
            continue
        if row["symbol"] in {"VTIQ / NKLA", "VTIQ", "NKLA", "NKLAQ"}:
            states.append({"case_id": case_id, "status": "Historical series incomplete; terminal share value USD 0 confirmed"})
            continue
        try:
            data = get_comparison_histories(row, force_live="--refresh" in sys.argv)
            summary, table, chart = analyse_comparisons(row, data)
            out = folder / case_id
            out.mkdir(exist_ok=True)
            table.to_csv(out / "periods.csv", index=False)
            chart.to_csv(out / "chart_data.csv", index_label="Date")
            (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            flat = {k: v for k, v in summary.items() if k not in {"price_target", "deadline_result", "comparisons", "requested_benchmark_symbols", "unavailable_benchmarks"}}
            target = summary["price_target"]
            close = target.get("close_comparison") or {}
            flat.update(target_usd=target.get("target_usd"), target_status=target["status"],
                        target_close_date=close.get("date"), target_close_usd=close.get("close_usd"),
                        target_difference_usd=close.get("difference_usd"),
                        target_difference_pct=close.get("difference_pct"))
            for symbol, values in summary["comparisons"].items():
                flat[symbol + "_return_pct"] = values["return_pct"]
                flat["difference_vs_" + symbol + "_pp"] = values["difference_pp"]
            summaries.append(flat)
            periods.append(table.assign(case_id=case_id, symbol=row["symbol"]))
            states.append({"case_id": case_id, "status": "Calculated", "data_source": data["source"]})
        except Exception as exc:
            states.append({"case_id": case_id, "status": str(exc)})
    pd.DataFrame(summaries).to_csv(folder / "current_summary.csv", index=False)
    if periods:
        pd.concat(periods, ignore_index=True).to_csv(folder / "all_periods.csv", index=False)
    pd.DataFrame(states).to_csv(folder / "case_status.csv", index=False)
    print(f"Calculated {len(summaries)} of {len(states)} cases. Results: {folder}")


if __name__ == "__main__":
    main()
