"""Reproduce a finite ordered intervention plan, consuming each change once."""
import heart_compositional_capability as M

E = M.E


class OnceChanges:
    def __init__(self, x, parent, changes):
        self.x, self.parent, self.changes = x, parent, list(changes)
        self.applied = []

    def choose(self, gc, observation, actions, descriptors):
        if len(self.applied) < len(self.changes):
            change = self.changes[len(self.applied)]
            if self.x.R.fingerprint(gc) == change['before']:
                selected = [int(a.bits) for a in actions].index(change['action'])
                self.applied.append(change)
                return selected
        return self.parent.choose(gc, observation, actions, descriptors)


def replan(x, parent, seed, record, output):
    policy = OnceChanges(x, parent, record['changes'])
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
    run = x.R.rollout(seed, x.config, gc=gc, net=policy, record=True, record_samples=False)
    x.R.clock_input(gc, x.config)
    run['terminal_fingerprint'] = x.R.fingerprint(gc)
    # Keep the actual failed run if any subsequent verification raises.
    run['interventions_applied'] = policy.applied
    M.put(output, run)
    M.check_route(x, run)
    E.require(policy.applied == record['changes'], 'intervention not reached or out of order')
    E.require(run['prefix'] == record['run']['prefix'] and
              run['terminal_fingerprint'] == record['run']['terminal_fingerprint'] and
              x.P.terminal_signature(run) == x.P.terminal_signature(record['run']),
              'once-only fresh planning differs')
    return run
