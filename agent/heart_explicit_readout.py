"""Public deck/option interactions for an existing-data representation test.

The 192-wide linear heads, fit-only scaling, option biases, parent margin and
two decision scopes are inherited. Only the fixed representation changes.
Tags are overlapping mechanical categories, not estimated card values.
"""
import hashlib
import json
import torch

import heart_relic_card_readout as M

J, R, A = M.J, M.R, M.A
VERSION = 'explicit_interactions_v1'
TAGS = {
    'draw': 'BATTLE_TRANCE POMMEL_STRIKE SHRUG_IT_OFF OFFERING BURNING_PACT DARK_EMBRACE '
            'DROPKICK EVOLVE WARCRY BRUTALITY MASTER_OF_STRATEGY FINESSE FLASH_OF_STEEL '
            'IMPATIENCE DEEP_BREATH THINKING_AHEAD',
    'exhaust': 'TRUE_GRIT BURNING_PACT FIEND_FIRE SECOND_WIND CORRUPTION EXHUME HAVOC '
               'OFFERING IMPERVIOUS SHOCKWAVE FEED REAPER LIMIT_BREAK SENTINEL '
               'FEEL_NO_PAIN DARK_EMBRACE',
    'block': 'DEFEND_RED SHRUG_IT_OFF TRUE_GRIT IRON_WAVE POWER_THROUGH SECOND_WIND '
             'FLAME_BARRIER IMPERVIOUS RAGE FEEL_NO_PAIN METALLICIZE ENTRENCH '
             'BARRICADE GHOSTLY_ARMOR GOOD_INSTINCTS PANIC_BUTTON FINESSE',
    'energy': 'OFFERING SEEING_RED SENTINEL BLOODLETTING CORRUPTION BERSERK '
              'HAVOC MADNESS',
    'strength': 'INFLAME SPOT_WEAKNESS DEMON_FORM LIMIT_BREAK FLEX HEAVY_BLADE '
                'SWORD_BOOMERANG PUMMEL REAPER',
    'hp_loss': 'OFFERING BLOODLETTING HEMOKINESIS COMBUST BRUTALITY RUPTURE',
}
CONTEXT_NAMES = (
    'hp_fraction', 'deck_size_div30', 'attack_fraction', 'skill_fraction',
    'power_fraction', 'upgraded_fraction', 'draw_fraction', 'exhaust_fraction',
    'block_fraction', 'energy_fraction', 'strength_fraction', 'curse_status_fraction',
    'corruption_owned', 'dark_embrace_owned', 'feel_no_pain_owned', 'dead_branch_owned',
)
CARD_NAMES = ('card', 'attack', 'skill', 'power', 'draw', 'exhaust', 'block',
              'energy', 'strength', 'hp_loss', 'upgraded', 'same_card_owned_div5')
DECK_OFFSET = J.M.DECK_OFFSET
RELIC_OFFSET = DECK_OFFSET + 6 * A.CARD_CAP + 32


def metadata():
    ids = {name: {int(getattr(R.sts.CardId, word)) for word in words.split()}
           for name, words in TAGS.items()}
    types = (R.sts.CardType.ATTACK, R.sts.CardType.SKILL, R.sts.CardType.POWER)
    rows = []
    for identity in range(A.CARD_CAP):
        card = R.sts.Card(R.sts.CardId(identity))
        rows.append([float(card.type == kind) for kind in types] +
                    [float(identity in ids[name]) for name in TAGS] +
                    [float(card.type in (R.sts.CardType.CURSE, R.sts.CardType.STATUS))])
    return torch.tensor(rows)


def schema_hash():
    return hashlib.sha256(json.dumps({'version': VERSION, 'tags': TAGS,
        'context': CONTEXT_NAMES, 'card': CARD_NAMES}, sort_keys=True).encode()).hexdigest()


def contexts(observations, table):
    if observations.shape[-1] != A.OBS_DIM:
        raise ValueError('public observation layout changed')
    faces = observations[:, DECK_OFFSET:DECK_OFFSET + 2*A.CARD_CAP].reshape(-1, A.CARD_CAP, 2)*20.
    counts = faces.sum(-1)
    size = counts.sum(-1).clamp_min(1.)
    totals = counts @ table
    hp = observations[:, 0]*A._maxes[0]
    maximum = (observations[:, 1]*A._maxes[1]).clamp_min(1.)
    owns = [counts[:, int(getattr(R.sts.CardId, name))].clamp(0., 1.)
            for name in ('CORRUPTION', 'DARK_EMBRACE', 'FEEL_NO_PAIN')]
    branch = observations[:, RELIC_OFFSET + int(R.sts.RelicId.DEAD_BRANCH)]
    values = [hp/maximum, size/30., totals[:, 0]/size, totals[:, 1]/size,
              totals[:, 2]/size, faces[:, :, 1].sum(-1)/size,
              totals[:, 3]/size, totals[:, 4]/size, totals[:, 5]/size,
              totals[:, 6]/size, totals[:, 7]/size, totals[:, 9]/size,
              *owns, branch]
    return torch.stack(values, -1), counts


