# 32F Amesim scenario run diagnostics

All runs used isolated copies under `hydraulic_audit_lumped/amesim_r2_isolated/<scenario>/` with the original archive basename. Protected model SHA-256 before/after: `7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767` / `7613615723973d66a7122c74956c5161f720a64b243139fe9736cb270303b767`.

The earlier UD00 attempt failed because changing `nstages` changed the signal-source structure; Amesim returned `simulation failed to run for system`. R2 uses existing STEP0/SIN0 scalar parameters, saves only the isolated copy, regenerates code, and records `ame_api.log`.

The complete prior exception stack and per-scenario exit evidence remain in `hydraulic_audit_lumped/31_amesim_paired_raw.json` (`S1`/`S2`: `ame_apy.error` raised by `AMERunSimulation`). The final R2 runner exit status is 0 and its complete scalar/list results are in `32_amesim_paired_raw.json`. Successful Amesim API logs are empty because no warning or error was emitted.

- S0: success=True, simulation_wall_time_s=21.79114603996277, closed_without_save=True, error=
- S1: success=True, simulation_wall_time_s=23.66683053970337, closed_without_save=True, error=
- S2: success=True, simulation_wall_time_s=24.237197160720825, closed_without_save=True, error=

S1 applies a -0.1 step to the existing summing path, moving primary rear valve inputs from 1.0 to 0.9. S2 applies the existing 1 Hz SIN0 at amplitude 0.1; measured primary inputs range 0.9..1.1 and fractional spool saturates at 1.0. Python replays the measured downstream valve inputs.
