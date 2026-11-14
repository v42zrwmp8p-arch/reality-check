"""The full observed history, with a forecast-deadline marker when covered."""
import altair as alt
import pandas as pd


def comparison_chart(normalized, asset_label, benchmark_label, deadline_result):
    data = normalized.rename(columns={"Asset": asset_label, "Benchmark": benchmark_label}).copy()
    data.index.name = "Date"
    long = data.reset_index().melt("Date", var_name="Series", value_name="Value")
    long["Date"] = long["Date"].dt.strftime("%Y-%m-%d")
    color = alt.Color("Series:N", scale=alt.Scale(domain=[asset_label, benchmark_label],
                      range=["#23685A", "#8A8D8B"]), legend=alt.Legend(title=None, orient="top"))
    base = alt.Chart(alt.Data(values=long.to_dict("records"))).encode(
        x=alt.X("Date:T", title="Date", scale=alt.Scale(type="utc"),
                axis=alt.Axis(tickCount=7, format="%b %Y", labelOverlap=True)),
        y=alt.Y("Value:Q", title="Value at entry = 100", scale=alt.Scale(zero=False)),
        color=color,
        tooltip=[alt.Tooltip("Date:T", title="Closing date", format="%d %b %Y"),
                 "Series:N", alt.Tooltip("Value:Q", format=".2f")])
    layers = [base.mark_line(strokeWidth=2)]
    if deadline_result.get("status") == "elapsed":
        deadline = deadline_result["deadline"]
        observation = deadline_result["observation_date"]
        marker = alt.Data(values=[{"Date": deadline, "Label": "Forecast deadline"}])
        layers.append(alt.Chart(marker).mark_rule(color="#343B37", strokeDash=[6, 4]).encode(x="Date:T"))
        right_half = pd.Timestamp(deadline) > normalized.index[0] + (normalized.index[-1] - normalized.index[0]) / 2
        layers.append(alt.Chart(marker).mark_text(align="right" if right_half else "left",
                      dx=-6 if right_half else 6, fontSize=11, color="#343B37").encode(
                          x="Date:T", y=alt.value(12), text="Label:N"))
        points = long.loc[long["Date"] == observation]
        layers.append(alt.Chart(alt.Data(values=points.to_dict("records"))).mark_point(filled=True, size=75).encode(
            x="Date:T", y="Value:Q", color=color,
            tooltip=[alt.Tooltip("Date:T", title="Observed close", format="%d %b %Y"),
                     "Series:N", alt.Tooltip("Value:Q", format=".2f")]))
    return alt.layer(*layers).properties(height=370)
