#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "14 days"  # only releases at least two weeks old (supply-chain cooldown)
# ///
"""Validate PDFs against PDF/UA-2 with veraPDF.

    uv run tools/a11y/check_pdf.py --root build [--json OUT] [PDF ...]

Without PDF arguments, every *.pdf under --root is checked except the standalone
TikZ figures (Lectures/Figures). Paths in the findings are relative to --root, so
build/Homeworks/HW2.pdf is reported as Homeworks/HW2.pdf.

veraPDF comes from $VERAPDF, a `verapdf` on the PATH, or (with --docker) the pinned
verapdf/cli image. One finding per (document, failed rule), counting failed checks.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from findings import Finding, write  # noqa: E402

# Pinned by digest as well as tag: a re-pushed tag cannot change what runs.
DOCKER_IMAGE = "verapdf/cli:v1.30.2@sha256:d5ee329657cf9bc4b2400392dd54c7d0a0ce9980ff6fa2da5590eebeec007cdb"


def verapdf_cmd(use_docker, root):
    if use_docker:
        return [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{root.resolve()}:/data",
            DOCKER_IMAGE,
        ], lambda p: f"/data/{p.relative_to(root).as_posix()}"
    exe = os.environ.get("VERAPDF") or shutil.which("verapdf")
    if not exe:
        sys.exit("veraPDF not found: set VERAPDF, put verapdf on the PATH, or pass --docker")
    return [exe], lambda p: str(p)


# Slide PDFs come from LibreOffice, which exports PDF/UA-1 (not UA-2): they are validated
# against ua1 and reported only, since exact counts depend on the LibreOffice version.
REPORT_ONLY = ("Lectures/Slides/",)
PROCESSES = max(1, min(4, os.cpu_count() or 1))  # files validated in parallel per run


def jobs_of(stdout):
    """veraPDF's per-file jobs: one report (single process) or a list (--processes)."""
    data = json.loads(stdout)
    reports = data["reports"] if "reports" in data else [data]
    return [job for rep in reports for job in rep["report"]["jobs"]]


def findings_for(rel, job, sev):
    result = job.get("validationResult")
    result = result[0] if isinstance(result, list) and result else result
    if not result:
        return [
            Finding(
                "pdf",
                rel,
                "pdf/not-validated",
                "veraPDF returned no result (unreadable or encrypted PDF?)",
                severity=sev,
            )
        ]
    out = []
    for rule in result["details"].get("ruleSummaries", []):
        if rule.get("status") == "failed" or rule.get("failedChecks"):
            rid = f"pdf/{rule.get('specification', 'ISO 14289-2')} {rule.get('clause')}-{rule.get('testNumber')}"
            out.append(
                Finding(
                    "pdf",
                    rel,
                    rid,
                    rule.get("description", "")[:200],
                    severity=sev,
                    count=int(rule.get("failedChecks") or 1),
                )
            )
    return out


VERAPDF_TIMEOUT = 20 * 60  # s per veraPDF run; a hang becomes a pdf/not-validated finding


def validate(cmd, by_name, sev):
    """Run one veraPDF command over the files in by_name ({path as veraPDF sees it: rel})."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=VERAPDF_TIMEOUT)
        jobs, detail = jobs_of(r.stdout), (r.stderr or r.stdout)[-200:]
    except subprocess.TimeoutExpired:
        jobs, detail = [], f"veraPDF did not finish within {VERAPDF_TIMEOUT // 60} min"
    except (ValueError, KeyError, TypeError):
        jobs, detail = [], (r.stderr or r.stdout)[-200:]
    out, seen = [], set()
    for job in jobs:
        rel = by_name.get(job.get("itemDetails", {}).get("name"))
        if rel is not None:
            seen.add(rel)
            out += findings_for(rel, job, sev)
    for rel in sorted(set(by_name.values()) - seen):
        out.append(
            Finding("pdf", rel, "pdf/not-validated", f"veraPDF could not validate the file: {detail}", severity=sev)
        )
    return out


def check(pdfs, root, use_docker):
    """Few veraPDF runs instead of one per file (each run starts a JVM, with --docker a
    container too). Natively, one run per flavour with --processes; in Docker the files
    are split over PROCESSES containers run side by side (veraPDF's own --processes
    spawns child JVMs, which hung inside the container)."""
    base, path_of = verapdf_cmd(use_docker, root)
    groups = {}
    for pdf in pdfs:
        rel = pdf.relative_to(root).as_posix()
        groups.setdefault("ua1" if rel.startswith(REPORT_ONLY) else "ua2", []).append(pdf)
    runs = []
    for flavour, group in groups.items():
        sev = "warning" if flavour == "ua1" else "error"
        chunks = [group[i::PROCESSES] for i in range(PROCESSES)] if use_docker else [group]
        for chunk in filter(None, chunks):
            by_name = {path_of(pdf): pdf.relative_to(root).as_posix() for pdf in chunk}
            extra = [] if use_docker else ["--processes", str(PROCESSES)]
            cmd = [*base, "--flavour", flavour, "--format", "json", *extra, *by_name]
            runs.append((cmd, by_name, sev))
    with ThreadPoolExecutor(max_workers=PROCESSES) as pool:
        results = pool.map(lambda run: validate(*run), runs)
    return [f for chunk in results for f in chunk]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="*")
    ap.add_argument("--root", default="build", help="directory the PDF paths are reported relative to")
    ap.add_argument("--docker", action="store_true", help=f"run veraPDF from the {DOCKER_IMAGE} image")
    ap.add_argument("--json", help="write findings here")
    args = ap.parse_args()
    root = Path(args.root)
    pdfs = [Path(p) for p in args.pdfs] or sorted(
        p for p in root.rglob("*.pdf") if "Lectures/Figures" not in p.as_posix() and "_minted" not in p.as_posix()
    )
    findings = check(pdfs, root, args.docker)
    if args.json:
        write(findings, args.json)
    bad = {f.file for f in findings}
    for pdf in pdfs:
        rel = pdf.relative_to(root).as_posix()
        print(
            f"{'FAIL' if rel in bad else 'ok  '} {rel}"
            + "".join(f"\n       {f.rule} x{f.count}" for f in findings if f.file == rel)
        )


if __name__ == "__main__":
    main()
