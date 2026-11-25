"""Render a standalone, offline HTML dashboard from the SQLite audit history."""
import argparse
from html import escape
from pathlib import Path
from readiness_history import recent


def render(runs, dataset):
    def safe(value):
        return escape(str(value), quote=True)

    def pct(value):
        return "-" if value is None else f"{value:.1%}"

    rows = []
    for report in runs:
        status = "PASS" if report["passed"] else "FAIL"
        violation_text = ", ".join(f"{key}: {value}" for key, value in sorted(report["violations"].items()))
        drift = report.get("drift", {})
        drift_text = drift.get("status", "not monitored")
        if drift.get("overridden_violations"):
            drift_text += " (approved threshold override)"
        distances = drift.get("distribution_distance", {})
        max_distance = max(distances.values()) if distances else None
        rows.append(
            "<tr>"
            f"<td>{safe(report['run_id'])}</td><td>{safe(report['evaluated_at'])}</td>"
            f"<td>{safe(report['contract_version'])}</td>"
            f"<td class='{status.lower()}'>{status}</td><td>{report['rows']:,}</td>"
            f"<td>{pct(report['row_pass_rate'])}</td><td>{safe(drift_text)}</td>"
            f"<td>{pct(drift.get('row_change'))}</td><td>{pct(max_distance)}</td>"
            f"<td>{safe(violation_text or '-')}</td></tr>"
        )
    failures = sum(not run["passed"] for run in runs)
    latest = runs[0] if runs else None
    latest_status = "PASS" if latest and latest["passed"] else ("FAIL" if latest else "No runs")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data readiness: {safe(dataset)}</title>
<style>
body{{font:15px system-ui,sans-serif;background:#f5f7fa;color:#162c44;margin:32px}}
h1{{font-size:28px;margin-bottom:4px}} .muted{{color:#546879}}
.cards{{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}}
.card{{background:white;border:1px solid #cbd5e1;padding:16px;min-width:140px;border-radius:8px}}
.card b{{display:block;font-size:24px;margin-top:8px}}
.table{{overflow:auto;background:white;border:1px solid #cbd5e1;border-radius:8px}}
table{{border-collapse:collapse;width:100%;text-align:left}} th,td{{padding:12px;border-bottom:1px solid #e2e8f0}}
th{{background:#e5edf5;white-space:nowrap}} .pass{{color:#12603d;font-weight:bold}}
.fail{{color:#a61b1b;font-weight:bold}} td{{vertical-align:top}}
</style></head><body>
<h1>Data readiness � {safe(dataset)}</h1>
<p class="muted">Latest recorded runs. Row pass rate excludes batch-level and drift violations.</p>
<div class="cards">
<div class="card">Recorded runs<b>{len(runs)}</b></div>
<div class="card">Failed runs<b>{failures}</b></div>
<div class="card">Latest gate<b>{latest_status}</b></div>
<div class="card">Gate pass rate<b>{pct((len(runs)-failures)/len(runs) if runs else None)}</b></div>
</div>
<h2>Run history</h2>
<div class="table"><table><thead><tr><th>Run</th><th>UTC time</th><th>Contract</th><th>Gate</th>
<th>Rows</th><th>Row pass</th><th>Baseline</th><th>Row change</th><th>Max drift</th><th>Violations</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="muted">Distribution distance is total variation (0-100%). This report includes aggregates and rule labels, not raw records.</p>
</body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history")
    parser.add_argument("dataset")
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    html = render(recent(args.history, args.dataset, args.limit), args.dataset)
    with args.output.open("x", encoding="utf-8") as target:
        target.write(html)


if __name__ == "__main__":
    main()
