"""Public boss context for the existing scorer, with exact zero-correction initialization."""
import heart_guided as G

H = G.H


class BossContextScorer(G.CardContextScorer):
    model_type = 'boss_context_residual'
    boss_offset = 65
    boss_count = 10

    def __init__(self, arch=(192,), prior_strength=3.0):
        super().__init__(arch, prior_strength)
        if H.A._maxes[self.boss_offset:self.boss_offset+self.boss_count] != [1.0]*self.boss_count:
            raise ValueError('boss observation layout changed')
        self.boss_context_projection = H.torch.nn.Linear(
            self.boss_count*(H.A.W_ACTION+1), arch[0], bias=False)
        H.torch.nn.init.zeros_(self.boss_context_projection.weight)

    def boss_features(self, values):
        bosses = values[:, self.boss_offset:self.boss_offset+self.boss_count]
        desc = values[:, H.A.OBS_DIM:]
        kinds = desc[:, H.A.OFF_ACTION:H.A.OFF_ACTION+H.A.W_ACTION]
        return H.torch.cat([bosses, (kinds[:, :, None]*bosses[:, None, :]).flatten(1)], dim=1)

    def residual_logits(self, values):
        # Keep the existing matrix multiplication unchanged. Adding zero columns
        # to its input could change floating-point accumulation and break the
        # original policy before any learning, so use a separate zero projection.
        hidden = self.net[0](self.features(values)) + self.boss_context_projection(self.boss_features(values))
        for layer in self.net[1:]:
            hidden = layer(hidden)
        return hidden.squeeze(-1)

    def initialize_from(self, checkpoint):
        if checkpoint['model_type'] != 'card_context_residual':
            raise ValueError('expected an existing CardContextScorer checkpoint')
        missing, unexpected = self.load_state_dict(checkpoint['state_dict'], strict=False)
        if missing != ['boss_context_projection.weight'] or unexpected:
            raise ValueError('unexpected base checkpoint layout')
        H.torch.nn.init.zeros_(self.boss_context_projection.weight)
        return self
