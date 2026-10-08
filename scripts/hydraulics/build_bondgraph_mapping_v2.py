from pathlib import Path
import csv
from collections import Counter

ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit"

CONNECTIONS = AUDIT / "02_connections_fullalias.csv"
OLD_COMPONENTS = AUDIT / "06A_bondgraph_component_candidates.csv"

OUT = AUDIT / "06A_bondgraph_component_candidates_v2.csv"
REPORT = AUDIT / "06D_bondgraph_candidate_cleanup.md"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def is_true(v):
    return str(v).strip().lower() == "true"


connections = read_csv(CONNECTIONS)
components = read_csv(OLD_COMPONENTS)

# ------------------------------------------------------------
# 1. 从正式连接表识别全部 line/net alias
# ------------------------------------------------------------

line_aliases = set()

for r in connections:

    if is_true(r["source_is_line"]):
        line_aliases.add(r["source_alias"])

    if is_true(r["target_is_line"]):
        line_aliases.add(r["target_alias"])


# ------------------------------------------------------------
# 2. 删除误进入 Component 表的 line/net
# ------------------------------------------------------------

cleaned = []

removed_lines = []

for r in components:

    alias = r["alias"]

    if alias in line_aliases:
        removed_lines.append(r)
        continue

    cleaned.append(r)


# ------------------------------------------------------------
# 3. remote 不是独立 power domain
#
# 如果 remote 与 signal 同时出现：
#     remote+signal -> signal
#
# 如果只有 remote：
#     保留为 INTERFACE，等待后续人工复核。
# ------------------------------------------------------------

remote_fixed = 0

for r in cleaned:

    combo = r["domain_combo"].strip()

    domains = {
        x.strip()
        for x in combo.split("+")
        if x.strip()
    }

    if "remote" not in domains:
        continue

    non_remote = domains - {"remote"}

    # remote + signal
    if non_remote == {"signal"}:

        r["domain_combo"] = "signal"
        r["candidate_bg_type"] = "SIGNAL"
        r["physical_role"] = (
            "supercomponent signal/interface element"
        )
        r["confidence"] = "high"
        r["review_required"] = "no"
        r["reason"] = (
            "The Amesim remote port is treated as an "
            "interface mechanism rather than an independent "
            "power domain; the remaining physical domain is signal."
        )

        remote_fixed += 1

    # 单独 remote
    elif not non_remote:

        r["domain_combo"] = "remote"
        r["candidate_bg_type"] = "INTERFACE"
        r["physical_role"] = (
            "supercomponent interface"
        )
        r["confidence"] = "medium"
        r["review_required"] = "yes"
        r["reason"] = (
            "Remote port detected without an explicit physical "
            "power domain. Keep as interface pending review."
        )

        remote_fixed += 1


# ------------------------------------------------------------
# 4. 写 V2
# ------------------------------------------------------------

fields = list(cleaned[0].keys())

with OUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    w = csv.DictWriter(
        f,
        fieldnames=fields
    )

    w.writeheader()
    w.writerows(cleaned)


# ------------------------------------------------------------
# 5. 统计
# ------------------------------------------------------------

type_count = Counter(
    r["candidate_bg_type"]
    for r in cleaned
)

confidence_count = Counter(
    r["confidence"]
    for r in cleaned
)

low_rows = [
    r for r in cleaned
    if r["confidence"] == "low"
]

unresolved_rows = [
    r for r in cleaned
    if r["candidate_bg_type"] == "UNRESOLVED"
]


with REPORT.open(
    "w",
    encoding="utf-8"
) as f:

    f.write("# Bond Graph Candidate Cleanup V2\n\n")

    f.write(
        f"- V1 rows: {len(components)}\n"
    )

    f.write(
        f"- Detected net/line aliases: {len(line_aliases)}\n"
    )

    f.write(
        f"- Line rows removed from component table: "
        f"{len(removed_lines)}\n"
    )

    f.write(
        f"- V2 component rows: {len(cleaned)}\n"
    )

    f.write(
        f"- remote-domain records normalized: "
        f"{remote_fixed}\n"
    )

    f.write(
        f"- Low-confidence rows after cleanup: "
        f"{len(low_rows)}\n"
    )

    f.write(
        f"- UNRESOLVED rows after cleanup: "
        f"{len(unresolved_rows)}\n\n"
    )

    f.write("## Candidate type distribution\n\n")

    for k, v in sorted(
        type_count.items(),
        key=lambda x: (-x[1], x[0])
    ):
        f.write(f"- `{k}`: {v}\n")

    f.write(
        "\n## Remaining UNRESOLVED\n\n"
    )

    for r in unresolved_rows:
        f.write(
            f"- `{r['alias']}` "
            f"({r['domain_combo']})\n"
        )


print("=" * 60)
print("Bond Graph candidate cleanup V2 complete")
print("=" * 60)

print("V1 ROWS =", len(components))
print("LINE ALIASES =", len(line_aliases))
print("REMOVED LINE ROWS =", len(removed_lines))
print("V2 COMPONENT ROWS =", len(cleaned))
print("REMOTE FIXED =", remote_fixed)
print("LOW CONFIDENCE =", len(low_rows))
print("UNRESOLVED =", len(unresolved_rows))

print()
print("OUTPUT =", OUT)
print("REPORT =", REPORT)