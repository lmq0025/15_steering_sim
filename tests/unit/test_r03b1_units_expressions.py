import math

import pytest

from steering_sim.hydraulics.expressions import SafeExpression, UnsafeExpressionError
from steering_sim.hydraulics.units import (
    bar_to_pa, cc_per_rev_to_m3_per_rev, cm3_to_m3, cp_to_pa_s,
    cst_to_m2ps, lpm_to_m3ps, mm_to_m,
)


def test_r03b1_unit_conversions():
    assert bar_to_pa(1) == 100_000.0
    assert lpm_to_m3ps(60) == pytest.approx(1e-3)
    assert mm_to_m(1000) == 1.0
    assert cm3_to_m3(1) == 1e-6
    assert cc_per_rev_to_m3_per_rev(1) == 1e-6
    assert cst_to_m2ps(1) == 1e-6
    assert cp_to_pa_s(1) == 1e-3


@pytest.mark.parametrize("x", [-1.0, -0.5, 0.0, 0.5, 1.0])
def test_frozen_dirvalve6_fx00_expressions(x):
    expressions = {
        "P-A": "+(x<=0)*(100+0*(x+1))+(0<x)*(100-100*(x-0))",
        "P-B": "+(x<=0)*(0+100*(x+1))+(0<x)*(100+0*(x-0))",
        "T-A": "+(x<=0)*(0+100*(x+1))+(0<x)*(100+0*(x-0))",
        "T-B": "+(x<=0)*(100+0*(x+1))+(0<x)*(100-100*(x-0))",
    }
    pa = SafeExpression(expressions["P-A"], variables=("x",)).evaluate(x=x)
    pb = SafeExpression(expressions["P-B"], variables=("x",)).evaluate(x=x)
    assert pa == pytest.approx(100.0 if x <= 0 else 100.0 * (1.0 - x))
    assert pb == pytest.approx(100.0 * (x + 1.0) if x <= 0 else 100.0)
    assert SafeExpression(expressions["T-A"], variables=("x",)).evaluate(x=x) == pytest.approx(pb)
    assert SafeExpression(expressions["T-B"], variables=("x",)).evaluate(x=x) == pytest.approx(pa)
    spool = SafeExpression("+(x<=0)*(-1+1*(x+1))+(0<x)*(0+1*(x-0))", variables=("x",))
    assert spool.evaluate(x=x) == pytest.approx(x)


def test_safe_expression_supports_evidence_backed_math():
    assert SafeExpression("sqrt(4/pi*area)", variables=("area",)).evaluate(area=math.pi) == pytest.approx(2.0)
    assert SafeExpression("fabs(x)^2", variables=("x",)).evaluate(x=-3) == 9.0


@pytest.mark.parametrize("raw", ["__import__('os').system('echo bad')", "x.__class__", "open('x')", "[x for x in (1,)]"])
def test_safe_expression_rejects_code_execution(raw):
    with pytest.raises(UnsafeExpressionError):
        SafeExpression(raw, variables=("x",))