class ExplicitReadoutPolicy(M.ReadoutPolicy):
    model_type = 'explicit_joint_readout'

    def __init__(self, checkpoint):
        if checkpoint.get('feature_version') != VERSION or checkpoint.get('feature_schema_sha256') != schema_hash():
            raise ValueError('explicit feature contract differs')
        super().__init__(checkpoint)
        if self.relic.weight.numel() != 192 or len(self.relic_support) > 24:
            raise ValueError('representation requires 192-wide heads and at most 24 relic IDs')
        self.register_buffer('mechanics', metadata())

    def embed(self, observations, descriptors):
        if descriptors.shape[-1] != A.DESC_DIM:
            raise ValueError('candidate layout changed')
        context, counts = contexts(observations, self.mechanics)
        cards = descriptors[:, A.OFF_CARD:A.OFF_CARD+A.W_CARD]
        selected = cards @ self.mechanics
        properties = torch.cat((cards.sum(-1, keepdim=True), selected[:, :9],
            (descriptors[:, A.OFF_CARD_UPGRADE:A.OFF_CARD_UPGRADE+1]*A.SPECIAL_SCALE).clamp(0., 1.),
            (cards*counts).sum(-1, keepdim=True)/5.), -1)
        card_values = (properties[:, :, None]*context[:, None, :]).flatten(1)
        slots = torch.zeros((len(descriptors), 24), dtype=descriptors.dtype)
        for slot, identity in enumerate(self.relic_support):
            slots[:, slot] = (descriptors[:, A.AK_BOSS_SKIP] if identity == A.RELIC_CAP
                             else descriptors[:, A.OFF_RELIC+identity])
        relic_values = (slots[:, :, None]*context[:, None, :8]).flatten(1)
        is_relic = descriptors[:, A.AK_BOSS_RELIC] + descriptors[:, A.AK_BOSS_SKIP]
        return torch.where(is_relic[:, None].bool(), relic_values, card_values)


def native_context(gc):
    """Independent decoder: native Card/Relic objects, no observation offsets."""
    deck = list(gc.deck)
    counts = {identity: sum(int(c.id) == identity for c in deck)
              for identity in {int(c.id) for c in deck}}
    size = max(1, len(deck))
    names = [c.id.name for c in deck]
    tagged = {name: sum(n in words.split() for n in names) for name, words in TAGS.items()}
    kinds = [sum(c.type == k for c in deck) for k in
             (R.sts.CardType.ATTACK, R.sts.CardType.SKILL, R.sts.CardType.POWER)]
    relics = {int(item.id) for item in gc.relics}
    values = [gc.cur_hp/max(1, gc.max_hp), size/30., *(v/size for v in kinds),
              sum(c.upgraded for c in deck)/size,
              *(tagged[name]/size for name in ('draw', 'exhaust', 'block', 'energy', 'strength')),
              sum(c.type in (R.sts.CardType.CURSE, R.sts.CardType.STATUS) for c in deck)/size,
              *(float(name in names) for name in ('CORRUPTION', 'DARK_EMBRACE', 'FEEL_NO_PAIN')),
              float(int(R.sts.RelicId.DEAD_BRANCH) in relics)]
    return values, counts


def native_features(gc, stage, identity, extra, relic_support):
    context, counts = native_context(gc)
    if stage == 'relic':
        result = [0.] * 192
        if identity in relic_support:
            offset = relic_support.index(identity)*8
            result[offset:offset+8] = context[:8]
        return result
    if identity >= A.CARD_CAP:
        return [0.] * 192
    card = R.sts.Card(R.sts.CardId(identity))
    properties = [1., *(float(card.type == k) for k in
        (R.sts.CardType.ATTACK, R.sts.CardType.SKILL, R.sts.CardType.POWER)),
        *(float(card.id.name in words.split()) for words in TAGS.values()),
        float(extra[0] > 0), counts.get(identity, 0)/5.]
    return [p*c for p in properties for c in context]


def artifact(base, relics, cards, provenance):
    return {'model_type': ExplicitReadoutPolicy.model_type, 'base_checkpoint': base,
        'relic_support': relics, 'card_support': cards, 'change_relic': True, 'change_card': True,
        'feature_version': VERSION, 'feature_schema_sha256': schema_hash(), 'provenance': provenance}
