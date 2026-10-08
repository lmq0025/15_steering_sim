import numpy as np

from steering_sim.hydraulics.elements import ComplianceLine, ResistiveComplianceLine, SegmentedLine


def test_compliance_pressure_rhs_sign():
    line = ComplianceLine(volume_m3=1e-4, bulk_modulus_pa=1.7e9)
    assert line.pressure_rhs_pa_s(1e-5) > 0.0
    assert line.pressure_rhs_pa_s(-1e-5) < 0.0


def test_rc_line_relaxes_toward_boundary_pressure():
    line = ResistiveComplianceLine(1e-4, 1.7e9, 1e10, 1e15)
    assert line.pressure_rhs_pa_s(2e6, 3e6, 3e6) > 0.0


def test_segmented_line_has_one_rhs_per_cell():
    line = SegmentedLine(np.full(3, 1e-5), 1.7e9, 1e10, 1e15)
    rhs = line.rhs(np.array([3e6, 2e6, 1e6]), 4e6, 0.0)
    assert rhs.shape == (3,)
    assert np.all(np.isfinite(rhs))
