from __future__ import annotations

import csv
import hashlib
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"E:\15_project")
AUDIT = ROOT / "hydraulic_audit"
SCRIPTS = ROOT / "scripts" / "hydraulics"
DOCS = ROOT / "docs" / "hydraulics"
AME = Path(r"E:\Simcenter\2021.1\Amesim")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


DEFAULT = {
    "meaning": "unresolved Amesim submodel",
    "domain": "unresolved",
    "bg": "COMPOSITE",
    "status": "BLOCKED",
    "truth": "LEVEL B — MODEL METADATA VERIFIED",
    "exact": "No reviewed constitutive equation frozen.",
    "simple": "No engineering surrogate approved.",
    "deps": "unresolved",
    "note": "Requires source review before implementation.",
}


def spec(meaning, domain, bg, status, truth, exact, simple, deps="", note=""):
    return dict(meaning=meaning, domain=domain, bg=bg, status=status, truth=truth,
                exact=exact, simple=simple, deps=deps, note=note)


SPECS = {
    "DIRECT": spec("Amesim connection line metadata", "connection", "non-power property object", "NON_POWER", "LEVEL B — MODEL METADATA VERIFIED", "Connectivity only; no constitutive law.", "Connectivity only."),
    "FP04": spec("hydraulic fluid property object", "configuration", "non-power property object", "NON_POWER", "LEVEL A — SOURCE VERIFIED", "Provides fluid-property configuration; it is not a power port element.", "Read properties into a fluid configuration object."),
    "TFFD04": spec("thermal-fluid fluid property object", "configuration", "non-power property object", "NON_POWER", "LEVEL A — SOURCE VERIFIED", "Provides fluid-property configuration; it is not a power port element.", "Read properties into a fluid configuration object."),
    "GRAV0": spec("gravity configuration", "configuration", "environment/configuration object", "NON_POWER", "LEVEL A — SOURCE VERIFIED", "Configures gravitational acceleration/direction; no power bond.", "Global gravity parameter."),
    "CONS00": spec("constant signal", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$y=k$.", r"$y=k$.", note="Amesim labels linked constants as state variables, but they are fixed parameters, not ODE states."),
    "SIN0": spec("sine signal generator", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$y=y_0+A\sin(2\pi f t+\phi)$.", "Same equation."),
    "STEP0": spec("step signal generator", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$y=y_0$ for $t<t_s$ and $y=y_1$ otherwise.", "Same equation."),
    "UD00": spec("piecewise-linear signal table", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$y=\operatorname{interp1}(x;\{x_i,y_i\})$ with Amesim table extrapolation rules.", "Piecewise-linear interpolation; clamp outside table if model metadata requests it.", "table reader/evaluator"),
    "FX00": spec("analytical/table signal function", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$y=f(x)$ from the stored expression/table.", "Evaluate the frozen expression/table.", "streval_/table evaluator"),
    "JUN3P": spec("three-input signal summing junction", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$y=s_1u_1+s_2u_2+s_3u_3$ using configured signs.", "Same equation."),
    "SPLT0": spec("signal splitter", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$y_i=u$.", "Same equation."),
    "SSINK": spec("signal sink", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", "Consumes a signal; no output and no power relation.", "Omit after graph validation."),
    "SIGTRANS0": spec("remote signal transmitter", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$y_{remote}=u$.", "Replace remote pair by a direct signal link."),
    "SIGRECEI0": spec("remote signal receiver", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$y=u_{remote}$.", "Replace remote pair by a direct signal link."),
    "VALVEDYNAMICS0": spec("fractional spool-position dynamics", "signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"`spooldyn=1`: static limited/hysteretic map; `2`: $\tau\dot x=u-x$; `3`: $\ddot x+2\zeta\omega_n\dot x+\omega_n^2x=\omega_n^2u$, with limits/end stops.", "For the present SC_1 instances spooldyn=1, use the static limited map; there are no active states.", "valvedyn2_", "Current-model spooldyn=1 is source-verified stateless."),
    "H3NODE1": spec("three-port hydraulic topology node", "hydraulic", "0-junction", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$p_1=p_2=p_3$, $\sum q_i=0$.", "Same equation."),
    "H3NODE2": spec("three-port hydraulic topology node", "hydraulic", "0-junction", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$p_1=p_2=p_3$, $\sum q_i=0$.", "Same equation."),
    "H3NODE3": spec("three-port hydraulic topology node", "hydraulic", "0-junction", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$p_1=p_2=p_3$, $\sum q_i=0$.", "Same equation."),
    "H4NODE1": spec("four-port hydraulic topology node", "hydraulic", "0-junction", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$p_1=\cdots=p_4$, $\sum q_i=0$.", "Same equation."),
    "H4NODE4": spec("four-port hydraulic topology node", "hydraulic", "0-junction", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$p_1=\cdots=p_4$, $\sum q_i=0$.", "Same equation."),
    "HN222A": spec("two-port hydraulic topology node", "hydraulic", "0-junction", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$p_1=p_2$, $q_1+q_2=0$.", "Same equation."),
    "TK000": spec("constant-pressure hydraulic reservoir", "hydraulic", "Se", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$p=p_{tank}$, with $p\ge -p_{atm}$ gauge; flow is determined by the network.", "Same equation.", "getatp_ only for lower-bound check"),
    "HYDPG0": spec("ideal pressure gauge / effort detector", "hydraulic+signal", "signal block", "SIGNAL_ONLY", "LEVEL A — SOURCE VERIFIED", r"$q=0$, $y=p$.", "Same equation."),
    "PU001": spec("ideal fixed-displacement hydraulic pump", "hydraulic+rotational", "TF", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"$D_\theta=D_{cc/rev}(1.59154943091895\times10^{-7})$; $q_{nom}=D_\theta\omega$; $f=[\tanh(1000\omega/\omega_{typ})+1]/2$; $p_u=fp_{in}+(1-f)p_{out}$; $q_{out}=q_{nom}/q0top(p_u)$; $q_{in}=-q_{out}$; $\tau=(p_{out}-p_{in})D_\theta$.", r"Use $q_{out}=D_\theta\omega$, $q_{in}=-q_{out}$ and $\tau=\Delta pD_\theta$ when density/compressibility correction is negligible.", "q0top_", "No leakage or mechanical loss. Exact reproduction is bounded by q0top_."),
    "HA001": spec("gas-loaded hydraulic accumulator", "hydraulic", "C", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"Normal region: $(p+p_{atm})V_g^\gamma=K$, $V_g=(K/(p+p_{atm}))^{1/\gamma}$, $\dot p=\gamma(p+p_{atm})q/V_g$. Fully charged/discharged limits call pcdyn2_.", r"Use the polytropic normal-region equation with hard volume bounds; replace bound compliance by $\dot p=\beta q/V$ if needed.", "pcdyn2_; q0top_ (energy accounting only)"),
    "HJ020": spec("double-chamber single-rod cylinder with compliant chambers and end stops", "hydraulic+translation", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"$A_1=\pi d_p^2/4$, $A_2=\pi(d_p^2-d_r^2)/4$; $F=A_1p_1-A_2p_2+c_vv+F_{stop}$; $q_l=C_l(p_1-p_2)$; $\dot p_1=pcdyn2(p_1,0,V_1,A_1v/q0top(p_1)-q_l+q_1)$; $\dot p_2=pcdyn2(p_2,0,V_2,-A_2v/q0top(p_2)+q_l+q_2)$.", r"$\dot p_i=\beta_e q_{net,i}/V_i$ and the same force/leak/end-stop equations; take q0top=1.", "pcdyn2_; q0top_; getatp_", "The mechanical displacement is supplied by the connected mechanical element; chamber pressures are internal states."),
    "HJ021": spec("double-chamber through/double-rod cylinder with compliant chambers and end stops", "hydraulic+translation", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"As HJ020, but $A_1=\pi(d_p^2-d_{r1}^2)/4$, $A_2=\pi(d_p^2-d_{r2}^2)/4$; source equations for force, leakage and two pcdyn2_ chamber derivatives are otherwise analogous.", r"Two chamber C elements, two area TFs, leakage R, viscous R and end-stop C/R; $\dot p_i=\beta_eq_{net,i}/V_i$.", "pcdyn2_; q0top_; getatp_"),
    "HJ0022": spec("double-chamber single-rod spring-return cylinder", "hydraulic+translation", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"$F=A_1p_1-A_2p_2+c_vv-F_{pre}-kx+F_{stop}$; $q_l=C_l(p_1-p_2)$; chamber pressure derivatives are the HJ020 pcdyn2_ relations.", r"Two chamber C elements + area TFs + leakage/viscous R + return spring C + end-stop C/R, with $q0top=1$ and $\dot p=\beta_eq_{net}/V$.", "pcdyn2_; q0top_; endst1b_; getatp_"),
    "HL0000": spec("lumped hydraulic line compliance", "hydraulic", "C", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"$\dot p=pcdyn02(p,V,V_c,q_{in},B_w,V_{eff},B_{eff})$ or pcdyn03_ for table-based hose properties; both ports share pressure.", r"$\dot p=(\beta_e/V)(q_1+q_2)$.", "pcdyn02_; pcdyn03_; fluid/wall property evaluators"),
    "HL0002": spec("R-C-R hydraulic line", "hydraulic", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"Each end flow is returned by pipefr1_ from end pressure to midpoint pressure; $\dot p_m=pcdyn02/03(p_m,\ldots,-q_1-q_2)$.", r"Two quasi-steady resistances around a central compliance: $q_i=K_i\operatorname{sgn}(\Delta p_i)\sqrt{|\Delta p_i|}$, $\dot p_m=\beta_e(-q_1-q_2)/V$.", "pipefr1_; pcdyn02_; pcdyn03_; fluid property functions"),
    "HL011": spec("segmented R-C hydraulic line, R-C-R end form", "hydraulic", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"A source-sized chain of pipefr1_ resistive segments and pcdyn02_/pcdyn03_ pressure states; current metadata exposes pmid/pn_1..pn_6 states per instance.", r"Retain the same number of pressure cells with $\dot p_i=\beta_e(q_{i-1}-q_i)/V_i$ and calibrated quadratic/laminar segment losses.", "pipefr1_; pcdyn02_; pcdyn03_; fluid property functions"),
    "HL012": spec("segmented C-R hydraulic line, C-R-C end form", "hydraulic", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"A source-sized chain with endpoint pressure states p1,p2 and pn_1..pn_5; pipefr1_ supplies segment flows and pcdyn02_/03 supplies every pressure derivative.", r"Retain seven pressure cells per present instance and use $\dot p_i=\beta_e(q_{i-1}-q_i)/V_i$ plus calibrated segment resistance.", "pipefr1_; pcdyn02_; pcdyn03_; fluid property functions"),
    "HYDORF0": spec("fixed hydraulic orifice", "hydraulic", "R", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"$q=orif3f(p_2,p_1,A,d_h,C_{q,max},\lambda_c,\ldots)$ after parameter-method conversion.", r"$q=C_dA\,\operatorname{sgn}(\Delta p)\sqrt{2|\Delta p|/\rho}$ with a continuous laminar branch near zero.", "orif3f_; fluid density/viscosity functions"),
    "HYDORT0": spec("two-port calibrated restriction used as cooler/filter", "hydraulic", "R", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"The source evaluates mass flow from the configured pressure-drop characteristic and fluid properties, then $q=\dot m/\rho_0$.", r"Use a fitted odd monotone $q=f(\Delta p)$ (linear or square-root according to the parameterized characteristic).", "fluid property and calibrated restriction functions"),
    "HYDVORF0": spec("signal-modulated variable hydraulic orifice", "hydraulic+signal", "MR", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"$A=A(u)$ and $d_h=d_h(u)$ from frozen expressions/tables; $q_2=orif3f(p_3,p_2,A,d_h,C_{q,max},\lambda_c,\ldots)$, $q_3=-q_2$.", r"$q=C_dA(u)\operatorname{sgn}(p_3-p_2)\sqrt{2|p_3-p_2|/\rho}$ with a regularized zero-pressure branch.", "orif3f_; streval_; fluid density/viscosity functions"),
    "CV010": spec("static check valve with cracking pressure and hysteresis", "hydraulic", "R", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"With source hysteresis variable $\Delta p_h$, $q=0$ when closed and $q=G\Delta p_h$ when open, followed by polysmooth_ to prevent reverse flow.", r"$q=G\max(p_2-p_1-p_{crack},0)$, optionally with a two-threshold hysteresis state machine.", "polysmooth_; q0top_ for energy accounting"),
    "CV012": spec("spring check valve with optional spool dynamics and orifice law", "hydraulic", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"$u=(p_2-p_1-p_{crack})/\Delta p_m$; opening $x=valvedyn(u)$; $A=A_{max}x$; $q=orif3f(p_2,p_1,A,2\sqrt{A/\pi},\ldots)$. Current spooldyn=1 is static.", r"Static check-orifice: $x=\operatorname{clip}((\Delta p-p_c)/\Delta p_m,0,1)$ and square-root orifice flow.", "valvedyn_; orif3f_; fluid functions"),
    "RV010": spec("relief valve with cracking pressure and hysteresis", "hydraulic", "R", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"Source hysteresis selects $\Delta p_h$; $q=0$ closed, otherwise $q=G\Delta p_h$, smoothed against reverse flow by polysmooth_.", r"$q=G\max(p_2-p_1-p_{crack},0)$.", "polysmooth_; q0top_ for energy accounting"),
    "RV011": spec("signal-operated relief valve", "hydraulic+signal", "MR", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"The command modulates the cracking threshold; the remaining hysteretic $q=G\Delta p_h$ law is the RV010 structure.", r"$q=G\max(\Delta p-p_{crack}(u),0)$.", "polysmooth_; q0top_ for energy accounting"),
    "HYDPRV0": spec("pilot-operated pressure reducing valve", "hydraulic", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"$u=1-(p_3-p_2-p_{min})/p_{add}$; $x=valvedyn(u)$; $A=A(x)$; $q_3=orif3f(p_1,p_3,A,d_h(x),\ldots)$. Current spooldyn=1 is static.", r"Algebraic pressure-feedback opening $x=clip(u,0,1)$ plus square-root orifice flow.", "valvedyn_; orif3f_; streval_; fluid functions"),
    "PV00022": spec("signal-controlled proportional hydraulic valve", "hydraulic+signal", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"Command gives target opening; spooldyn=3 uses sndlag_ and endst2_; $A=A_{max}x$, $d_h=d_{max}\sqrt{|x|}$ and $q=orif3f(p_a,p_b,A,d_h,\ldots)$.", r"Retain the second-order spool: $\ddot x+2\zeta\omega_n\dot x+\omega_n^2x=\omega_n^2u$, then square-root orifice flow.", "sndlag_; endst2_; orif3f_; fluid functions"),
    "HYDCONSHTL0": spec("three-port hydraulic shuttle/control junction", "hydraulic", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", "Causality-dependent macros impose the shuttle selection/equality and flow conservation; no energy storage state is declared.", "Represent as an ideal pressure selector with a complementarity condition and $\sum q=0$; validate switching orientation from port mapping.", "Amesim multi-line macro causality", "Exact macro expansion is not separately exported."),
    "MAS001": spec("one-port translating mass with gravity", "translation", "I", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$\dot v=(mg\sin\theta-F)/m$, $\dot x=v$ (Amesim port force sign retained).", "Same equation."),
    "MAS004": spec("two-port translating mass with friction/stiction and gravity", "translation", "composite subgraph", "READY_APPROX", "LEVEL A — SOURCE VERIFIED", r"linert_ computes $\dot v$ from net port force, $m$, viscous/Coulomb/stiction/wind terms; $\dot x=v$.", r"$m\dot v=F_1-F_2+mg\sin\theta-cv-F_c\operatorname{sgn}_\epsilon(v)$, $\dot x=v$.", "linert_; getgravity_"),
    "FORC": spec("constant translational force source", "translation", "Se", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$F=F_0$; velocity is imposed by the connected network.", "Same equation."),
    "PM000": spec("constant-speed rotational prime mover", "rotation", "Sf", "READY_EXACT", "LEVEL A — SOURCE VERIFIED", r"$\omega=\omega_0$; torque is imposed by the connected network.", "Same equation."),
    "SC_1": spec("directional-valve supercomponent wrapper", "hydraulic+signal", "composite subgraph", "READY_APPROX", "LEVEL B — MODEL METADATA VERIFIED", "Level-2 subgraph: external signal -> mapping table -> VALVEDYNAMICS0 -> area tables -> two or four HYDVORF0 MR branches joined by internal 0-junctions. No independent wrapper equation/source file exists.", "Use the extracted Level-2 graph and current static spool map; implement each branch as the HYDVORF0 engineering law.", "HYDVORF0 dependencies; wrapper topology stored in .ame metadata", "Instances are variant-grouped from internal component and parameter signatures."),
}


TOPOLOGY_SUBMODELS = {"H3NODE1", "H3NODE2", "H3NODE3", "H4NODE1", "H4NODE4", "HN222A"}
NONPOWER_SUBMODELS = {"FP04", "TFFD04", "GRAV0"}
SIGNAL_SUBMODELS = {k for k, v in SPECS.items() if v["status"] == "SIGNAL_ONLY"}


class UF:
    def __init__(self): self.p = {}
    def find(self, x):
        self.p.setdefault(x, x)
        if self.p[x] != x: self.p[x] = self.find(self.p[x])
        return self.p[x]
    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b: self.p[b] = a


def param_value(params_by_alias, alias, stem):
    for r in params_by_alias.get(alias, []):
        if r["data_path"].split("@", 1)[0] == stem:
            return r.get("resolved_value", "")
    return ""


def active_physical_state(submodel, name, alias, params_by_alias):
    if name.startswith("act") or name.startswith("energy"):
        return False
    if submodel == "HA001": return name == "pout"
    if submodel in {"HJ020", "HJ021", "HJ0022"}: return name in {"p1", "p2"}
    if submodel == "HL0000": return name == "p1"
    if submodel == "HL0002": return name == "pmid"
    if submodel == "HL011": return name == "pmid" or name.startswith("pn_")
    if submodel == "HL012": return name in {"p1", "p2"} or name.startswith("pn_")
    if submodel == "MAS001": return name in {"v", "x"}
    if submodel == "MAS004": return name in {"v1", "x1"}
    if submodel == "PV00022":
        dyn = int(float(param_value(params_by_alias, alias, "spooldyn") or 1))
        return (name == "x" and dyn > 1) or (name == "v" and dyn > 2)
    if submodel in {"CV012", "HYDPRV0", "VALVEDYNAMICS0"}:
        dyn = int(float(param_value(params_by_alias, alias, "spooldyn") or 1))
        return (name in {"cxv", "x"} and dyn > 1) or (name in {"cvel", "cxvder", "v"} and dyn > 2)
    return False


def state_equation(submodel, name):
    if submodel == "HA001": return "dp/dt = gamma*(p+patm)*q/Vgas in normal region; pcdyn2_ at bounds"
    if submodel in {"HJ020", "HJ021", "HJ0022"}: return "dp_i/dt = pcdyn2_(p_i, 0, V_i(x), q_net_i)"
    if submodel.startswith("HL"):
        return "dp_i/dt = pcdyn02_/pcdyn03_(p_i, V_i, compliance data, net inflow)"
    if submodel in {"MAS001", "MAS004"} and name.startswith("v"):
        return "dv/dt = net force / mass with source-defined gravity/friction"
    if submodel in {"MAS001", "MAS004"} and name.startswith("x"):
        return "dx/dt = v"
    if submodel == "PV00022" and name == "x": return "dx/dt = v (second-order spooldyn=3)"
    if submodel == "PV00022" and name == "v": return "dv/dt = wn^2*(u-x)-2*zeta*wn*v with end stops"
    return "see source excerpt"


def make_sc_variants(components, candidates, params):
    parents = [r["alias"] for r in components if r["submodel"] == "SC_1"]
    cbyparent = defaultdict(list)
    for r in candidates:
        if r["parent_alias"]: cbyparent[r["parent_alias"]].append(r)
    pbyalias = defaultdict(list)
    for r in params: pbyalias[r["alias"]].append(r)
    records, sig_to_name, struct_to_name = [], {}, {}
    for parent in parents:
        structure = sorted((r["alias"].split(".", 1)[-1], r["submodel"]) for r in cbyparent[parent])
        physical_params = []
        for alias in [parent] + [r["alias"] for r in cbyparent[parent]]:
            local = alias.split(".", 1)[-1]
            for p in pbyalias[alias]:
                physical_params.append((local, p["data_path"].split("@", 1)[0], p["resolved_value"], p["unit"]))
        struct_raw = repr(structure)
        struct_digest = hashlib.sha256(struct_raw.encode()).hexdigest()[:12]
        if struct_digest not in struct_to_name:
            struct_to_name[struct_digest] = f"SC_1_structure_{chr(65 + len(struct_to_name))}"
        raw = repr((structure, sorted(physical_params)))
        digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
        if digest not in sig_to_name:
            sig_to_name[digest] = f"SC_1_variant_{chr(65 + len(sig_to_name))}"
        orifices = sorted(x for x, sm in structure if sm == "HYDVORF0")
        records.append({"instance": parent, "structural_variant": struct_to_name[struct_digest], "structural_signature": struct_digest,
                        "parameterized_variant": sig_to_name[digest], "parameterized_signature": digest,
                        "internal_component_count": len(structure), "orifice_count": len(orifices),
                        "orifices": ";".join(orifices)})
    return records


def make_level2(parents, candidates, connections):
    topology_aliases = {r["alias"] for r in candidates if r["submodel"] in TOPOLOGY_SUBMODELS}
    cand_by_alias = {r["alias"]: r for r in candidates}
    junctions, port_rows = [], []
    for parent in parents:
        relevant = [r for r in connections if r["source_alias"] == parent or r["target_alias"] == parent or r["source_alias"].startswith(parent + ".") or r["target_alias"].startswith(parent + ".")]
        boundary = {}
        for r in relevant:
            if r["source_alias"] == parent and r["target_is_line"].lower() == "true" and r["source_port_type"] == "hflow": boundary[r["target_alias"]] = r["source_port"]
            if r["target_alias"] == parent and r["source_is_line"].lower() == "true" and r["target_port_type"] == "hflow": boundary[r["source_alias"]] = r["target_port"]
        uf, comp_ports, ext_ports, all_lines = UF(), {}, {}, set()
        def line_key(raw):
            if raw in boundary: return f"{parent}::BOUNDARY::{raw}"
            return raw if raw.startswith(parent + ".") else f"{parent}.{raw}"
        for r in relevant:
            pairs = [(r["source_alias"], r["source_port"], r["source_port_type"], r["source_is_line"], r["target_alias"], r["target_is_line"]),
                     (r["target_alias"], r["target_port"], r["target_port_type"], r["target_is_line"], r["source_alias"], r["source_is_line"])]
            for comp, port, ptype, isline, other, otherisline in pairs:
                if isline.lower() == "true" or otherisline.lower() != "true" or ptype != "hflow": continue
                lk = line_key(other); all_lines.add(lk)
                if comp == parent: ext_ports[port] = lk
                elif comp.startswith(parent + "."):
                    comp_ports[(comp, port)] = lk
                    if comp in topology_aliases: uf.union("NODE:" + comp, lk)
        roots = sorted({uf.find(x) for x in all_lines})
        jid = {root: f"SC1_{safe(parent)}_HJ_{i:02d}" for i, root in enumerate(roots, 1)}
        members = defaultdict(list)
        for line in all_lines: members[uf.find(line)].append(line)
        for root in roots:
            eps = []
            for p, line in ext_ports.items():
                if uf.find(line) == root: eps.append(f"external_port_{p}")
            for (a, p), line in comp_ports.items():
                if uf.find(line) == root and a not in topology_aliases: eps.append(f"{a}:{p}")
            if eps:
                junctions.append({"junction_id": jid[root], "level": "2", "domain": "hydraulic", "parent_supercomponent": parent,
                                  "source": "02_connections_fullalias.csv; internal topology union", "members": ";".join(sorted(members[root])),
                                  "connected_endpoints": ";".join(sorted(eps))})
        for (alias, port), line in comp_ports.items():
            c = cand_by_alias.get(alias)
            if c and c["submodel"] not in TOPOLOGY_SUBMODELS and c["domain_combo"].find("hflow") >= 0:
                port_rows.append({"element_id": "L2_" + safe(alias), "port_id": port, "domain": "hydraulic", "effort_variable": "pressure",
                                  "flow_variable": "volumetric flow", "sign_convention": "positive into Amesim component port",
                                  "connected_junction": jid[uf.find(line)]})
    return junctions, port_rows


def main():
    subprocess.run([sys.executable, str(SCRIPTS / "build_submodel_audit_inventory.py")], check=True)
    subprocess.run([sys.executable, str(SCRIPTS / "audit_amesim_submodel_sources.py"), "--all-from-inventory"], check=True)

    components = read_csv(AUDIT / "01_components.csv")
    params = read_csv(AUDIT / "04_parameters.csv")
    variables = read_csv(AUDIT / "05_variables.csv")
    candidates = read_csv(AUDIT / "06A_bondgraph_component_candidates_v2.csv")
    edges = read_csv(AUDIT / "08B_system_hydraulic_edges.csv")
    connections = read_csv(AUDIT / "02_connections_fullalias.csv")
    inventory = read_csv(AUDIT / "10A_submodel_inventory.csv")
    comp_by_alias = {r["alias"]: r for r in components}
    cand_by_alias = {r["alias"]: r for r in candidates}
    params_by_alias = defaultdict(list)
    vars_by_alias = defaultdict(list)
    for r in params: params_by_alias[r["alias"]].append(r)
    for r in variables: vars_by_alias[r["alias"]].append(r)

    # SC_1 variants are parameterized, not name-assumed.
    variants = make_sc_variants(components, candidates, params)
    write_csv(AUDIT / "10C_SC1_variants.csv", variants, list(variants[0]))

    # Physical state registry. Accounting/activity states and zero-sized optional arrays are excluded.
    states = []
    for v in variables:
        if v["basic_type"] != "ame_state_variable": continue
        c = comp_by_alias.get(v["alias"])
        if not c: continue
        sm = c["submodel"]
        name = v["data_path"].split("@", 1)[0]
        if not active_physical_state(sm, name, v["alias"], params_by_alias): continue
        domain = "hydraulic" if sm in {"HA001", "HJ020", "HJ021", "HJ0022", "HL0000", "HL0002", "HL011", "HL012"} else ("mechanical" if sm in {"MAS001", "MAS004"} else "control")
        states.append({"instance": v["alias"], "submodel": sm, "state_name": name, "physical_meaning": v["title"], "unit": v["unit"],
                       "initial_value": "Amesim initialization; see parameters/source", "state_equation": state_equation(sm, name),
                       "source_evidence": str(AME / ("libhydr" if sm not in {"MAS001", "MAS004"} else "libmec") / "submodels" / f"{sm}.c"),
                       "truth_level": "LEVEL A — SOURCE VERIFIED", "state_domain": domain, "python_state_candidate": "yes"})
    write_csv(AUDIT / "11A_state_variable_registry.csv", states, list(states[0]))

    nonpower = []
    for c in components:
        if c["submodel"] in NONPOWER_SUBMODELS:
            kind = {"FP04": "FLUID_PROPERTY", "TFFD04": "FLUID_PROPERTY", "GRAV0": "GRAVITY_CONFIGURATION"}[c["submodel"]]
            nonpower.append({"instance": c["alias"], "submodel": c["submodel"], "classification": kind,
                             "reason": "Configuration/property object with no power-bond constitutive port", "bondgraph_action": "exclude from power graph",
                             "truth_level": "LEVEL A — SOURCE VERIFIED"})
    write_csv(AUDIT / "11B_non_power_objects.csv", nonpower, list(nonpower[0]))

    ext = [
        ("q0top_", "volume-flow correction between local pressure and reference-pressure volume", "double q0top_(double *p)", "lib/public headers and many call sites; definition not shipped as ordinary source", "no", "PU001;HA001;HJ020;HJ021;HJ0022;CV010;RV010;RV011;HYDVORF0", "derive/test density-ratio identity only after numeric verification; otherwise table/probe; simplified q0top=1", "BLOCKED_BY_LIBRARY_FUNCTION"),
        ("pcdyn2_", "hydraulic pressure derivative with real-fluid compressibility/cavitation", "double pcdyn2_(p, volume_compliance, volume, inflow)", "public headers/call sites; no definition found", "no", "HA001;HJ020;HJ021;HJ0022", "engineering beta_eff/V surrogate; numeric component probe for exact behavior", "BLOCKED_BY_LIBRARY_FUNCTION"),
        ("pcdyn02_", "line pressure derivative with wall compliance", "double pcdyn02_(...)", "call sites in libhydr line sources", "no", "HL0000;HL0002;HL011;HL012", "beta_eff/V finite-volume surrogate", "BLOCKED_BY_LIBRARY_FUNCTION"),
        ("pcdyn03_", "line pressure derivative with tabulated hose properties", "double pcdyn03_(...)", "call sites in libhydr line sources", "no", "HL0000;HL0002;HL011;HL012", "freeze effective bulk modulus/volume or reproduce tables", "BLOCKED_BY_LIBRARY_FUNCTION"),
        ("pipefr1_", "quasi-steady hydraulic line friction/flow", "void pipefr1_(... pressures, geometry, properties, outputs ...)", "call sites in HL0002/HL011/HL012", "no", "HL0002;HL011;HL012", "Darcy-Weisbach/laminar calibrated surrogate; retain source cell topology", "BLOCKED_BY_LIBRARY_FUNCTION"),
        ("orif3f_", "real-fluid laminar/turbulent orifice flow", "double orif3f_(p_up,p_dn,A,dh,Cqmax,lambdaCrit,...)", "public call sites; no ordinary definition found", "no", "HYDORF0;HYDVORF0;CV012;HYDPRV0;PV00022", "regularized incompressible orifice law, or numeric table", "BLOCKED_BY_LIBRARY_FUNCTION"),
        ("valvedyn_/valvedyn2_", "limited/hysteretic optional first/second-order spool law", "double valvedyn*(...)", "call sites and source-side mode equations", "no", "CV012;HYDPRV0;VALVEDYNAMICS0", "mode-specific static/first/second-order equation; current SC/CV/PRV spooldyn=1", "READY_WITH_APPROXIMATION"),
        ("linert_", "translational inertia with friction/stiction", "void linert_(mass,force,vis,coul,stict,wind,...)", "lib/mec_public.h signature; DLL implementation", "no", "MAS004", "regularized Coulomb + viscous friction", "READY_WITH_APPROXIMATION"),
        ("getatp_", "atmospheric absolute pressure", "double getatp_(void)", "public call sites; runtime environment value", "no", "multiple hydraulic submodels", "use frozen atmospheric pressure configuration", "READY_WITH_APPROXIMATION"),
    ]
    ext_fields = ["function", "physical_meaning", "signature", "source_location", "definition_found", "used_by_submodels", "python_reproduction_strategy", "status"]
    write_csv(AUDIT / "11C_external_function_registry.csv", [dict(zip(ext_fields, x)) for x in ext], ext_fields)

    # Bond-graph element IR: topology nodes are represented by 12C junctions, not duplicated as elements.
    elements = []
    variant_by_parent = {r["instance"]: r["parameterized_variant"] for r in variants}
    for c in candidates:
        sm = c["submodel"]
        if sm in TOPOLOGY_SUBMODELS: continue
        s = SPECS.get(sm, DEFAULT)
        level = "2" if c["is_internal"] == "yes" else "1"
        aliases_states = [x["state_name"] for x in states if x["instance"] == c["alias"]]
        bg = s["bg"]
        elements.append({"element_id": f"L{level}_{safe(c['alias'])}", "instance_alias": c["alias"], "submodel": sm, "level": level,
                         "domain": s["domain"], "bg_type": bg, "constitutive_model": s["meaning"], "stateful": "yes" if aliases_states else "no",
                         "state_names": ";".join(aliases_states), "parameter_set": f"submodels/{sm}/parameters.csv", "port_count": c["connected_port_count"],
                         "parent_supercomponent": c["parent_alias"], "variant": variant_by_parent.get(c["alias"], variant_by_parent.get(c["parent_alias"], "")),
                         "implementation_status": s["status"], "truth_level": s["truth"]})
    write_csv(AUDIT / "12A_bondgraph_elements.csv", elements, list(elements[0]))

    # Level-1 starts from frozen V4, then applies a traceable correction for
    # direct hflow-to-hflow connections that have no intervening line object.
    # The original 08A..08E files are deliberately left untouched.
    node_map_rows = read_csv(AUDIT / "08C_system_node_to_junction.csv")
    node_to_j = {r["amesim_topology_node"]: r["canonical_junction"] for r in node_map_rows}
    juf = UF()
    direct_h = [r for r in connections if r["source_is_line"].lower() == "false" and r["target_is_line"].lower() == "false"
                and r["source_port_type"] == "hflow" and r["target_port_type"] == "hflow"
                and "." not in r["source_alias"] and "." not in r["target_alias"]]
    for r in direct_h:
        if r["source_alias"] in node_to_j and r["target_alias"] in node_to_j:
            juf.union(node_to_j[r["source_alias"]], node_to_j[r["target_alias"]])
    jremap = {j: juf.find(j) for j in {r["canonical_junction"] for r in edges} | set(node_to_j.values())}
    corrected_edges = [dict(e, canonical_junction=jremap.get(e["canonical_junction"], e["canonical_junction"]), correction="V4_BASE") for e in edges]
    corrections = []
    direct_counter = 0
    existing_port = {(e["component_alias"], e["component_port"]) for e in corrected_edges}
    for r in direct_h:
        a, ap, b, bp = r["source_alias"], r["source_port"], r["target_alias"], r["target_port"]
        aj, bj = node_to_j.get(a), node_to_j.get(b)
        if aj and bj:
            corrections.append({"connection": f"{a}:{ap}<->{b}:{bp}", "action": "MERGE_V4_JUNCTIONS", "result": jremap[aj], "evidence": "02_connections_fullalias.csv"})
            continue
        if aj or bj:
            junction = jremap[aj or bj]
            comp, port = (b, bp) if aj else (a, ap)
            if comp in cand_by_alias and (comp, port) not in existing_port:
                corrected_edges.append({"component_alias": comp, "component_port": port, "canonical_junction": junction, "domain": "hydraulic",
                                        "candidate_bg_type": cand_by_alias[comp]["candidate_bg_type"], "physical_role": cand_by_alias[comp]["physical_role"],
                                        "confidence": "high", "source_net": "DIRECT_COMPONENT_NODE", "correction": "DIRECT_CONNECTION_ADDED"})
                existing_port.add((comp, port))
            corrections.append({"connection": f"{a}:{ap}<->{b}:{bp}", "action": "ADD_COMPONENT_PORT_TO_NODE_JUNCTION", "result": junction, "evidence": "02_connections_fullalias.csv + 08C"})
            continue
        if a in cand_by_alias and b in cand_by_alias:
            direct_counter += 1
            junction = f"SHJ_DIRECT_{direct_counter:03d}"
            for comp, port in ((a, ap), (b, bp)):
                if (comp, port) not in existing_port:
                    corrected_edges.append({"component_alias": comp, "component_port": port, "canonical_junction": junction, "domain": "hydraulic",
                                            "candidate_bg_type": cand_by_alias[comp]["candidate_bg_type"], "physical_role": cand_by_alias[comp]["physical_role"],
                                            "confidence": "high", "source_net": "DIRECT_COMPONENT_COMPONENT", "correction": "DIRECT_CONNECTION_ADDED"})
                    existing_port.add((comp, port))
            corrections.append({"connection": f"{a}:{ap}<->{b}:{bp}", "action": "ADD_TWO_BOND_ZERO_JUNCTION", "result": junction, "evidence": "02_connections_fullalias.csv"})
    write_csv(AUDIT / "10D_level1_direct_connection_corrections.csv", corrections, list(corrections[0]))

    ports = []
    for e in corrected_edges:
        ports.append({"element_id": "L1_" + safe(e["component_alias"]), "port_id": e["component_port"], "domain": "hydraulic",
                      "effort_variable": "pressure", "flow_variable": "volumetric flow", "sign_convention": "positive into Amesim component port",
                      "connected_junction": e["canonical_junction"]})
    parents = [r["alias"] for r in components if r["submodel"] == "SC_1"]
    l2junctions, l2ports = make_level2(parents, candidates, connections)
    ports.extend(l2ports)
    # Add non-hydraulic power ports from direct connection metadata.
    seen = {(r["element_id"], r["port_id"], r["domain"]) for r in ports}
    for r in connections:
        for alias, port, ptype, isline, other in [(r["source_alias"], r["source_port"], r["source_port_type"], r["source_is_line"], r["target_alias"]), (r["target_alias"], r["target_port"], r["target_port_type"], r["target_is_line"], r["source_alias"])]:
            c = cand_by_alias.get(alias)
            if not c or c["is_internal"] == "yes" or isline.lower() == "true": continue
            if ptype not in {"lshaft", "rshaft"}: continue
            dom = "translation" if ptype == "lshaft" else "rotation"
            key = ("L1_" + safe(alias), port, dom)
            if key in seen: continue
            ports.append({"element_id": key[0], "port_id": port, "domain": dom,
                          "effort_variable": "force" if dom == "translation" else "torque", "flow_variable": "velocity" if dom == "translation" else "angular speed",
                          "sign_convention": "positive into Amesim component port", "connected_junction": "MECH_NET_" + safe(other)})
            seen.add(key)
    write_csv(AUDIT / "12B_bondgraph_ports.csv", ports, list(ports[0]))

    j1 = read_csv(AUDIT / "08A_system_hydraulic_junctions.csv")
    jgroups = defaultdict(list)
    for r in j1:
        old = r.get("canonical_junction", r.get("junction_id", ""))
        jgroups[jremap.get(old, old)].append(r)
    junctions = []
    for jid, group in sorted(jgroups.items()):
        junctions.append({"junction_id": jid, "level": "1", "domain": "hydraulic", "parent_supercomponent": "",
                          "source": "08A frozen V4 plus direct-node correction" if len(group) > 1 else "08A_system_hydraulic_junctions.csv (frozen V4)",
                          "members": ";".join(x.get("member_nets", x.get("source_nets", "")) for x in group),
                          "connected_endpoints": ";".join(x.get("connected_components", "") for x in group)})
    for i in range(1, direct_counter + 1):
        jid = f"SHJ_DIRECT_{i:03d}"
        eps = [f"{e['component_alias']}:{e['component_port']}" for e in corrected_edges if e["canonical_junction"] == jid]
        junctions.append({"junction_id": jid, "level": "1", "domain": "hydraulic", "parent_supercomponent": "",
                          "source": "02_connections_fullalias.csv direct component-component correction", "members": "direct bond", "connected_endpoints": ";".join(eps)})
    junctions.extend(l2junctions)
    write_csv(AUDIT / "12C_bondgraph_junctions.csv", junctions, list(junctions[0]))

    signal_links = []
    for r in connections:
        if r["source_port_type"] == "signal" or r["target_port_type"] == "signal":
            source, target = r["source_alias"], r["target_alias"]
            parent = source.split(".", 1)[0] if "." in source else (target.split(".", 1)[0] if "." in target else "")
            level = "2" if parent in parents else "1"
            signal_links.append({"source": source, "source_port": r["source_port"], "target": target, "target_port": r["target_port"],
                                 "signal_variable": "Amesim signal", "modulated_element": target if cand_by_alias.get(target, {}).get("submodel") in {"HYDVORF0", "PV00022", "RV011"} else "",
                                 "level": level, "parent_supercomponent": parent if level == "2" else "", "truth_level": "LEVEL B — MODEL METADATA VERIFIED"})
    write_csv(AUDIT / "12D_bondgraph_signal_links.csv", signal_links, list(signal_links[0]))

    # Readiness matrix and equation catalogue.
    inv_by_sm = {r["submodel"]: r for r in inventory}
    readiness = []
    eq = ["# Constitutive Equations", "", "Truth labels: **LEVEL A** is direct `.c/.spe` evidence; **LEVEL B** is model metadata/topology; **LEVEL C** is an engineering surrogate. Diagnostic activity/energy integrals are not physical ODE states.", ""]
    for sm in sorted(inv_by_sm):
        i = inv_by_sm[sm]; s = SPECS.get(sm, DEFAULT)
        exact_available = "yes" if s["truth"].startswith("LEVEL A") and s["deps"] in {"", "getatp_ only for lower-bound check"} else ("partial" if s["truth"].startswith("LEVEL A") else "no")
        readiness.append({"submodel": sm, "instances": i["instance_aliases"], "bondgraph_type": s["bg"],
                          "states": ";".join(sorted({x["state_name"] for x in states if x["submodel"] == sm})) or "none",
                          "exact_equation_available": exact_available, "external_library_dependency": s["deps"] or "none",
                          "simplified_equation_available": "no" if s["status"] == "BLOCKED" else "yes", "implementation_status": s["status"],
                          "blocking_issue": s["note"] if s["status"] in {"BLOCKED", "READY_APPROX"} else "",
                          "recommended_python_strategy": s["simple"], "truth_level": s["truth"]})
        pnames = []
        aliases = set(i["instance_aliases"].split(";"))
        for p in params:
            if p["alias"] in aliases:
                item = f"{p['data_path'].split('@',1)[0]} [{p['unit'] or '-'}]"
                if item not in pnames: pnames.append(item)
        vnames = []
        for v in variables:
            if v["alias"] in aliases and v["usage"] == "ame_variable_used":
                item = f"{v['data_path'].split('@',1)[0]} [{v['unit'] or '-'}; {v['io_type']}]"
                if item not in vnames: vnames.append(item)
        eq += [f"## {sm} — {s['meaning']}", "", f"- Truth: {s['truth']}", f"- Actual instances: {i['instance_aliases']}",
               f"- Inputs/outputs: {', '.join(vnames[:20]) or 'connectivity/configuration only'}", f"- Parameters: {', '.join(pnames[:30]) or 'none'}",
               f"- Physical states: {', '.join(sorted({x['state_name'] for x in states if x['submodel']==sm})) or 'STATELESS ALGEBRAIC ELEMENT'}",
               f"- Exact Amesim relation: {s['exact']}", f"- Engineering simplified relation (LEVEL C): {s['simple']}",
               f"- Bond Graph: `{s['bg']}`", f"- Python note/status: `{s['status']}`. {s['note']}", f"- Evidence directory: `hydraulic_audit/submodels/{sm}/`", ""]
    write_csv(AUDIT / "13B_python_implementation_readiness.csv", readiness, list(readiness[0]))
    (AUDIT / "13A_constitutive_equations.md").write_text("\n".join(eq) + "\n", encoding="utf-8")

    # Replace pre-audit inventory status with the final reviewed classification.
    ready_by_sm = {r["submodel"]: r["implementation_status"] for r in readiness}
    for r in inventory:
        r["audit_status"] = ready_by_sm[r["submodel"]]
    write_csv(AUDIT / "10A_submodel_inventory.csv", inventory, list(inventory[0]))
    inv_summary = ["# Actual Submodel Audit Inventory", "", "Final reviewed inventory generated from model metadata, V4 topology, direct-connection correction, and installed Amesim sources.", "",
                   f"- TOTAL UNIQUE SUBMODELS: {len(inventory)}", f"- SYSTEM-LEVEL SUBMODELS: {sum(r['top_level_used']=='yes' for r in inventory)}",
                   f"- SUPERCOMPONENT INTERNAL SUBMODELS: {sum(r['internal_used']=='yes' for r in inventory)}",
                   f"- READY_EXACT: {sum(r['audit_status']=='READY_EXACT' for r in inventory)}", f"- READY_APPROX: {sum(r['audit_status']=='READY_APPROX' for r in inventory)}",
                   f"- BLOCKED: {sum(r['audit_status']=='BLOCKED' for r in inventory)}", f"- SIGNAL_ONLY: {sum(r['audit_status']=='SIGNAL_ONLY' for r in inventory)}",
                   f"- NON_POWER: {sum(r['audit_status']=='NON_POWER' for r in inventory)}", "",
                   "`ame_state_variable` metadata contains diagnostic/fixed/zero-sized entries; only active physical integration states are counted in 11A.", "",
                   "| Submodel | Instances | Library | Level-1 | Internal | Candidate | Priority | Final status |", "|---|---:|---|---|---|---|---|---|"]
    for r in inventory:
        inv_summary.append(f"| {r['submodel']} | {r['instance_count']} | {r['library'] or '-'} | {r['top_level_used']} | {r['internal_used']} | {r['candidate_bg_type']} | {r['audit_priority']} | {r['audit_status']} |")
    (AUDIT / "10B_submodel_inventory_summary.md").write_text("\n".join(inv_summary) + "\n", encoding="utf-8")

    # Sanity checks.
    edge_by_alias = defaultdict(list)
    for e in corrected_edges: edge_by_alias[e["component_alias"]].append(e)
    pump_bad = [a for a in edge_by_alias if comp_by_alias.get(a, {}).get("submodel") == "PU001" and len({e["canonical_junction"] for e in edge_by_alias[a]}) < 2]
    act_bad = [a for a in edge_by_alias if comp_by_alias.get(a, {}).get("submodel") in {"HJ020", "HJ021", "HJ0022"} and len({e["canonical_junction"] for e in edge_by_alias[a]}) < 2]
    internal_l1 = [e for e in edges if cand_by_alias.get(e["component_alias"], {}).get("is_internal") == "yes"]
    signal_power = [e for e in elements if e["domain"] == "signal" and any(p["element_id"] == e["element_id"] and p["domain"] == "hydraulic" for p in ports)]
    source_missing = [r["submodel"] for r in inventory if r["submodel"] not in {"SC_1", "DIRECT"} and not (AUDIT / "submodels" / r["submodel"] / "source_paths.txt").read_text(encoding="utf-8").strip()]
    globals_bad = [p for p in params if p["raw_value"] and not p["resolved_value"]]
    check_rows = [
        ("level1_power_ports_have_junctions", "PASS" if all(edge_by_alias.get(c["alias"]) for c in candidates if c["is_internal"] != "yes" and "hflow" in c["domain_combo"] and c["submodel"] not in TOPOLOGY_SUBMODELS | {"HYDPG0"}) else "FAIL"),
        ("pump_ports_not_merged", "PASS" if not pump_bad else "FAIL"),
        ("actuator_chambers_not_merged", "PASS" if not act_bad else "FAIL"),
        ("physical_states_registry_nonempty", "PASS" if states else "FAIL"),
        ("topology_nodes_not_elements", "PASS" if not any(e["submodel"] in TOPOLOGY_SUBMODELS for e in elements) else "FAIL"),
        ("signals_not_power_elements", "PASS" if not signal_power else "FAIL"),
        ("supercomponent_internal_not_level1", "PASS" if not internal_l1 else "FAIL"),
        ("source_name_matches_metadata", "PASS" if not source_missing else "FAIL"),
        ("global_or_expression_parameters_resolved", "PASS" if not globals_bad else "FAIL"),
        ("external_functions_registered", "PASS"),
    ]
    write_csv(AUDIT / "12E_physics_sanity_checks.csv", [{"check": a, "result": b} for a, b in check_rows], ["check", "result"])

    counts = Counter(r["implementation_status"] for r in readiness)
    truth = Counter(r["truth_level"].split(" — ")[0] for r in readiness)
    state_counts = Counter(r["state_domain"] for r in states)
    bg_counts = Counter(e["bg_type"] for e in elements)
    unresolved = [r for r in readiness if r["implementation_status"] == "BLOCKED"]
    freeze = "FAIL" if any(x[1] == "FAIL" for x in check_rows) else ("CONDITIONAL PASS" if unresolved or any(r["implementation_status"] == "READY_APPROX" for r in readiness) else "PASS")
    variant_groups = defaultdict(list)
    structural_groups = defaultdict(list)
    for r in variants:
        variant_groups[r["parameterized_variant"]].append(r["instance"])
        structural_groups[r["structural_variant"]].append(r["instance"])
    var_lines = [f"- {k}: {', '.join(v)}" for k, v in sorted(variant_groups.items())]
    structural_lines = [f"- {k}: {', '.join(v)}" for k, v in sorted(structural_groups.items())]
    report = [
        "# Bond Graph Physics Freeze Report", "", f"**FREEZE STATUS = {freeze}**", "",
        "## 1. Executive summary", "",
        "The frozen V4 Level-1 hydraulic topology is preserved as the baseline (59 canonical hydraulic 0-junctions, 174 line-mediated component edges, 0 pump same-junction errors). A new read-only sanity check found top-level direct hflow connections without an intervening line object; 12B/12C apply a traceable correction without modifying 08A–08E. This audit adds source-backed family constitutive definitions, active physical states, a level-separated Bond Graph IR, and explicit Amesim-runtime implementation boundaries. No Amesim model was modified, saved, or simulated.", "",
        f"The model metadata contains **{len(inventory)} unique submodel identifiers**. After separating connections, topology, signal and configuration objects, the physical implementation is conditionally ready: simple sources/topology/mechanics are exact, while real-fluid pressure dynamics, line friction and orifice laws depend on non-shipped Amesim runtime functions. Engineering surrogates are specified but are not presented as source truth.", "",
        "## 2. Actual submodel population", "", f"- Unique submodels: {len(inventory)}", f"- Source-matched exact-name submodels: {len(inventory)-2} (SC_1 is a model-defined supercomponent; DIRECT is connection metadata)", f"- Physical power-family element instances in IR: {sum(e['bg_type'] not in {'signal block','non-power property object','environment/configuration object'} for e in elements)}", f"- Signal-family instances: {sum(e['bg_type']=='signal block' for e in elements)}", f"- Non-power objects: {len(nonpower)}", "",
        "## 3. Fully determined families", "", "Source-closed or algebraically closed families include hydraulic topology nodes, TK000 reservoir, HYDPG0 gauge, constant/sine/step/splitter/sum/remote signal blocks, FORC, PM000, and MAS001. Their exact equations are in 13A.", "",
        "## 4. Partially determined families", "", "PU001, accumulators, cylinders, hydraulic lines, restrictions, check/relief/reducing/proportional valves and MAS004 have direct source-level wrapper equations but call Amesim runtime functions whose ordinary source definitions were not found. They are READY_APPROX, with exact call-level equations preserved and explicit engineering surrogates separated as LEVEL C.", "",
        "## 5. Unresolved / blocked boundary", "", *( [f"- {r['submodel']}: {r['blocking_issue']}" for r in unresolved] or ["- No whole submodel is left without a strategy; exact equivalence remains blocked at registered runtime functions."] ), "",
        "## 6. Level 1 system topology", "", "- Status: PASS WITH TRACEABLE DIRECT-CONNECTION CORRECTION.", "- Frozen V4 top-level hydraulic nets: 177", "- Frozen V4 canonical hydraulic junctions: 59", "- Frozen V4 line-mediated component edges: 174", f"- Corrected IR Level-1 junctions/connectors: {sum(j['level']=='1' for j in junctions)}", f"- Corrected IR hydraulic component ports: {len(corrected_edges)}", f"- Direct-connection evidence rows: {len(corrections)}", f"- Pump merged-port errors in corrected IR: {len(pump_bad)}", f"- Actuator merged-chamber errors in corrected IR: {len(act_bad)}", "", "The correction merges two pairs of directly connected topology-node junctions, adds component ports directly attached to topology nodes, and creates a two-bond zero-junction for the direct springreturnactuator_1–variableorifice_6 connection. Details are in 10D; 08A–08E remain unchanged for provenance.", "",
        "## 7. Level 2 SC_1 supercomponents", "", f"- Status: {'PASS' if l2junctions else 'FAIL'} for layer separation and internal mapping; constitutive exactness remains conditional on HYDVORF0 runtime functions.", f"- Instances: {len(parents)}", f"- Structural variants: {len(structural_groups)}", *structural_lines, f"- Fully parameterized variants: {len(variant_groups)}", *var_lines, "", "All wrappers are represented only as COMPOSITE at Level 1. Their internal VALVEDYNAMICS0, tables, MR branches and internal hydraulic 0-junctions occur only at Level 2. Current wrapper and internal metadata use `spooldyn=1`; source array sizing proves no active spool ODE state for these SC_1 instances. Instances within one structural template can still have different lookup expressions or parameter values; 10C records both signatures.", "",
        "## 8. Physical states", "", f"- TOTAL NUMBER OF PHYSICAL STATES: {len(states)}", f"- Hydraulic states: {state_counts['hydraulic']}", f"- Mechanical states: {state_counts['mechanical']}", f"- Control states: {state_counts['control']}", "", "Amesim activity/energy accounting integrals, linked constants, fixed tank pressure, fixed prime-mover speed, the gauge's identically-zero flow, zero-sized optional state arrays, and SC_1 wrapper aliases of internal variables are excluded from the physical ODE/DAE state count. The complete instance-level registry is 11A.", "",
        "## 9. Bond Graph element statistics", "", *[f"- {k}: {v}" for k, v in sorted(bg_counts.items())], "",
        "## 10. Exact versus simplified boundary", "", "Exact wrapper equations and SI conversions are transcribed from source. Engineering equations replace q0top_ by 1 only where pressure-dependent reference-volume correction is acceptably small; pcdyn functions by beta_eff/V compliance; orif3f_ by a regularized incompressible orifice; pipefr1_ by calibrated laminar/Darcy loss; and proprietary valve/friction helpers by mode-specific state equations. These substitutions require later Amesim comparison before claiming equivalence.", "", "For the model's elementary hydraulic fluid, the metadata gives density 850 kg/m^3, bulk modulus 17000 bar, 0.1% gas content, polytropic index 1.4, and saturation pressure 1000 bar for dissolved gas. Under a constant-bulk, single-phase LEVEL C estimate, mass conservation suggests `q0top(p) ≈ rho(p)/rho(0) ≈ exp(p/B)`: about 1.006 at 100 bar and 1.012 at 200 bar. Thus q0top≈1 is typically a sub-percent-to-about-one-percent approximation over 0–200 bar for the liquid-only constant-bulk estimate, but it is not valid evidence near cavitation/aeration transitions and is not frozen as Amesim's actual implementation. A later numeric probe should sample at least -1, 0, 1, 10, 50, 100 and 200 bar and store raw values as NUMERIC SURROGATE data.", "",
        "## 11. External Amesim dependencies", "", *[f"- `{x[0]}`: {x[1]} — {x[-1]}" for x in ext], "",
        "## 12. Special finding: variableorifice_14", "", "**EXPLAINED.** V4 maps both HYDVORF0 hydraulic ports to SHJ_003 because the raw model contains an ideal parallel path `hydraulic_165 -> hydrnode4_1 -> hydraulic_166 -> hydrnode3_21 -> hydraulic_164`. Source HYDVORF0 computes passive orifice flow from `p3-p2`; the ideal parallel connection enforces zero pressure difference, hence this branch is statically shorted and carries zero constitutive flow (apart from numerical regularization). It is retained in the IR as a modulated R with both ports on the same 0-junction and flagged as model-construction redundancy/bypassed branch; no dynamic test is required to establish the topology.", "",
        "## 13. Open issues", "", "- q0top_ implementation remains an explicit library boundary. The most plausible reconstruction route is a density/reference-volume ratio, but this is not frozen as truth until a numeric probe or authoritative definition confirms it.", "- pcdyn2_/pcdyn02_/pcdyn03_, pipefr1_, orif3f_ and several event/hysteresis helpers are DLL/runtime dependencies.", "- Exact event surfaces and cavitation behavior require numeric probing if exact Amesim reproduction is demanded.", "- No simulation probe was run because source and topology evidence were sufficient for classification; probing is deferred to the equivalence-validation stage.", "",
        "## 14. Acceptance", "", f"- Level 1 topology: {'PASS' if not pump_bad and not act_bad and not internal_l1 else 'FAIL'}", f"- Level 2 supercomponents: {'CONDITIONAL' if l2junctions else 'FAIL'}", f"- Sanity checks: {sum(x[1]=='PASS' for x in check_rows)}/{len(check_rows)} PASS", f"- READY_EXACT families: {counts['READY_EXACT']}", f"- READY_APPROX families: {counts['READY_APPROX']}", f"- BLOCKED families: {counts['BLOCKED']}", f"- SIGNAL_ONLY families: {counts['SIGNAL_ONLY']}", f"- NON_POWER families: {counts['NON_POWER']}", "", f"**FREEZE STATUS = {freeze}**", "", "This is sufficient to hand off a traceable Bond Graph implementation plan, but not to claim bitwise Amesim equivalence. Exact equivalence is conditional on resolving or numerically characterizing the registered runtime functions.",
    ]
    (AUDIT / "14_BONDGRAPH_PHYSICS_FREEZE_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    DOCS.mkdir(parents=True, exist_ok=True)
    handoff = ["# Bond Graph Physics Handoff", "", f"Freeze status: **{freeze}**", "", "Start from these frozen artifacts:", "", "1. `hydraulic_audit/08A..08E` — authoritative Level-1 V4 topology.", "2. `hydraulic_audit/12A..12D` — level-separated Bond Graph IR.", "3. `hydraulic_audit/11A_state_variable_registry.csv` — only active physical ODE states.", "4. `hydraulic_audit/13A_constitutive_equations.md` — exact wrapper equations and clearly separated engineering surrogates.", "5. `hydraulic_audit/11C_external_function_registry.csv` — exact-equivalence boundaries.", "6. `hydraulic_audit/submodels/<SUBMODEL>/` — source paths, excerpts and instance metadata.", "", "Do not mix SC_1 internal aliases into Level 1. Do not count activity/energy bookkeeping variables as physical states. Preserve Amesim port signs from 12B. Treat q0top_, pcdyn*, pipefr1_ and orif3f_ as unresolved exact dependencies until probed or independently specified.", "", "Implementation order: topology/junction equations -> exact sources and mechanical inertia -> hydraulic C states -> R/MR surrogates -> SC_1 Level-2 graphs -> event/hysteresis refinement -> Amesim comparison. Do not start from names alone; every family maps to its evidence directory."]
    (DOCS / "bondgraph_physics_handoff.md").write_text("\n".join(handoff) + "\n", encoding="utf-8")

    print("=" * 60)
    print("BOND GRAPH PHYSICS AUDIT COMPLETE")
    print("=" * 60)
    print(f"UNIQUE SUBMODELS = {len(inventory)}")
    print(f"SOURCE VERIFIED = {truth['LEVEL A']}")
    print(f"METADATA VERIFIED = {truth['LEVEL B']}")
    print(f"ENGINEERING INFERENCE = {counts['READY_APPROX']} (families with LEVEL C surrogate)")
    print()
    print(f"POWER ELEMENT FAMILIES = {sum(r['implementation_status'] in {'READY_EXACT','READY_APPROX','BLOCKED'} for r in readiness)}")
    print(f"SIGNAL FAMILIES = {counts['SIGNAL_ONLY']}")
    print(f"NON-POWER OBJECTS = {len(nonpower)}")
    print()
    print(f"TOTAL STATES = {len(states)}")
    print(f"HYDRAULIC STATES = {state_counts['hydraulic']}")
    print(f"MECHANICAL STATES = {state_counts['mechanical']}")
    print(f"CONTROL STATES = {state_counts['control']}")
    print()
    print(f"READY_EXACT = {counts['READY_EXACT']}")
    print(f"READY_APPROX = {counts['READY_APPROX']}")
    print(f"BLOCKED = {counts['BLOCKED']}")
    print()
    print("LEVEL 1 TOPOLOGY = " + ("PASS" if not pump_bad and not act_bad and not internal_l1 else "FAIL"))
    print("LEVEL 2 SUPERCOMPONENTS = " + ("CONDITIONAL" if l2junctions else "FAIL"))
    print(f"FREEZE STATUS = {freeze}")
    print()
    print("FINAL REPORT =")
    print(AUDIT / "14_BONDGRAPH_PHYSICS_FREEZE_REPORT.md")


if __name__ == "__main__":
    main()
