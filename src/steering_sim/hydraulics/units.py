"""Small, explicit AMESim-to-SI conversions used by R03-B1."""

BAR_TO_PA = 100_000.0
LPM_TO_M3PS = 1.0e-3 / 60.0
MM_TO_M = 1.0e-3
CM3_TO_M3 = 1.0e-6
CC_PER_REV_TO_M3_PER_REV = 1.0e-6
CST_TO_M2PS = 1.0e-6
CP_TO_PA_S = 1.0e-3


def bar_to_pa(value: float) -> float:
    return float(value) * BAR_TO_PA


def lpm_to_m3ps(value: float) -> float:
    return float(value) * LPM_TO_M3PS


def mm_to_m(value: float) -> float:
    return float(value) * MM_TO_M


def cm3_to_m3(value: float) -> float:
    return float(value) * CM3_TO_M3


def cc_per_rev_to_m3_per_rev(value: float) -> float:
    return float(value) * CC_PER_REV_TO_M3_PER_REV


def cst_to_m2ps(value: float) -> float:
    return float(value) * CST_TO_M2PS


def cp_to_pa_s(value: float) -> float:
    return float(value) * CP_TO_PA_S

