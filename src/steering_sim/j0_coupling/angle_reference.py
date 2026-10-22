"""Error-checked interpolation of the existing mechanical inverse model."""
from dataclasses import replace
import numpy as np


class AngleStrokeReference:
    def __init__(self, runner, case, start_deg, *, tolerance_m=1e-7, max_step_deg=0.25):
        self.channels = [item.channel for item in runner.config.channels]
        self.nodes = {}
        self.maximum_midpoint_error_m = 0.0

        def solve(angle):
            key = float(angle)
            if key not in self.nodes:
                target = runner.target(replace(case, target_outer_angle_deg=key))
                self.nodes[key] = np.array([target['x_ref'][name] for name in self.channels])
            return self.nodes[key]

        def refine(lo, hi, depth=0):
            mid = (lo+hi)/2
            a, b, exact = solve(lo), solve(hi), solve(mid)
            error = float(np.max(np.abs(exact-(a+b)/2)))
            if hi-lo > max_step_deg or error > tolerance_m:
                if depth >= 20:
                    raise ValueError('角度—行程插值未达到精度要求')
                refine(lo, mid, depth+1)
                refine(mid, hi, depth+1)
            else:
                self.maximum_midpoint_error_m = max(self.maximum_midpoint_error_m, error)

        low, high = sorted((float(start_deg), float(case.target_outer_angle_deg)))
        if low == high:
            solve(low)
        else:
            refine(low, high)
        self.angles = np.array(sorted(self.nodes))
        self.strokes = np.array([self.nodes[key] for key in self.angles])

    def at(self, angle, velocity_deg_s):
        if len(self.angles) == 1:
            return self.strokes[0].copy(), np.zeros(len(self.channels))
        index = int(np.clip(np.searchsorted(self.angles, angle, side='right')-1,
                            0, len(self.angles)-2))
        lo, hi = self.angles[index:index+2]
        derivative = (self.strokes[index+1]-self.strokes[index])/(hi-lo)
        return self.strokes[index]+(angle-lo)*derivative, derivative*velocity_deg_s
