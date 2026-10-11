"""PHASE M3：``REDESIGNED_ACKERMANN_TRANSMISSION`` 机构综合（SciPy 数值优化）。

对每个机构组独立做一次小规模参数优化，目标按任务书第七节的优先级排列：

1. 所有正常目标角下车轮转向方向正确（方向违规 = 极大罚）；
2. ±30° 全范围都有定义明确的机构解（不可解 / 分支跳变 = 极大罚）；
3. 十二轮理论角尽量接近理想阿克曼角（主目标，RMS 平方和）；
4. 行程连续、单调、无传动奇异（死点余量不足 = 罚）；
5. 左右转近似对称（镜像由构造保证，非对称 = 罚）。

**不改变**甲方任何原始铰点、杆长与液压缸安装点；优化变量只有新设计点：
中间摇臂枢轴 / 输入臂端点 / 输出臂端点 / 转向节转向臂端点 / 摆臂新拾取点。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
import sys

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from steering_sim.ackermann.redesign import (  # noqa: E402
    DESIGN_SCHEMA, REDESIGN_TAG, WHEEL_ORDER, GroupDesign, RedesignParameters,
    RelayDesign, build_group_chains, cylinder_stroke_m)
from steering_sim.ackermann.ideal import ideal_ackermann  # noqa: E402
from steering_sim.mechanics import reference_geometry_from_file  # noqa: E402

LEGACY_SIDE = {"left": "POS_Y", "right": "NEG_Y"}
REAR_AXLES = (4, 5, 6)
TARGETS_DEG = tuple(float(value) for value in range(-30, 31, 5))
TARGETS_FINE_DEG = tuple(float(value) for value in range(-30, 31, 2))

#: 死点余量下限（度）。低于此值即认为传动接近奇异。
TOGGLE_LIMIT_DEG = 32.0
#: 每个机构组的优化时间预算（秒）。到点即停，取当前最优参数。
TIME_BUDGET_S = 200.0


class _BudgetExceeded(RuntimeError):
    pass
#: 机构坐标扫描范围（rad）。
FRONT_Q_SPAN = 0.95
REAR_Q_SPAN = 0.95


def _chain_spec(reference, group_key: str, axle: int, relay: RelayDesign,
                swing_pickup: tuple[float, float], knuckle_tip: tuple[float, float]):
    """构造一个最小可评估的三刚体链（用于单桥优化时的快速评估）。"""
    from steering_sim.ackermann.redesign import (DRAG_PICKUP, _customer_body_points,
                                                 _mirror, _relay_body)
    from steering_sim.ackermann.planar import build_bodies, build_link, PlanarClosedChain
    pickup = DRAG_PICKUP[group_key] if group_key in DRAG_PICKUP else None
    pivots: dict[str, tuple[float, float]] = {}
    hardpoints: dict[str, dict[str, tuple[float, float]]] = {}
    for side in ("right", "left"):
        legacy = LEGACY_SIDE[side]
        swing = f"SWING_{axle}_{legacy}"
        wheel = f"WHEEL_{axle}_{legacy}"
        relay_body = f"RELAY_{axle}_{legacy}"
        pivots[swing] = tuple(map(float, reference.bodies[swing].pivot))
        hardpoints[swing] = {"SW": swing_pickup if side == "right"
                             else _mirror(swing_pickup)}
        pivots[wheel] = tuple(map(float, reference.bodies[wheel].pivot))
        hardpoints[wheel] = {"K": knuckle_tip if side == "right"
                             else _mirror(knuckle_tip)}
        points, hp = _relay_body(relay_body, relay if side == "right"
                                 else relay.mirrored())
        pivots.update(points)
        hardpoints.update(hp)
    bodies = build_bodies(pivots, hardpoints)
    specs = {
        "DRAG_R": ((f"SWING_{axle}_NEG_Y", "SW"), (f"RELAY_{axle}_NEG_Y", "IN")),
        "DRAG_L": ((f"SWING_{axle}_POS_Y", "SW"), (f"RELAY_{axle}_POS_Y", "IN")),
        "SIDE_R": ((f"RELAY_{axle}_NEG_Y", "OUT"), (f"WHEEL_{axle}_NEG_Y", "K")),
        "SIDE_L": ((f"RELAY_{axle}_POS_Y", "OUT"), (f"WHEEL_{axle}_POS_Y", "K")),
        "TRAP": ((f"WHEEL_{axle}_NEG_Y", "K"), (f"WHEEL_{axle}_POS_Y", "K")),
    }
    links = [build_link(name, a, b, bodies) for name, (a, b) in specs.items()]
    return PlanarClosedChain(f"OPT_AXLE{axle}", list(bodies.values()), links,
                             (f"SWING_{axle}_NEG_Y", f"SWING_{axle}_POS_Y"))


def _wheel_map(axle: int) -> dict[str, str]:
    return {f"WHEEL_{axle}_{LEGACY_SIDE[side]}": f"axle{axle}_{side}"
            for side in ("left", "right")}


def _scan_chain(chain, wheels, span: float, samples: int):
    """从 q=0 连续延拓出 q → 全部构件角的表；失败返回 None。

    返回完整构件角（而不是只返回轮角），这样单调行程判据与死点余量判据都能
    直接从同一张表算出来，不必再各扫一遍闭链——这正是之前目标函数慢 50 倍的
    原因。
    """
    step_size = min(span / max(samples, 1), 0.05)
    positive, negative = [], []
    for direction, store in ((1.0, positive), (-1.0, negative)):
        chain.reset()
        chain.solve(0.0)
        q = 0.0
        step = direction * step_size
        while abs(q + step) <= span + 1e-12:
            q_next = q + step
            try:
                solution = chain.solve(q_next)
            except Exception:
                break
            if solution.max_residual_m > 1.0e-9:
                break
            store.append((q_next, dict(solution.angles_rad)))
            q = q_next
    zero = {name: 0.0 for name in chain.body_names}
    rows = list(reversed(negative)) + [(0.0, zero)] + positive
    if len(rows) < 5:
        return None
    q_array = np.array([row[0] for row in rows], dtype=float)
    angle_array = {wheel: np.array([row[1][body] for row in rows], dtype=float)
                   for body, wheel in wheels.items()}
    return q_array, angle_array, rows


def _monotone_interval_from_rows(rows, reference, axle):
    """由同一张扫描表算"代表（A）缸行程严格单调且包含 q=0"的最大区间。"""
    from steering_sim.ackermann.redesign import cylinder_stroke_m

    grid = np.array([row[0] for row in rows], dtype=float)
    values = np.array([cylinder_stroke_m(reference, axle, "right",
                                         float(row[1][f"SWING_{axle}_NEG_Y"]))
                       for row in rows], dtype=float)
    if len(grid) < 9:
        return 0.0, 0.0
    zero = int(np.argmin(np.abs(grid)))
    step = np.diff(values)
    base = step[zero] if zero < len(step) else 0.0
    if base == 0.0:
        base = 1.0
    upper, lower = float(grid[-1]), float(grid[0])
    for index in range(zero, len(step)):
        if step[index] * base <= 0.0:
            upper = float(grid[index])
            break
    for index in range(zero - 1, -1, -1):
        if step[index] * base <= 0.0:
            lower = float(grid[index + 1])
            break
    return lower, upper


def _evaluate(chain, wheels, centers, axles, targets, span, samples, *,
              reference=None, axle=None):
    """返回 (代价[deg²], 诊断字典)。

    代价 = 各目标角下"左右轮对理想阿克曼角 RMS 偏差"的平方，对目标角取平均。
    单位是 deg²，因此可以直接和下面的几何惩罚项加权相加。

    传入 ``reference`` / ``axle`` 时，还会要求每个目标角拟合出的机构坐标落在
    **代表缸行程严格单调**的区间内（否则 J0 无法把行程唯一反解回机构坐标）。
    """
    table = _scan_chain(chain, wheels, span, samples)
    penalty = 0.0
    diagnostics = {"reach_deg": 0.0, "worst_rms_deg": 0.0,
                   "direction_violations": 0, "coverage": 0,
                   "monotone_lo_deg": 0.0, "monotone_hi_deg": 0.0,
                   "outside_monotone": 0}
    if table is None:
        return 1.0e4 + penalty, diagnostics
    q_array, angle_array, rows = table
    diagnostics["reach_deg"] = math.degrees(float(np.max(np.abs(q_array))))
    monotone = None
    if reference is not None and axle is not None:
        lo, hi = _monotone_interval_from_rows(rows, reference, axle)
        monotone = (lo, hi)
        diagnostics["monotone_lo_deg"] = math.degrees(lo)
        diagnostics["monotone_hi_deg"] = math.degrees(hi)
        # 单调区间必须覆盖足够的双向范围，否则转向范围会被行程折返截断。
        for value in (lo, hi):
            if abs(value) < 0.80:
                penalty += (0.80 - abs(value)) ** 2 * 400.0
    if _toggle_pairs(chain):
        penalty += _toggle_penalty_from_rows(chain, rows)
    total = 0.0
    count = 0
    group_wheels = [f"axle{axle}_{side}" for axle in axles for side in ("left", "right")]
    for target in targets:
        ideal = ideal_ackermann(target, centers)
        cost = np.zeros_like(q_array)
        for wheel in group_wheels:
            cost += (angle_array[wheel] - math.radians(ideal.angles_deg[wheel])) ** 2
        index = int(np.argmin(cost))
        if index in (0, len(q_array) - 1):
            # 目标角落在扫描端点：说明该目标需要超出可达范围的 q。
            penalty += 30.0
        else:
            diagnostics["coverage"] += 1
        if monotone is not None:
            q_best = float(q_array[index])
            if q_best < monotone[0] - 1e-9 or q_best > monotone[1] + 1e-9:
                outside = max(monotone[0] - q_best, q_best - monotone[1], 0.0)
                penalty += outside * outside * 4000.0
                diagnostics["outside_monotone"] += 1
        rms = math.degrees(math.sqrt(float(cost[index]) / len(group_wheels)))
        diagnostics["worst_rms_deg"] = max(diagnostics["worst_rms_deg"], rms)
        total += rms * rms
        count += 1
        for wheel in group_wheels:
            want = ideal.angles_deg[wheel]
            got = math.degrees(float(angle_array[wheel][index]))
            if abs(want) > 0.05 and abs(got) > 0.05 and \
                    math.copysign(1.0, got) != math.copysign(1.0, want):
                penalty += 200.0
                diagnostics["direction_violations"] += 1
    return total / max(count, 1) + penalty, diagnostics


def _penalties(reference, group_key, axle, relay, swing_pickup, knuckle_tip):
    """几何合理性与死点余量罚。"""
    from steering_sim.ackermann.planar import toggle_margin_deg
    value = 0.0
    s_pivot = np.asarray(reference.bodies[f"SWING_{axle}_NEG_Y"].pivot, dtype=float)
    w_pivot = np.asarray(reference.bodies[f"WHEEL_{axle}_NEG_Y"].pivot, dtype=float)
    r_pivot = np.asarray(relay.pivot, dtype=float)
    arm_sw = float(np.linalg.norm(np.asarray(swing_pickup) - s_pivot))
    arm_in = float(np.linalg.norm(np.asarray(relay.input_tip) - r_pivot))
    arm_out = float(np.linalg.norm(np.asarray(relay.output_tip) - r_pivot))
    arm_k = float(np.linalg.norm(np.asarray(knuckle_tip) - w_pivot))
    for arm, low, high in ((arm_sw, 0.18, 0.55), (arm_in, 0.12, 0.60),
                           (arm_out, 0.12, 0.60), (arm_k, 0.22, 0.75)):
        if arm < low:
            value += (low - arm) ** 2 * 400.0
        elif arm > high:
            value += (arm - high) ** 2 * 400.0
    # 新点必须位于右侧半平面，且不越出车轮中心线太远（避免进入轮胎区域）。
    for point in (relay.pivot, relay.input_tip, relay.output_tip, swing_pickup,
                  knuckle_tip):
        y = float(point[1])
        if y > -0.05:
            value += (y + 0.05) ** 2 * 400.0
        if y < -1.55:
            value += (-1.55 - y) ** 2 * 400.0
    ground_drag = float(np.linalg.norm(r_pivot - s_pivot))
    ground_side = float(np.linalg.norm(r_pivot - w_pivot))
    for ground in (ground_drag, ground_side):
        if ground < 0.45:
            value += (0.45 - ground) ** 2 * 200.0
        if ground > 2.2:
            value += (ground - 2.2) ** 2 * 200.0
    # 死点余量：直接对新机构在零位与两个极限附近做解析检查。
    return value


def _toggle_pairs(chain):
    """参与死点判据的连杆（新设计的拉杆），(body_a, point_a, body_b, point_b)。"""
    pairs = []
    for link in chain.links:
        if link.name.startswith(("DRAG", "SIDE")):
            pairs.append((link.endpoint_a[0], link.endpoint_a[1],
                          link.endpoint_b[0], link.endpoint_b[1]))
    return tuple(pairs)


def _toggle_penalty_from_rows(chain, rows):
    """由同一张扫描表算死点余量与零位雅可比条件数罚（不再重复扫闭链）。"""
    margins = []
    for _, angles in rows:
        for body_a, point_a, body_b, point_b in _toggle_pairs(chain):
            pa = chain.bodies[chain.body_index[body_a]].world_point(point_a, angles[body_a])
            pb = chain.bodies[chain.body_index[body_b]].world_point(point_b, angles[body_b])
            pivot_b = np.asarray(chain.bodies[chain.body_index[body_b]].pivot, dtype=float)
            pivot_a = np.asarray(chain.bodies[chain.body_index[body_a]].pivot, dtype=float)
            for anchor, pivot, other in ((pa, pivot_a, pb), (pb, pivot_b, pa)):
                arm = anchor - pivot
                if float(np.linalg.norm(arm)) < 1e-9:
                    continue
                angle = math.degrees(math.atan2(*(other - anchor)[::-1])
                                     - math.atan2(arm[1], arm[0]))
                relative = (angle + 180.0) % 360.0 - 180.0
                margins.append(min(abs(relative), 180.0 - abs(relative)))
    if not margins:
        return 0.0
    value = 0.0
    worst = min(margins)
    if worst < TOGGLE_LIMIT_DEG:
        value += (TOGGLE_LIMIT_DEG - worst) ** 2 * 1.5
    try:
        condition = float(chain.solve(0.0).condition_number)
    except Exception:
        return value + 50.0
    if condition > 1.0e4:
        value += min(200.0, math.log10(condition) ** 2)
    return value


# ------------------------------------------------------------------ 变量打包
def _unpack_rear(vector, axle, group_key):
    return (RelayDesign((vector[0], vector[1]), (vector[2], vector[3]),
                        (vector[4], vector[5])),
            (vector[6], vector[7]), (vector[8], vector[9]))


def _pack_rear(relay, swing_pickup, knuckle_tip):
    return [relay.pivot[0], relay.pivot[1], relay.input_tip[0], relay.input_tip[1],
            relay.output_tip[0], relay.output_tip[1], swing_pickup[0], swing_pickup[1],
            knuckle_tip[0], knuckle_tip[1]]


def optimise_rear(reference, centers, axle, span=REAR_Q_SPAN, samples=16,
                  restarts=1, verbose=True):
    group_key = f"axle{axle}"
    wheels = _wheel_map(axle)
    cache: dict[tuple, float] = {}

    def objective(vector):
        key = tuple(round(float(value), 9) for value in vector)
        if key in cache:
            return cache[key]
        relay, swing_pickup, knuckle_tip = _unpack_rear(vector, axle, group_key)
        try:
            chain = _chain_spec(reference, group_key, axle, relay, swing_pickup,
                                knuckle_tip)
            cost, _ = _evaluate(chain, wheels, centers, (axle,), TARGETS_DEG, span,
                                samples, reference=reference, axle=axle)
        except Exception:
            value = 1.0e5
        else:
            value = cost + _penalties(reference, group_key, axle, relay, swing_pickup,
                                      knuckle_tip)
        cache[key] = value
        if value < tracker["best"][0]:
            tracker["best"] = (value, np.asarray(vector, dtype=float).copy())
        if time.perf_counter() > deadline:
            raise _BudgetExceeded()
        return value

    best = None
    deadline = time.perf_counter() + TIME_BUDGET_S
    tracker = {"best": (float("inf"), None)}
    seeds = seeds_rear(reference, axle)

    def cheap(vector):
        relay, swing_pickup, knuckle_tip = _unpack_rear(vector, axle, group_key)
        try:
            chain = _chain_spec(reference, group_key, axle, relay, swing_pickup,
                                knuckle_tip)
            cost, _ = _evaluate(chain, wheels, centers, (axle,), TARGETS_DEG, span, 8,
                                reference=reference, axle=axle)
        except Exception:
            return 1.0e5
        return cost + _penalties(reference, group_key, axle, relay, swing_pickup,
                                 knuckle_tip)

    scored = sorted(seeds, key=lambda item: cheap(_pack_rear(*item)))
    for seed in scored[:restarts]:
        try:
            result = minimize(objective, _pack_rear(*seed), method="Powell",
                              options={"maxiter": 400, "xtol": 1e-3, "ftol": 1e-6})
        except _BudgetExceeded:
            break
        if best is None or result.fun < best[0]:
            best = (float(result.fun), result.x.copy())
    if tracker["best"][1] is not None and (best is None or tracker["best"][0] < best[0]):
        best = (float(tracker["best"][0]), tracker["best"][1])
    relay, swing_pickup, knuckle_tip = _unpack_rear(best[1], axle, group_key)
    chain = _chain_spec(reference, group_key, axle, relay, swing_pickup, knuckle_tip)
    cost, diagnostics = _evaluate(chain, wheels, centers, (axle,), TARGETS_FINE_DEG,
                                  span, samples * 4, reference=reference, axle=axle)
    if verbose:
        print(f"[{group_key}] objective={best[0]:.4f} rms_cost={cost:.4f} deg^2 "
              f"reach={diagnostics['reach_deg']:.2f}deg "
              f"dirviol={diagnostics['direction_violations']} "
              f"worstRMS={diagnostics['worst_rms_deg']:.3f}deg "
              f"coverage={diagnostics['coverage']}/{len(TARGETS_DEG)}")
        print(f"    relay pivot=({relay.pivot[0]:.4f},{relay.pivot[1]:.4f}) "
              f"in=({relay.input_tip[0]:.4f},{relay.input_tip[1]:.4f}) "
              f"out=({relay.output_tip[0]:.4f},{relay.output_tip[1]:.4f})")
        print(f"    swing pickup=({swing_pickup[0]:.4f},{swing_pickup[1]:.4f}) "
              f"knuckle tip=({knuckle_tip[0]:.4f},{knuckle_tip[1]:.4f})")
    return relay, swing_pickup, knuckle_tip, diagnostics


def _unit(angle_rad: float) -> np.ndarray:
    return np.array([math.cos(angle_rad), math.sin(angle_rad)])


def icr_x_m(reference) -> float:
    return 0.5 * (float(reference.bodies["WHEEL_3_NEG_Y"].pivot[0])
                  + float(reference.bodies["WHEEL_3_POS_Y"].pivot[0]))


def seeds_rear(reference, axle):
    """构造一组物理上合理的初始设计，供多起点优化使用。

    关键约束：转向节转向臂**不能正好沿 ±y（横向）**。此时梯形横拉杆在零位对
    "左右轮反向转动"的一阶灵敏度为零，机构雅可比奇异（condition number = ∞）。
    阿克曼梯形的经典做法是让转向臂大致指向共同瞬时转向中心（近乎纵向），
    既避开奇异，又让横拉杆长度对转角的二阶项产生正确的差动。
    """
    s_pivot = np.asarray(reference.bodies[f"SWING_{axle}_NEG_Y"].pivot, dtype=float)
    w_pivot = np.asarray(reference.bodies[f"WHEEL_{axle}_NEG_Y"].pivot, dtype=float)
    x_icr = icr_x_m(reference)
    psi_ack = math.atan2(0.0 - w_pivot[1], x_icr - w_pivot[0])
    results = []
    offsets = (0.0, 20.0, -20.0, 40.0, -40.0)
    for base in (math.degrees(psi_ack), math.degrees(psi_ack) + 180.0):
        for offset in offsets:
            psi_k = math.radians(base + offset)
            for arm_k in (0.32, 0.48, 0.64):
                knuckle_tip = w_pivot + arm_k * _unit(psi_k)
                for sign in (1.0, -1.0):
                    for distance in (0.65, 0.90, 1.15):
                        relay_pivot = w_pivot + distance * _unit(psi_k + sign * math.pi / 2)
                        if not (-1.45 < relay_pivot[1] < -0.10):
                            continue
                        link_angle = math.atan2(*(knuckle_tip - relay_pivot)[::-1])
                        ground = relay_pivot - s_pivot
                        ground_angle = math.atan2(ground[1], ground[0])
                        for out_sign in (1.0, -1.0):
                            relay_output = relay_pivot + 0.30 * _unit(
                                link_angle + out_sign * math.pi / 2)
                            for in_sign in (1.0, -1.0):
                                swing_pickup = s_pivot + 0.34 * _unit(
                                    ground_angle + in_sign * math.pi / 2)
                                relay_input = relay_pivot + 0.30 * _unit(
                                    ground_angle - in_sign * math.pi / 2)
                                results.append((
                                    RelayDesign(tuple(relay_pivot), tuple(relay_input),
                                                tuple(relay_output)),
                                    tuple(swing_pickup), tuple(knuckle_tip)))
    return results


def seed_rear(reference, axle):
    """返回第一个可用初值（兼容旧调用）。"""
    return seeds_rear(reference, axle)[0]


# ------------------------------------------------------------------ 前组
def _front_design(relay1: RelayDesign, tip1, tip2, swing1=None, swing2=None):
    pickups = {}
    if swing1 is not None:
        pickups[1] = tuple(swing1)
    if swing2 is not None:
        pickups[2] = tuple(swing2)
    return GroupDesign(key="front", axles=(1, 2), relays={1: relay1},
                       knuckle_tips={1: tuple(tip1), 2: tuple(tip2)},
                       swing_pickups=pickups)


def _front_chain(reference, design: GroupDesign):
    from steering_sim.ackermann.redesign import build_group_chains
    parameters = RedesignParameters(schema_version=DESIGN_SCHEMA, tag=REDESIGN_TAG,
                                    groups={"front": design,
                                            "axle4": design, "axle5": design,
                                            "axle6": design})
    return build_group_chains(reference, parameters)["front"]


def _build_front_chain(reference, relay1, tip1, tip2, swing1, swing2):
    """只用前组构造闭链（绕过 build_group_chains 对另外三组的强制要求）。"""
    from steering_sim.ackermann.redesign import (_build_front_group)
    design = _front_design(relay1, tip1, tip2, swing1, swing2)
    build = _build_front_group(reference, design)
    return build.chain, build.wheels


def seeds_front(reference):
    w1 = np.asarray(reference.bodies["WHEEL_1_NEG_Y"].pivot, dtype=float)
    x_icr = icr_x_m(reference)
    psi_ack = math.atan2(0.0 - w1[1], x_icr - w1[0])
    results = []
    for offset in (0.0, 25.0, -25.0, 50.0, -50.0):
        for base_turn in (0.0, 180.0):
            psi_k = math.radians(math.degrees(psi_ack) + base_turn + offset)
            for arm_k in (0.34, 0.52):
                tip1 = w1 + arm_k * _unit(psi_k)
                for sign in (1.0, -1.0):
                    for distance in (0.75, 1.10):
                        relay_pivot = w1 + distance * _unit(psi_k + sign * math.pi / 2)
                        if not (-1.45 < relay_pivot[1] < -0.10):
                            continue
                        link_angle = math.atan2(*(tip1 - relay_pivot)[::-1])
                        for out_sign in (1.0, -1.0):
                            relay_output = relay_pivot + 0.30 * _unit(
                                link_angle + out_sign * math.pi / 2)
                            for in_sign in (1.0, -1.0):
                                ground = relay_pivot - np.asarray(
                                    reference.bodies["SWING_1_NEG_Y"].pivot, dtype=float)
                                ground_angle = math.atan2(ground[1], ground[0])
                                relay_input = relay_pivot + 0.30 * _unit(
                                    ground_angle - in_sign * math.pi / 2)
                                for offset2 in (0.0, 20.0, -20.0):
                                    w2 = np.asarray(reference.bodies["WHEEL_2_NEG_Y"].pivot,
                                                    dtype=float)
                                    psi2 = math.atan2(0.0 - w2[1], x_icr - w2[0])
                                    psi_k2 = math.radians(math.degrees(psi2) + offset2)
                                    tip2 = w2 + 0.42 * _unit(psi_k2)
                                    results.append((RelayDesign(
                                        tuple(relay_pivot), tuple(relay_input),
                                        tuple(relay_output)), tuple(tip1), tuple(tip2)))
    return results


def _front_penalties(reference, relay1, tip1, tip2):
    value = 0.0
    w1 = np.asarray(reference.bodies["WHEEL_1_NEG_Y"].pivot, dtype=float)
    w2 = np.asarray(reference.bodies["WHEEL_2_NEG_Y"].pivot, dtype=float)
    r_pivot = np.asarray(relay1.pivot, dtype=float)
    for point, low, high, axis in (
            (np.linalg.norm(np.asarray(tip1) - w1), 0.24, 0.72, "tip1"),
            (np.linalg.norm(np.asarray(tip2) - w2), 0.24, 0.72, "tip2"),
            (np.linalg.norm(np.asarray(relay1.input_tip) - r_pivot), 0.12, 0.60, "in"),
            (np.linalg.norm(np.asarray(relay1.output_tip) - r_pivot), 0.12, 0.60, "out")):
        if point < low:
            value += (low - point) ** 2 * 400.0
        elif point > high:
            value += (point - high) ** 2 * 400.0
    for point in (relay1.pivot, relay1.input_tip, relay1.output_tip, tip1, tip2):
        y = float(point[1])
        if y > -0.05:
            value += (y + 0.05) ** 2 * 400.0
        if y < -1.55:
            value += (-1.55 - y) ** 2 * 400.0
    return value


def optimise_front(reference, centers, span=FRONT_Q_SPAN, samples=16, restarts=1,
                   verbose=True):
    cache: dict[tuple, float] = {}

    def objective(vector):
        key = tuple(round(float(value), 9) for value in vector)
        if key in cache:
            return cache[key]
        relay1 = RelayDesign((vector[0], vector[1]), (vector[2], vector[3]),
                             (vector[4], vector[5]))
        tip1 = (vector[6], vector[7])
        tip2 = (vector[8], vector[9])
        try:
            chain, wheels = _build_front_chain(reference, relay1, tip1, tip2, None, None)
            cost, _ = _evaluate(chain, wheels, centers, (1, 2), TARGETS_DEG, span,
                                samples)
        except Exception:
            value = 1.0e5
        else:
            value = cost + _front_penalties(reference, relay1, tip1, tip2)
        cache[key] = value
        if value < tracker["best"][0]:
            tracker["best"] = (value, np.asarray(vector, dtype=float).copy())
        if time.perf_counter() > deadline:
            raise _BudgetExceeded()
        return value

    def pack(seed):
        relay1, tip1, tip2 = seed
        return [relay1.pivot[0], relay1.pivot[1], relay1.input_tip[0],
                relay1.input_tip[1], relay1.output_tip[0], relay1.output_tip[1],
                tip1[0], tip1[1], tip2[0], tip2[1]]

    deadline = time.perf_counter() + TIME_BUDGET_S
    tracker = {"best": (float("inf"), None)}

    def cheap_front(vector):
        relay1 = RelayDesign((vector[0], vector[1]), (vector[2], vector[3]),
                             (vector[4], vector[5]))
        tip1 = (vector[6], vector[7])
        tip2 = (vector[8], vector[9])
        try:
            chain, wheels = _build_front_chain(reference, relay1, tip1, tip2, None, None)
            cost, _ = _evaluate(chain, wheels, centers, (1, 2), TARGETS_DEG, span, 8)
        except Exception:
            return 1.0e5
        return cost + _front_penalties(reference, relay1, tip1, tip2)

    scored = sorted(seeds_front(reference), key=lambda item: cheap_front(pack(item)))
    best = None
    for seed in scored[:restarts]:
        try:
            result = minimize(objective, pack(seed), method="Powell",
                              options={"maxiter": 500, "xtol": 1e-3, "ftol": 1e-6})
        except _BudgetExceeded:
            break
        if best is None or result.fun < best[0]:
            best = (float(result.fun), result.x.copy())
    if tracker["best"][1] is not None and (best is None or tracker["best"][0] < best[0]):
        best = (float(tracker["best"][0]), tracker["best"][1])
    vector = best[1]
    relay1 = RelayDesign((vector[0], vector[1]), (vector[2], vector[3]),
                         (vector[4], vector[5]))
    tip1, tip2 = (vector[6], vector[7]), (vector[8], vector[9])
    chain, wheels = _build_front_chain(reference, relay1, tip1, tip2, None, None)
    cost, diagnostics = _evaluate(chain, wheels, centers, (1, 2), TARGETS_FINE_DEG,
                                  span, samples * 4)
    if verbose:
        print(f"[front] objective={best[0]:.4f} rms_cost={cost:.4f} deg^2 "
              f"reach={diagnostics['reach_deg']:.2f}deg "
              f"dirviol={diagnostics['direction_violations']} "
              f"worstRMS={diagnostics['worst_rms_deg']:.3f}deg "
              f"coverage={diagnostics['coverage']}/{len(TARGETS_DEG)}")
        print(f"    relay pivot=({relay1.pivot[0]:.4f},{relay1.pivot[1]:.4f}) "
              f"in=({relay1.input_tip[0]:.4f},{relay1.input_tip[1]:.4f}) "
              f"out=({relay1.output_tip[0]:.4f},{relay1.output_tip[1]:.4f})")
        print(f"    knuckle tip1=({tip1[0]:.4f},{tip1[1]:.4f}) "
              f"tip2=({tip2[0]:.4f},{tip2[1]:.4f})")
    return relay1, tip1, tip2, diagnostics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geometry", default=str(ROOT / "mechanical_model_input_spec_v1.0.yaml"))
    parser.add_argument("--out", default=str(ROOT / "mechanics_ackermann_redesigned" / "design_parameters.json"))
    parser.add_argument("--axles", default="4,5,6")
    parser.add_argument("--samples", type=int, default=60)
    args = parser.parse_args()

    reference = reference_geometry_from_file(args.geometry)
    centers = {}
    for axle in range(1, 7):
        for side, legacy in (("left", "POS_Y"), ("right", "NEG_Y")):
            pivot = reference.bodies[f"WHEEL_{axle}_{legacy}"].pivot
            centers[f"axle{axle}_{side}"] = (float(pivot[0]), float(pivot[1]))

    groups: dict[str, GroupDesign] = {}
    if "front" in args.axles:
        relay1, tip1, tip2, _ = optimise_front(reference, centers, samples=args.samples)
        groups["front"] = _front_design(relay1, tip1, tip2)
    for axle in [int(value) for value in args.axles.split(",") if value.isdigit()]:
        relay, swing_pickup, knuckle_tip, _ = optimise_rear(
            reference, centers, axle, samples=args.samples)
        # 摆臂新拾取点与甲方原始拾取点合并存储：只用新点，甲方点保持不变。
        groups[f"axle{axle}"] = GroupDesign(
            key=f"axle{axle}", axles=(axle,),
            relays={axle: relay},
            knuckle_tips={axle: knuckle_tip},
            swing_pickups={axle: swing_pickup},
            notes=(f"swing_pickup_NEG_Y={swing_pickup}",))
    path = Path(args.out)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        for key, item in existing.get("groups", {}).items():
            if key not in groups:
                groups[key] = GroupDesign.from_dict(item)
    parameters = RedesignParameters(schema_version=DESIGN_SCHEMA, tag=REDESIGN_TAG,
                                    groups=groups, provenance={})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(parameters.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
