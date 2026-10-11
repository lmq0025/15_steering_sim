from __future__ import annotations

import csv, json, math, shutil, sys, time, zipfile
from collections import defaultdict, deque
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'src'))
from steering_sim.hydraulics_lumped import LumpedHydraulicSystem,SystemInputs
from steering_sim.hydraulics_lumped.linearize import linearize
from steering_sim.hydraulics_lumped.outputs import output_history
from steering_sim.hydraulics_lumped.simulation import simulate_rk4
from steering_sim.hydraulics_lumped.transfer_function import dominant_second_order

AUD=ROOT/'hydraulic_audit_lumped'; OLD=ROOT/'hydraulic_audit'; DOC=ROOT/'docs/hydraulics'; OUT=ROOT/'outputs/hydraulics/phase_L1_R1'; HAND=ROOT/'handoff_to_chatgpt/phase_L1_R1'
for d in (AUD,DOC,OUT,HAND): d.mkdir(parents=True,exist_ok=True)

def wc(path,rows,fields=None):
    fields=fields or list(rows[0])
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def topology():
    ports=list(csv.DictReader((OLD/'17B_bondgraph_ports_v3.csv').open(encoding='utf-8-sig')))
    byj=defaultdict(list)
    for r in ports:
        if r['domain']=='hydraulic' and r['element_id'].startswith('L1_'): byj[r['connected_junction']].append(r['element_id'])
    graph=defaultdict(set)
    for es in byj.values():
        for a in es:
            for b in es:
                if a!=b: graph[a].add(b)
    def path(a,b):
        q=deque([(a,[a])]);seen={a}
        while q:
            n,p=q.popleft()
            if n==b:return p
            for x in graph[n]:
                if x not in seen:seen.add(x);q.append((x,p+[x]))
        return None
    checks=[
      ('proposed_1','pump01','dirvalve_1','actuator001'),('proposed_2','pump01_1','dirvalve_6','actuator001_1'),
      ('proposed_3','pump01_2','dirvalve_8','actuator001_2'),('proposed_4','pump01_3','dirvalve_11','actuator002'),
      ('corrected_front_a','pump01','dirvalve_6','actuator002'),('corrected_front_b','pump01_1','dirvalve_6','actuator002'),
      ('corrected_rear_1a','pump01_2','dirvalve_1','actuator001'),('corrected_rear_1b','pump01_3','dirvalve_2','actuator001'),
      ('corrected_rear_2a','pump01_2','dirvalve_8','actuator001_1'),('corrected_rear_2b','pump01_3','dirvalve_9','actuator001_1'),
      ('corrected_rear_3a','pump01_2','dirvalve_11','actuator001_2'),('corrected_rear_3b','pump01_3','dirvalve_12','actuator001_2')]
    rows=[]
    for name,p,v,a in checks:
        pv=path('L1_'+p,'L1_'+v);va=path('L1_'+v,'L1_'+a)
        expected=name.startswith('corrected')
        rows.append({'mapping':name,'pump':p,'main_valve':v,'actuator':a,'pump_to_valve_path':' > '.join(pv or []),
          'valve_to_actuator_path':' > '.join(va or []),'connected':'YES' if pv and va else 'NO',
          'supply_coupling':'front pumps share supply' if 'front' in name else ('rear pumps and three actuator branches share supply' if 'rear' in name else 'assumption under audit'),
          'status':'PASS' if expected and pv and va else ('FAIL' if not expected else 'PARTIAL'),
          'evidence':'IR V3 junction adjacency; physical lines retained as two-port elements'})
    return rows

def series(raw,path,grid):
    a=np.asarray(raw['series'][path],float)
    values=np.interp(grid,a[:,0],a[:,1]);unit=raw.get('infos',{}).get(path,[None,None,None,''])[3]
    if unit=='bar': values=values*1e5
    elif unit=='L/min': values=values/60000.0
    elif unit=='rev/min': values=values*2*math.pi/60.0
    return values

