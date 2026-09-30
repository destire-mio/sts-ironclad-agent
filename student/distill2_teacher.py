"""Extract the complete outside decision block, including late rule overrides."""
import ast
import copy
import inspect

DEFAULT_ARMS = 'sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4'
STUDENT_ARMS = 'sims32+boss12+reuse+c4r+heart2+spear320+student'


def teacher_function(module, arms=DEFAULT_ARMS):
    features = set(arms.split('+'))
    if any(f.startswith(('explore', 'branch')) or f.endswith('fork') or
           f in {'traj', 'teacher', 'relicself'} for f in features):
        raise ValueError('oracle arms must be deterministic outside policy, without data/fork arms')
    play = ast.parse(inspect.getsource(module.play)).body[0]
    trial = next(n for n in play.body if isinstance(n, ast.Try))
    loop = next(n for n in trial.body if isinstance(n, ast.While))
    begin = next(i for i,n in enumerate(loop.body) if isinstance(n, ast.Assign) and
                 any(isinstance(t, ast.Name) and t.id == 'chosen' for t in n.targets))
    endings = [i for i,n in enumerate(loop.body) if isinstance(n, ast.Expr) and
               isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == 'actions[chosen].execute']
    if len(endings) != 1 or endings[0] <= begin:
        raise ValueError('unsupported teacher layout: expected one outside action execution')
    # Reuse the driver's own initializers, so new rule counters/caches are included.
    init = []
    for n in play.body[1:play.body.index(trial)]:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'gc' for t in n.targets):
            continue
        init.append(copy.deepcopy(n))
    fn = ast.parse('def choose_teacher(x, parent, gc, actions, descriptors, seed=0):\n    pass').body[0]
    fn.body = ast.parse('arm = ARMS\nseeds = [101,102,103,104]\nsimulations = 500\nrecord_dir = start = stop = None').body
    fn.body += init + copy.deepcopy(loop.body[begin:endings[0]])
    fn.body += ast.parse('return int(chosen)').body
    program = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    scope = dict(vars(module), ARMS=arms)
    exec(compile(program, '<distill2-complete-teacher>', 'exec'), scope)
    fn = scope['choose_teacher']
    fn.extracted_source = ast.unparse(program)
    return fn


def label_copy(P, x, parent, oracle, gc, actions, seed=0):
    before = x.R.fingerprint(gc)
    clone = P.C.F.copy_game(gc)
    ca = list(x.R.sts.get_legal_game_actions(clone))
    _, cd, _ = x.A.build_choices(clone)
    bits = [int(a.bits) for a in actions]
    if bits != [int(a.bits) for a in ca]:
        raise ValueError('copy changed legal actions')
    index = oracle(x, parent, clone, ca, cd, seed)
    if x.R.fingerprint(gc) != before:
        raise ValueError('oracle mutated student state')
    if not 0 <= index < len(bits):
        raise ValueError('oracle returned invalid index')
    return index
