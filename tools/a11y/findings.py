"""Accessibility findings: one format for every checker, plus the ratchet baseline.

Each checker (lint_latex, lint_pptx, check_pdf, check_html, ...) writes a JSON list of
findings. A finding is counted under a *stable key* (tool | file | rule | where) that
does not change with unrelated edits: no line numbers, only things like a slide id and
picture id, a page path or a validation rule. `where` is empty when the finding is a
count over a whole file.

The ratchet: a11y-baseline.json records the accepted count per key (the backlog). A run
fails only when an error-severity key is new or its count went up. Fixing problems and
running `run_all.py --update-baseline` lowers the counts; the baseline can only shrink
unless someone deliberately accepts new problems with `--accept-new`.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "a11y-baseline.json"


@dataclass
class Finding:
    tool: str
    file: str  # repo-relative path (or published path for built HTML/PDF)
    rule: str
    message: str
    where: str = ""  # stable locator inside the file; "" = counted over the whole file
    severity: str = "error"  # "error" gates CI; "warning" is only reported
    count: int = 1

    @property
    def key(self):
        return " | ".join((self.tool, self.file, self.rule, self.where))


def write(findings, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps([asdict(f) for f in merge(findings)], indent=1) + "\n")


def read(path):
    return [Finding(**d) for d in json.loads(Path(path).read_text())]


def merge(findings):
    """Combine findings with the same key, adding their counts."""
    out = {}
    for f in findings:
        if f.key in out:
            out[f.key].count += f.count
        else:
            out[f.key] = Finding(**asdict(f))
    return sorted(out.values(), key=lambda f: (f.tool, f.file, f.rule, f.where))


def load_baseline():
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text())["accepted"]


def save_baseline(counts):
    BASELINE.write_text(
        json.dumps(
            {
                "about": "Accepted accessibility backlog (tools/a11y). Counts may only go down; "
                "regenerate with `uv run tools/a11y/run_all.py --update-baseline`.",
                "accepted": dict(sorted(counts.items())),
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n"
    )


def compare(findings, baseline, tools=None):
    """Return (regressions, improved_keys) for error findings against the baseline.

    `tools` limits the comparison to the tools that actually ran, so a partial run
    (e.g. the pre-commit hook running only the linters) never reports other tools'
    baseline entries as fixed."""
    errors = [f for f in findings if f.severity == "error"]
    current = {f.key: f for f in errors}
    regressions = [f for f in errors if f.count > baseline.get(f.key, 0)]
    improved = [k for k in baseline if (tools is None or k.split(" | ")[0] in tools) and k not in current]
    improved += [k for k, f in current.items() if k in baseline and f.count < baseline[k]]
    return regressions, sorted(set(improved))


def updated_baseline(findings, baseline, tools, accept_new=False):
    """Lower counts to what is current (never raise them unless accept_new)."""
    current = {f.key: f.count for f in findings if f.severity == "error"}
    out = {k: n for k, n in baseline.items() if k.split(" | ")[0] not in tools}
    for k, n in current.items():
        if k in baseline:
            out[k] = min(n, baseline[k]) if not accept_new else n
        elif accept_new:
            out[k] = n
    return out


def source_file(path):
    """Repo file a finding belongs to: built outputs (Homeworks/HW1.pdf, .html) map to
    the source they are built from (.tex, or .pptx for slide PDFs)."""
    if (REPO / path).is_file():
        return path
    stem = path.rsplit(".", 1)[0]
    for ext in (".tex", ".pptx"):
        if (REPO / (stem + ext)).is_file():
            return stem + ext
    return path


def sarif(findings, baseline):
    """SARIF 2.1.0 log for GitHub code scanning: alerts on the files, and on pull
    requests only the alerts a change introduces. Each alert is fingerprinted by its
    stable key, so it is tracked across commits like the baseline is. Findings already
    accepted in the baseline are reported as notes."""
    rules, results = {}, []
    for f in findings:
        rules.setdefault(
            f.rule,
            {
                "id": f.rule,
                "name": f.rule.replace("/", "-"),
                "shortDescription": {"text": f.rule},
                "properties": {"tags": ["accessibility", f.tool]},
            },
        )
        accepted = f.severity == "error" and f.count <= baseline.get(f.key, 0)
        where = f" ({f.where})" if f.where else ""
        count = f" x{f.count}" if f.count > 1 else ""
        results.append(
            {
                "ruleId": f.rule,
                "level": "note" if accepted else f.severity,
                "message": {"text": f"{f.message}{where}{count}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": source_file(f.file), "uriBaseId": "%SRCROOT%"},
                            "region": {"startLine": 1},
                        }
                    }
                ],
                "partialFingerprints": {"a11yKey/v1": hashlib.sha256(f.key.encode()).hexdigest()},
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "se423-a11y",
                        "informationUri": "https://github.com/Marius-Juston/SE-423---Class-Material/tree/main/tools/a11y",
                        "rules": sorted(rules.values(), key=lambda r: r["id"]),
                    }
                },
                "results": results,
            }
        ],
    }


def summary_markdown(findings, regressions, improved):
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    lines = ["## Accessibility", ""]
    if regressions:
        lines += [f"**{len(regressions)} new problem(s)** (not in the baseline):", ""]
        lines += [
            f"- `{f.file}` {f.rule} {('@ ' + f.where) if f.where else ''}: {f.message} (x{f.count})"
            for f in regressions
        ]
        lines.append("")
    else:
        lines += ["No new problems.", ""]
    by_tool = {}
    for f in errors:
        by_tool.setdefault(f.tool, 0)
        by_tool[f.tool] += f.count
    lines += ["| Checker | Open errors | Warnings |", "|---|---:|---:|"]
    for tool in sorted({f.tool for f in findings}):
        w = sum(f.count for f in warnings if f.tool == tool)
        lines.append(f"| {tool} | {by_tool.get(tool, 0)} | {w} |")
    lines.append("")
    if improved:
        lines += [
            f"{len(improved)} baseline item(s) improved; run `uv run tools/a11y/run_all.py --update-baseline` "
            "and commit `a11y-baseline.json` to lock that in.",
            "",
        ]
    by_file = {}
    for f in errors:
        by_file.setdefault(f.file, 0)
        by_file[f.file] += f.count
    if by_file:
        lines += ["<details><summary>Open errors by file</summary>", "", "| File | Errors |", "|---|---:|"]
        lines += [f"| `{k}` | {v} |" for k, v in sorted(by_file.items(), key=lambda kv: -kv[1])]
        lines += ["", "</details>", ""]
    return "\n".join(lines)