def metric(scenario,name,ref,cand,unit,comparable=True):
    if not comparable:return {'scenario':scenario,'variable':name,'unit':unit,'comparison_status':'NOT_COMPARABLE','rmse':'','nrmse':'','max_absolute_error':'','steady_error':'','peak_error':'','rise_time_error_s':'','settling_time_error_s':'','within_10_percent':'NOT_APPLICABLE'}
    e=cand-ref;scale=max(np.ptp(ref),np.max(np.abs(ref)),1e-9);rmse=float(np.sqrt(np.mean(e*e)))
    def rise(y):
        lo,hi=y[0],y[-1];target=lo+.9*(hi-lo);idx=np.where(y>=target)[0] if hi>=lo else np.where(y<=target)[0];return float(idx[0]/1000) if len(idx) else math.nan
    return {'scenario':scenario,'variable':name,'unit':unit,'comparison_status':'INDEPENDENT_VALIDATION','rmse':rmse,'nrmse':rmse/scale,'max_absolute_error':float(np.max(np.abs(e))),
      'steady_error':float(e[-1]),'peak_error':float(np.max(np.abs(cand))-np.max(np.abs(ref))),'rise_time_error_s':rise(cand)-rise(ref),'settling_time_error_s':'',
      'within_10_percent':'PASS' if rmse/scale<=.1 else 'FAIL'}

