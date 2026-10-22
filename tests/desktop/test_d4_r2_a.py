from pathlib import Path
import numpy as np
from steering_sim.desktop.response_analysis import linear_ramp_profile
from steering_sim.desktop.services import _runner
from steering_sim.j0_coupling.config import J0CaseConfig


def test_angle_reference_is_inverse_kinematics_not_stroke_interpolation():
    runner = _runner()
    case = J0CaseConfig(id='R2_A', target_outer_angle_deg=10, speed_kmh=5, duration_s=0.04)
    result = runner.run_case(case, profile=linear_ramp_profile(60), reference_space='outer_angle')
    assert result.completed, result.failure_reason
    samples = result.samples
    np.testing.assert_allclose(samples['outer_angle_reference_deg'], samples['time_s']/6, atol=1e-14)
    for i, t in enumerate(samples['time_s']):
        control_time = np.floor((t + 1e-10)/runner.dt_c)*runner.dt_c
        target = runner.target(J0CaseConfig(id='ref', target_outer_angle_deg=control_time/6,
                                           speed_kmh=5, duration_s=1))
        assert abs(samples['channel_front_x_ref_eff_m'][i]-target['x_ref']['channel_front']) < 1e-7
    assert not np.array_equal(samples['channel_front_x_m'], samples['channel_front_x_ref_eff_m'])


def test_cross_zero_reference_direction_and_continuity():
    profile = linear_ramp_profile(120)
    time = np.arange(0, 121, 0.01)
    angles = np.array([10+profile(t)[0]*(-20) for t in time])
    np.testing.assert_allclose(angles[time<=120], 10-time[time<=120]/6, atol=1e-12)
    assert angles[-1] == -10


def test_action_preview_project_restore_and_batch_coverage():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from steering_sim.desktop.app import MainWindow
    qt = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = window.pages[0]
    page.command_type.setCurrentIndex(1)
    assert page.from_straight.isChecked()
    assert not page.initial_angle.isEnabled()
    page.from_straight.setChecked(False)
    page.initial_angle.setValue(8)
    page.angle.setValue(10)
    assert '12 秒' in page.action_preview.text()
    payload = page.project_payload()
    window._apply_page_inputs({'simulation': payload})
    assert page.initial_angle.value() == 8
    assert not page.from_straight.isChecked()
    captured = []
    page.run_requested.disconnect()
    page.run_requested.connect(lambda name, data: captured.append((name,data)))
    page._batch()
    rows = captured[-1][1]['scenarios']
    assert len(rows) == 3111
    assert {r['speed_kmh'] for r in rows} == set(range(0,81,5))
    assert {r['friction_coefficient'] for r in rows} == {0.70,0.75,0.80}
    assert {r['target_outer_angle_deg'] for r in rows} == set(range(-30,31))
    window.close()


def test_wheel_and_channel_titles_follow_selected_data():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from steering_sim.desktop.pages import SimulationPage
    from steering_sim.desktop.response_analysis import analyze_response, ResponseCriteria
    from steering_sim.j0_coupling.runner import WHEELS, CHANNEL_ORDER
    qt = QApplication.instance() or QApplication([])
    page = SimulationPage()
    time = np.linspace(0, 5, 501)
    samples = {'time_s': time}
    for wheel in WHEELS:
        samples[f'wheel_{wheel}_command_deg'] = np.zeros_like(time)
        samples[f'wheel_{wheel}_actual_deg'] = np.zeros_like(time)
    for channel in CHANNEL_ORDER:
        for suffix in ('x_ref_eff_m', 'x_m', 'v_m_s'):
            samples[f'{channel}_{suffix}'] = np.zeros_like(time)
    page.last_result = {'kind': 'simulation', 'samples': samples,
                       'response': analyze_response(samples, 0, ResponseCriteria())}
    page.wheel_selector.setCurrentIndex(8)
    assert '5桥左轮' in page.angle_plot.plotItem.titleLabel.text
    page.cylinder_selector.setCurrentIndex(2)
    assert '五桥' in page.cylinder_plot.plotItem.titleLabel.text
    page.close()
