from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit"
AME = Path(r"E:\Simcenter\2021.1\Amesim")
OUT = AUDIT / "submodels"
EXTENSIONS = {".c", ".h", ".spe", ".py"}
KEYWORDS = re.compile(
    r"pressure|flow|torque|speed|force|velocity|displacement|leak|friction|"
    r"efficien|volume|bulk|density|cavitation|state|derivative|stiffness|"
    r"damping|mass|inertia|q0top|rhoatp|getatp|ame[_a-z]*integr",
    re.I,
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def decode(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", errors="replace")


def build_index() -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for path in AME.rglob("*"):
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            index[path.stem.upper()].append(path)
    return index


def excerpts(path: Path, text: str) -> list[str]:
    lines = text.splitlines()
    if len(lines) <= 650:
        selected = set(range(len(lines)))
    else:
        selected = set(range(min(100, len(lines))))
        for i, line in enumerate(lines):
            if KEYWORDS.search(line) or re.search(r"\b(calc|init|macro)\b", line, re.I):
                selected.update(range(max(0, i - 2), min(len(lines), i + 4)))
    out, previous = [], -2
    for i in sorted(selected):
        if i != previous + 1:
            out.append("...")
        out.append(f"{i + 1:6d}: {lines[i]}")
        previous = i
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--submodel")
    group.add_argument("--all-from-inventory", action="store_true")
    args = ap.parse_args()

    inventory = read_csv(AUDIT / "10A_submodel_inventory.csv")
    selected = [args.submodel.upper()] if args.submodel else [r["submodel"].upper() for r in inventory]
    components = read_csv(AUDIT / "01_components.csv")
    params = read_csv(AUDIT / "04_parameters.csv")
    variables = read_csv(AUDIT / "05_variables.csv")
    aliases_by_submodel: dict[str, set[str]] = defaultdict(set)
    for r in components:
        aliases_by_submodel[r["submodel"].upper()].add(r["alias"])

    print("Indexing Amesim source tree...")
    index = build_index()
    found_count = 0
    for submodel in selected:
        dest = OUT / submodel
        dest.mkdir(parents=True, exist_ok=True)
        # DIRECT is Amesim connection metadata. Files named direct.h in compiler
        # toolchains are unrelated C-runtime headers, not a submodel definition.
        paths = [] if submodel == "DIRECT" else sorted(index.get(submodel, []), key=lambda p: (p.suffix.lower(), str(p).lower()))
        source_paths = [str(p) for p in paths]
        (dest / "source_paths.txt").write_text("\n".join(source_paths) + ("\n" if source_paths else ""), encoding="utf-8")
        if paths:
            found_count += 1
        excerpt_lines = [f"SUBMODEL: {submodel}", f"SOURCE FILES: {len(paths)}", ""]
        external_calls: set[str] = set()
        for path in paths:
            text = decode(path)
            excerpt_lines += ["=" * 78, f"FILE: {path}", "=" * 78]
            excerpt_lines += excerpts(path, text)
            excerpt_lines.append("")
            if path.suffix.lower() in {".c", ".h"}:
                for call in re.findall(r"\b([A-Za-z_]\w*_)(?=\s*\()", text):
                    if call.lower() not in {"if_", "for_", "while_", "switch_"}:
                        external_calls.add(call)
        (dest / "source_excerpt.txt").write_text("\n".join(excerpt_lines), encoding="utf-8")

        aliases = aliases_by_submodel.get(submodel, set())
        prows = [r for r in params if r["alias"] in aliases]
        vrows = [r for r in variables if r["alias"] in aliases]
        write_csv(dest / "parameters.csv", prows, list(prows[0]) if prows else list(params[0]))
        write_csv(dest / "variables.csv", vrows, list(vrows[0]) if vrows else list(variables[0]))
        state_names = sorted({r["data_path"].split("@", 1)[0] for r in vrows if r["basic_type"] == "ame_state_variable"})
        md = [
            f"# {submodel} constitutive evidence",
            "",
            "Evidence status: automatically extracted; constitutive classification must be reviewed against the cited source lines.",
            "",
            "## Identity",
            "",
            f"- Instances: {', '.join(sorted(aliases)) or 'none'}",
            f"- Source files found: {len(paths)}",
            f"- Amesim-declared state names: {', '.join(state_names) or 'none'}",
            "",
            "## Source paths",
            "",
        ]
        md += [f"- `{p}`" for p in paths] or ["- No exact-name source file found (implementation boundary)."]
        md += ["", "## Potential external calls", ""]
        md += [f"- `{x}`" for x in sorted(external_calls)] or ["- None detected by lexical scan."]
        md += [
            "",
            "## Truth level",
            "",
            "- Source paths and excerpts: LEVEL A — SOURCE VERIFIED when present.",
            "- Instance parameters/variables: LEVEL B — MODEL METADATA VERIFIED.",
            "- No equation is asserted by this automatic extraction alone.",
        ]
        (dest / "constitutive_evidence.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        print(f"{submodel}: {len(paths)} source file(s), {len(aliases)} instance(s)")

    print(f"SOURCE-MATCHED SUBMODELS = {found_count}/{len(selected)}")


if __name__ == "__main__":
    main()