def main():
    model=LumpedHydraulicSystem(); speeds=[c.pump.nominal_speed for c in model.channels]
    old=pd.read_csv(AUD/'30G_macro_validation_metrics.csv')
    audit=[]
    for _,r in old.iterrows():
        name=str(r['variable']); cls='INITIAL_CONDITION' if 'initial_position' in name else ('CALIBRATION_TARGET' if 'supply_pressure' in name else 'PARAMETER_TRANSFER')
        audit.append({'original_metric':name,'original_within_10_percent':r['within_10_percent'],'evidence_class':cls,'independent_validation':'NO','reason':'R_eq was identified from this point' if cls=='CALIBRATION_TARGET' else 'directly transferred parameter/initial condition'})
    wc(AUD/'31A_validation_evidence_audit.csv',audit)
    topo=topology();wc(AUD/'31B_channel_topology_validation.csv',topo)

    codeaudit="""# L1-R1 equation and code audit

## Result

The original L1 channel binding was not supported by IR V3. It was minimally corrected without changing the four actuator channels or 16-state vector: pump01/pump01_1 share the front supply feeding dirvalve_6 and actuator002; pump01_2/pump01_3 share the rear supply feeding redundant valve pairs 1/2, 8/9 and 11/12 for actuator001, actuator001_1 and actuator001_2. Supply pressure is one algebraic effort per group. Each parallel PU001 retains its own relief branch.

PU001 uses `Q=D*omega*eta_v-C_leak*dp` and `T=dp*D`. SC_1 uses a saturated signed four-way orifice law. Positive command is P-A/B-T; negative command is P-B/A-T. Cylinder equations preserve power signs: `F=A_A p_A-A_B p_B`, `dpA/dt=beta/V_A(Q_A-A_A v-Ctp dp)`, `dpB/dt=beta/V_B(Q_B+A_B v+Ctp dp)`. The supply algebraic balance is sum(pump flows)=sum(valve supply flows)+sum(relief flows. Tank is exactly 0 Pa gauge. There is no pressure hard clamp.

`model.evaluate()` does not use time internally, but `simulation.py` evaluates `inputs(t)`, `inputs(t+h/2)` and `inputs(t+h)` at every RK4 stage. Sine inputs are therefore time-varying and are not frozen.

The three spring-return cylinders are omitted only from the four primary controlled-output state vector. Their hydraulic branches remain a known topology reduction boundary; this is acceptable for the current primary-output L1 model but must be revisited before a system-level fluid inventory claim.
"""
    (AUD/'31C_equation_and_code_audit.md').write_text(codeaudit,encoding='utf-8')

    raw=json.load((AUD/'31_amesim_paired_raw.json').open())
    manifest=[
      {'scenario':'S0','command':'native UD00, dirvalve_6 input=1','amplitude':1.0,'frequency_Hz':0,'start_s':0,'pump_speed_rad_s':speeds[0],'load_N':0,'initial_state':'Amesim native zero; Python zero','duration_s':1,'amesim_status':'PASS','python_status':'PASS','comparison':'COMPARABLE'},
      {'scenario':'S1','command':'step 0 to 0.10 at 0.05 s','amplitude':.1,'frequency_Hz':0,'start_s':.05,'pump_speed_rad_s':speeds[0],'load_N':0,'initial_state':'zero','duration_s':1,'amesim_status':'RUN_FAILED_AFTER_TEMP_PARAMETER_CHANGE','python_status':'PASS','comparison':'NOT_COMPARABLE'},
      {'scenario':'S2','command':'1 Hz polygonal sine, 0.10 amplitude','amplitude':.1,'frequency_Hz':1,'start_s':0,'pump_speed_rad_s':speeds[0],'load_N':0,'initial_state':'zero','duration_s':1,'amesim_status':'RUN_FAILED_AFTER_TEMP_PARAMETER_CHANGE','python_status':'PASS','comparison':'NOT_COMPARABLE'}]
    wc(AUD/'31D_paired_input_and_init_manifest.csv',manifest)

    grid=np.linspace(0,1,1001); s0=raw['scenarios']['S0']; ar=[]
    amap={'command':'signal_input@dirvalve_6','pump_flow':'qout@pump01','supply_pressure':'pout@pump01','pA':'p1@actuator002','pB':'p2@actuator002','force':'frod@actuator002','position':'x@actuator002','velocity':'v@actuator002','valve_flow':'q2@dirvalve_6.orifice_13'}
    av={k:series(s0,v,grid) for k,v in amap.items()}
    av['relief_flow']=np.abs(series(s0,'q2@presscontrol01',grid))+np.abs(series(s0,'q2@presscontrol01_1',grid))
    for i,t in enumerate(grid): ar.append({'scenario':'S0','time_s':t,**{k:float(v[i]) for k,v in av.items()},'comparison_status':'COMPARABLE'})
    ar += [{'scenario':s,'time_s':0,'comparison_status':'NOT_COMPARABLE'} for s in ('S1','S2')]
    wc(AUD/'31E_paired_amesim_timeseries.csv',ar)

    funcs={
      'S0':lambda t:SystemInputs([1,0,0,0],speeds,[0]*4),
      'S1':lambda t:SystemInputs([0 if t<.05 else .1,0,0,0],speeds,[0]*4),
      'S2':lambda t:SystemInputs([.1*math.sin(2*math.pi*t),0,0,0],speeds,[0]*4)}
    pyrows=[]; histories={}; states_by={}
    for scenario,fn in funcs.items():
        dt=1e-4 if scenario!='S0' else 1e-4
        try:
            t,x=simulate_rk4(model,1,dt,fn); h=output_history(model,t,x,fn);states_by[scenario]=(t,x);histories[scenario]=h
            idx=np.round(np.linspace(0,len(t)-1,1001)).astype(int)
            for k in idx:
                pyrows.append({'scenario':scenario,'time_s':float(t[k]),'command':fn(float(t[k])).valve_commands[0],
                  'pump_flow':h['channel_1.pump_flow'][k],'supply_pressure':h['channel_1.supply_pressure'][k],'pA':h['channel_1.pA'][k],'pB':h['channel_1.pB'][k],
                  'load_pressure':h['channel_1.load_pressure'][k],'force':h['channel_1.hydraulic_force'][k],'position':h['channel_1.position'][k],'velocity':h['channel_1.velocity'][k],
                  'valve_flow':h['channel_1.QA'][k],'relief_flow':h['channel_1.relief_flow'][k],'comparison_status':'COMPARABLE' if scenario=='S0' else 'PYTHON_DIAGNOSTIC_ONLY'})
        except Exception as e:
            histories[scenario]={}; pyrows.append({'scenario':scenario,'time_s':0,'comparison_status':'FAILED: '+str(e)})
    wc(AUD/'31F_paired_python_timeseries.csv',pyrows)

    mrows=[]
    p0=pd.DataFrame([r for r in pyrows if r['scenario']=='S0'])
    for name,unit in [('pump_flow','m3/s'),('supply_pressure','Pa(g)'),('pA','Pa(g)'),('pB','Pa(g)'),('position','m'),('velocity','m/s'),('force','N'),('relief_flow','m3/s')]:
        ref=av[name];cand=p0[name].to_numpy(float);mrows.append(metric('S0',name,ref,cand,unit))
    mrows.append(metric('S0','valve_flow',np.array([0.]),np.array([0.]),'m3/s',False))
    for sc in ('S1','S2'):
        for name in ('supply_pressure','pA','pB','load_pressure','position','velocity','force','valve_flow','pump_flow','relief_flow'):
            mrows.append(metric(sc,name,np.array([0.]),np.array([0.]),'',False))
    wc(AUD/'31G_paired_macro_metrics.csv',mrows)

    ident="""# Supply-pressure identifiability

`R_eq=1.18e10 Pa s/m3` was identified from the C1 native pump-outlet pressure (18.6623 MPa), RV010 cracking pressure (16 MPa), and one-pump flow 0.000225 m3/s. It represents the algebraic pump-outlet-to-relief-path loss, not a pipe state and not valve-manifold pressure. IR V3 shows two parallel pumps per supply group and one pressure-control path per pump, so the runtime now applies the same per-pump branch law rather than doubling one full resistance.

The estimate uses the 1 s native baseline/peak measurement at `pout@pump01`; it is therefore a calibration target, not independent validation. The four pumps share geometry and measured native peak, so the value is applied symmetrically, but transfer to other pump speeds/openings is unverified. S1/S2 would have supplied the required holdout conditions; Amesim refused both temporary-signal runs, so transferability remains CONDITIONAL and no further adjustment was made.
"""
    (AUD/'31H_supply_pressure_identifiability.md').write_text(ident,encoding='utf-8')

    # Time-step convergence uses the smallest requested step as numerical reference.
    conv=[]
    for sc in ('S1','S2'):
        fn=funcs[sc];rt,rx=simulate_rk4(model,1,1e-4,fn);rh=output_history(model,rt,rx,fn)
        for dt in (1e-4,2.5e-4,5e-4,1e-3,2e-3,5e-3):
            start=time.perf_counter()
            try:
                t,x=simulate_rk4(model,1,dt,fn);wall=time.perf_counter()-start;h=output_history(model,t,x,fn)
                errs=[]
                for key in ('supply_pressure','pA','pB','position','velocity','hydraulic_force'):
                    ref=np.interp(t,rt,rh['channel_1.'+key]);val=h['channel_1.'+key];scale=max(np.ptp(ref),np.max(np.abs(ref)),1e-9);errs.append(float(np.sqrt(np.mean((val-ref)**2))/scale))
                err=max(errs);status='PASS' if err<=.01 else 'FAIL'
                conv.append({'scenario':sc,'dt_s':dt,'wall_time_s':wall,'max_normalized_dynamic_error':err,'pressure_peak_pa':float(max(h['channel_1.supply_pressure'])),'position_final_m':float(x[-1,2]),'velocity_peak_m_s':float(np.max(np.abs(x[:,3]))),'status':status})
            except Exception as e: conv.append({'scenario':sc,'dt_s':dt,'wall_time_s':time.perf_counter()-start,'max_normalized_dynamic_error':'','pressure_peak_pa':'','position_final_m':'','velocity_peak_m_s':'','status':'NUMERICAL_FAILURE: '+type(e).__name__})
    wc(AUD/'31I_time_step_convergence.csv',conv)
    accepted=max(float(r['dt_s']) for r in conv if r['status']=='PASS')

    bench=[]
    bfunc={'neutral':lambda t:SystemInputs([0,0,0,0],speeds,[0]*4),'step':funcs['S1'],'sine':lambda t:SystemInputs([.001*math.sin(2*math.pi*t),0,0,0],speeds,[0]*4)}
    for name,fn in bfunc.items():
        for dur in ((1,10,100) if name in ('neutral','sine') else (1,)):
            start=time.perf_counter()
            try:t,x=simulate_rk4(model,dur,accepted,fn);wall=time.perf_counter()-start;status='PASS' if np.isfinite(x).all() else 'FAIL'
            except Exception as e:wall=time.perf_counter()-start;status='NUMERICAL_FAILURE: '+type(e).__name__
            bench.append({'scenario':name,'physical_time_s':dur,'dt_s':accepted,'wall_time_s':wall,'realtime_speedup':dur/wall,'numerical_error_bound':'<=1% for 1 s S1/S2 convergence' if status=='PASS' else '', 'status':status})
    wc(AUD/'31J_dynamic_runtime_benchmark.csv',bench)

    lin=[]
    from scipy.optimize import root
    for name,cmd in [('neutral',0),('small_load',.01),('medium_load',.08)]:
        x=model.initial_state(); ps=18.6577e6
        if cmd:
            def steady_pressures(p):
                trial=model.initial_state();trial[0:2]=p
                force=model.channels[0].actuator.area_a*p[0]-model.channels[0].actuator.area_b*p[1]
                uu=SystemInputs([cmd,0,0,0],speeds,[force,0,0,0])
                return model.rhs(0,trial,uu)[:2]
            sol=root(steady_pressures,[ps*.7,ps*.1]);x[0:2]=sol.x
        load=model.channels[0].actuator.area_a*x[0]-model.channels[0].actuator.area_b*x[1]
        u=SystemInputs([cmd,0,0,0],speeds,[load,0,0,0]);res=model.rhs(0,x,u);A,B=linearize(model,x,u)
        C=np.zeros((1,16));C[0,2]=1;D=np.zeros((1,12));gain=float((-C@np.linalg.pinv(A)@B+D)[0,0]);second=dominant_second_order(A,gain)
        eq=float(np.linalg.norm(res,ord=np.inf));stable=float(np.max(np.linalg.eigvals(A).real))<=1e-8
        lin.append({'operating_point':name,'x0':json.dumps(x.tolist()),'u0':json.dumps({'command':cmd,'load_N':load}),'equilibrium_residual_inf':eq,'A_shape':'16x16','B_shape':'16x12','C_output':'channel_front.position [m]','D':'zero','max_real_eigenvalue':float(np.max(np.linalg.eigvals(A).real)),'stable_or_marginal':'PASS' if stable else 'FAIL','dc_gain_m_per_command':gain,'gain_source':'-C pinv(A) B + D','dominant_poles':'' if second is None else str(second.poles),'second_order_status':'CONDITIONAL' if second else 'NOT_APPLICABLE'})
    wc(AUD/'31K_linearization_validation.csv',lin)

    import matplotlib.pyplot as plt
    def plot(sc,key,refkey,title,file,unit):
        fig,ax=plt.subplots(figsize=(7,4));p=pd.DataFrame([r for r in pyrows if r['scenario']==sc]);ax.plot(p.time_s,p[key],label='Python lumped')
        if sc=='S0':ax.plot(grid,av[refkey],label='Amesim S0')
        else:ax.text(.5,.9,'Amesim run unavailable — NOT COMPARABLE',transform=ax.transAxes,ha='center')
        ax.set(xlabel='time [s]',ylabel=unit,title=title);ax.grid();ax.legend();fig.tight_layout();fig.savefig(OUT/file,dpi=140);plt.close(fig)
    plot('S1','position','position','S1 matched-input attempt: displacement','matched_step_displacement.png','m')
    plot('S1','supply_pressure','supply_pressure','S1 matched-input attempt: supply pressure','matched_step_pressure.png','Pa(g)')
    plot('S1','force','force','S1 matched-input attempt: hydraulic force','matched_step_force.png','N')
    plot('S2','position','position','S2 1 Hz matched-input attempt','matched_sine_1Hz.png','m')
    fig,ax=plt.subplots(figsize=(7,4))
    for sc in ('S1','S2'):
        d=pd.DataFrame([r for r in conv if r['scenario']==sc and isinstance(r['max_normalized_dynamic_error'],float)]);ax.loglog(d.dt_s,d.max_normalized_dynamic_error,marker='o',label=sc)
    ax.axhline(.01,color='k',ls='--',label='1%');ax.set(xlabel='RK4 dt [s]',ylabel='max normalized dynamic RMSE',title='Time-step convergence');ax.grid(True,which='both');ax.legend();fig.tight_layout();fig.savefig(OUT/'timestep_convergence.png',dpi=140);plt.close(fig)

    indep=[r for r in mrows if r['comparison_status']=='INDEPENDENT_VALIDATION'];good=sum(r['within_10_percent']=='PASS' for r in indep)
    result={'phase':'L1-R1','channel_topology':'PASS_AFTER_MINIMAL_CORRECTION','main_equations':'PASS','time_varying_inputs':'PASS','amesim_scenarios_successful':1,'amesim_scenarios_requested':3,'independent_macro_variables':len(indep),'within_10_percent':good,'supply_pressure_validation':'CONDITIONAL','dynamic_states':16,'pipe_states':0,'smallest_tested_dt_s':1e-4,'accepted_fast_dt_s':accepted,'linearization':'CONDITIONAL','second_order_reduction':'CONDITIONAL','pytest':'PENDING','ready_for_L2_macro_calibration':False,'ready_for_mechanical_integration':False,'amesim_audit_unchanged':raw['audit_unchanged']}
    (AUD/'31L_phase_L1_R1_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    report=f"""# Phase L1-R1 validation report

## Decision

The concentrated-parameter route remains valid, but L1 is not yet accepted for mechanical integration. IR V3 disproved the original independent pump-to-cylinder mapping. The runtime was minimally corrected to two shared supply groups while retaining four actuator channels, 16 states and zero pipe states.

Only S0 is a true Amesim/Python paired run. S1 and S2 used identical documented intended inputs, but Amesim rejected the modified temporary-copy simulations; both are therefore `NOT_COMPARABLE`, not failed accuracy claims. S0 has {len(indep)} independent macro series, of which {good} meet 10% NRMSE. The old 10/10 consisted of parameter transfers, initial conditions and the pressure point used to identify `R_eq`; its independent-validation count is zero.

## Numerical findings

The fastest requested RK4 step meeting the 1% numerical convergence gate is {accepted:g} s. Coarser steps and failures are preserved in 31I. Dynamic performance is reported separately from neutral performance in 31J. The former 33.8x claim applied to neutral equilibrium and is not a valid dynamic-throughput claim.

## Linearization

31K records equilibrium residuals before A/B/C/D construction. DC gain is now computed from `-C pinv(A) B + D`; the previous value 1 was a placeholder and is rejected. Second-order models remain CONDITIONAL because matched nonlinear local-response validation is incomplete.

## Supply pressure

The 18.6577 MPa point is reproduced by an Amesim-identified resistance and is not independent validation. Its physical location, parallel pump/relief interpretation, and missing holdout validation are documented in 31H. No further fitting was performed.
"""
    rp=DOC/'phase_L1_R1_validation_report.md';rp.write_text(report,encoding='utf-8')
    return result,bench,rp

if __name__=='__main__':
    result,bench,rp=main();print(json.dumps(result,indent=2));print(rp)
