"""Profile the existing responsiveness assertion without changing it."""
import runpy,cProfile,pstats
m=runpy.run_path('tests/desktop/test_d4_desktop.py');names=list(m)
for n in names:
    if n=='test_background_controller_keeps_event_loop_responsive':break
    if n.startswith('test_'):m[n]()
p=cProfile.Profile();p.enable()
try:m['test_background_controller_keeps_event_loop_responsive']()
except AssertionError:print('ASSERTION_FAILED')
p.disable();pstats.Stats(p).sort_stats('cumulative').print_stats(25)
