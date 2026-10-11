# Phase L1-S1 original runtime profile

This profile freezes the unmodified Phase L1-R3 S2 periodic workload. It uses RK4 with a 0.5 ms step and prescribed Amesim motion boundary.

- 1 s wall time: 11.530161 s
- 10 s wall time: 115.064383 s
- Frozen measured 100 s wall time: 458.562957 s
- 10 s RHS calls: 80000

## Required hotspot categories

| category | calls | self s | cumulative s | matched location |
|---|---:|---:|---:|---|
| solve_sc1_load_sensing_network | 160000 | 2.561043 | 101.140411 | supply.py:185:solve_sc1_load_sensing_network |
| network_at_low | 1428984 | 5.385479 | 96.570030 | supply.py:201:network_at_low |
| return_residual | 1268984 | 1.024840 | 81.142509 | supply.py:260:return_residual |
| brentq | 176 | 0.000776 | 0.439450 | _zeros_py.py:712:brentq |
| sc1_four_port_flows | 5949118 | 28.307108 | 79.206019 | valve.py:86:sc1_four_port_flows |
| fractional_area_percent | 20087092 | 12.366428 | 21.775967 | valve.py:49:fractional_area_percent |
| characteristic_orifice_flow | 20087092 | 10.707965 | 16.319817 | valve.py:67:characteristic_orifice_flow |
| evaluate | 80000 | 6.168458 | 113.585193 | model.py:67:evaluate |
| inputs | 80000 | 0.101712 | 0.563411 | run_phase_l1_s1_baseline.py:37:periodic_inputs |
| simulate_rk4 | 1 | 0.606693 | 115.064263 | simulation.py:12:simulate_rk4 |

## Top 40 cumulative profile entries

```text
         298699877 function calls in 114.453 seconds

   Ordered by: cumulative time
   List reduced from 83 to 40 due to restriction <40>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.607    0.607  115.064  115.064 E:\15_project\src\steering_sim\hydraulics_lumped\simulation.py:12(simulate_rk4)
    80000    0.309    0.000  113.894    0.001 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:183(rhs)
    80000    6.168    0.000  113.585    0.001 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:67(evaluate)
   160000    2.561    0.000  101.140    0.001 E:\15_project\src\steering_sim\hydraulics_lumped\supply.py:185(solve_sc1_load_sensing_network)
  1428984    5.385    0.000   96.570    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\supply.py:201(network_at_low)
  2857968    8.100    0.000   88.958    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\supply.py:208(build)
  1268984    1.025    0.000   81.143    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\supply.py:260(return_residual)
  5949118   28.307    0.000   79.206    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\valve.py:86(sc1_four_port_flows)
 20087092   12.366    0.000   21.776    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\valve.py:49(fractional_area_percent)
 20087092   10.708    0.000   16.320    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\valve.py:67(characteristic_orifice_flow)
 99899956   11.538    0.000   11.654    0.000 {built-in method builtins.max}
 66899102    8.478    0.000    8.478    0.000 {built-in method builtins.min}
  5949118    7.230    0.000    7.230    0.000 <string>:2(__init__)
  3828984    2.073    0.000    4.607    0.000 {built-in method builtins.sum}
 20087092    1.813    0.000    1.813    0.000 {method 'split' of 'str' objects}
   320000    0.897    0.000    1.584    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\actuator.py:28(actuator_rates)
 16138236    1.146    0.000    1.146    0.000 {method 'append' of 'list' objects}
  9029036    0.830    0.000    0.830    0.000 {built-in method math.sqrt}
   960000    0.451    0.000    0.798    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:145(<genexpr>)
    80000    0.102    0.000    0.563    0.000 E:\15_project\scripts\hydraulics\run_phase_l1_s1_baseline.py:37(periodic_inputs)
  4403543    0.537    0.000    0.537    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\supply.py:257(<genexpr>)
   480000    0.301    0.000    0.500    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:79(<genexpr>)
      176    0.001    0.000    0.439    0.002 E:\ProgramData\condaData\envs_dirs\steering_sim\Lib\site-packages\scipy\optimize\_zeros_py.py:712(brentq)
      176    0.001    0.000    0.438    0.002 {built-in method scipy.optimize._zeros._brentq}
     2684    0.006    0.000    0.436    0.000 E:\ProgramData\condaData\envs_dirs\steering_sim\Lib\site-packages\scipy\optimize\_zeros_py.py:93(f_raise)
    80000    0.158    0.000    0.424    0.000 E:\15_project\scripts\hydraulics\run_phase_l1_r3_validation.py:93(inputs)
   320000    0.239    0.000    0.395    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\actuator.py:19(chamber_volumes)
  4763916    0.381    0.000    0.381    0.000 {built-in method builtins.abs}
   960000    0.284    0.000    0.284    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:55(_pump_speed)
   960000    0.263    0.000    0.263    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\pump.py:6(pump_flow)
    80001    0.191    0.000    0.191    0.000 {built-in method builtins.round}
   160000    0.149    0.000    0.149    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:76(<listcomp>)
   560000    0.134    0.000    0.134    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:61(_valve_command)
   880000    0.128    0.000    0.128    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:174(<genexpr>)
   880000    0.125    0.000    0.125    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:172(<genexpr>)
   880000    0.118    0.000    0.118    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:143(<genexpr>)
   880000    0.116    0.000    0.116    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:164(<genexpr>)
   880000    0.113    0.000    0.113    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:173(<genexpr>)
    80000    0.088    0.000    0.113    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:50(_inputs)
   880000    0.107    0.000    0.107    0.000 E:\15_project\src\steering_sim\hydraulics_lumped\model.py:144(<genexpr>)
```
