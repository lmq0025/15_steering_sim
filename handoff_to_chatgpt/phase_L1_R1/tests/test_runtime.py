import time
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


def test_runtime_smoke_not_a_hard_machine_benchmark(model, neutral):
    start = time.perf_counter()
    t, x = simulate_rk4(model, 1.0, .005, lambda _: neutral)
    assert t[-1] == 1.0 and x.shape == (201, 16)
    assert time.perf_counter()-start < 2.0
