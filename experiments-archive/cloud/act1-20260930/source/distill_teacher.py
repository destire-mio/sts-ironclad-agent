"""Read-only AST adapter for the existing teacher's exact outside decision order.

This adapter is for label audits/shadow diagnostics only; student.choose never calls it.
"""
import ast
import inspect

from distill_model import TEACHER_ARM


def teacher_function(module):
    tree = ast.parse(inspect.getsource(module.play))
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.While))
    start = next(i for i, n in enumerate(loop.body) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'chosen' for t in n.targets))
    end = next(i for i, n in enumerate(loop.body) if isinstance(n, ast.If)
               and any(isinstance(c, ast.Constant) and c.value == 'neowfork' for c in ast.walk(n.test)))
    prefix = ast.parse('''
def choose_teacher(x, parent, gc, actions, descriptors):
    A, sts = x.A, x.R.sts
    features = set(TEACHER_ARM.split('+'))
    overrides = teacher_calls = teacher_changed = guides = fixes = simulations_used = 0
    elite_thr = flame_thr = route_params = None
    branch = 0
    strength_cache, route_cache, guide2_cache = {}, {}, {}
''').body[0]
    prefix.body += loop.body[start:end] + [ast.Return(value=ast.Name(id='chosen', ctx=ast.Load()))]
    program = ast.fix_missing_locations(ast.Module(body=[prefix], type_ignores=[]))
    scope = dict(vars(module), TEACHER_ARM=TEACHER_ARM)
    exec(compile(program, '<distill-teacher-adapter>', 'exec'), scope)
    return scope['choose_teacher']
