"""Lightweight papermill substitute: parametrize and execute a notebook.

Usage:
    python scripts/run_attribution_notebook.py --regime-dim vol_regime \
        --start 2025-09-25 --end 2026-04-22 \
        --output notebooks/research_notes/out_vol.ipynb
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient


def find_parameters_cell(nb: nbformat.NotebookNode) -> int:
    for i, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        if "parameters" in (cell.metadata.get("tags") or []):
            return i
        # heuristic: first code cell that contains "regime_dim ="
        if "regime_dim" in cell.source and "=" in cell.source:
            return i
    raise RuntimeError("parameters cell not found")


def patch_parameters(source: str, params: dict[str, str]) -> str:
    lines = source.splitlines()
    out = []
    for line in lines:
        replaced = False
        stripped = line.lstrip()
        for key, value in params.items():
            if stripped.startswith(f"{key} ") and "=" in stripped:
                indent = line[: len(line) - len(stripped)]
                out.append(f"{indent}{key} = {value!r}")
                replaced = True
                break
        if not replaced:
            out.append(line)
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="notebooks/research_notes/M2_broker_algo_v0.ipynb")
    ap.add_argument("--output", required=True)
    ap.add_argument("--regime-dim", default="vol_regime", choices=["vol_regime", "liq_regime", "trend_regime"])
    ap.add_argument("--start", default="2025-09-25")
    ap.add_argument("--end", default="2026-04-22")
    ap.add_argument("--config-version", default="attr_v0")
    args = ap.parse_args()

    nb = nbformat.read(args.input, as_version=4)
    idx = find_parameters_cell(nb)
    nb.cells[idx].source = patch_parameters(
        nb.cells[idx].source,
        {
            "regime_dim": args.regime_dim,
            "start_date": args.start,
            "end_date": args.end,
        },
    )
    print(f"executing notebook with regime_dim={args.regime_dim} start={args.start} end={args.end}")
    client = NotebookClient(nb, timeout=3600, kernel_name="python3")
    client.execute()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, args.output)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
