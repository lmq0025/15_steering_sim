import time
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


def test_runtime_smoke_not_a_hard_machine_benchmark(model, neutral):
    start = time.perf_counter()
    t, x = simulate_rk4(model, 0.02, .0005, lambda _: neutral)
    assert t[-1] == 0.02 and x.shape == (41, 16)
    # This remains a smoke test.  Machine-dependent performance is reported
    # by 33K, not enforced through a misleading old one-node timing bound.
    assert time.perf_counter()-start < 5.0
