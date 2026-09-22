"""Preserve E134 features and add current boss-relic x card-property terms."""
import torch

import heart_explicit_readout as N

M,R,A=N.M,N.R,N.A
VERSION='boss_card_interactions_v1'


def boss_ids(support):
    return [i for i in support if i<A.RELIC_CAP]


def artifact(base,rs,cs,provenance):
    return {**N.artifact(base,rs,cs,provenance),'model_type':BossConditionedPolicy.model_type,
            'boss_conditioning_version':VERSION}


class BossConditionedPolicy(N.ExplicitReadoutPolicy):
    model_type='boss_conditioned_joint_readout'

    def __init__(self,checkpoint):
        if checkpoint.get('boss_conditioning_version')!=VERSION:
            raise ValueError('boss-conditioning contract differs')
        # The inherited constructor establishes the frozen parent and original
        # feature schema. New heads are loaded after their width is established.
        super().__init__({k:v for k,v in checkpoint.items() if k not in ('relic_state','card_state')})
        self.boss_identities=tuple(boss_ids(self.relic_support))
        width=192+12*len(self.boss_identities)
        self.relic=M.Readout(width,len(self.relic_support))
        self.card=M.Readout(width,len(self.card_support))
        for head,enabled in ((self.relic,self.change_relic),(self.card,self.change_card)):
            for p in head.parameters():p.requires_grad_(enabled)
        if 'relic_state' in checkpoint:
            self.relic.load_state_dict(checkpoint['relic_state'],strict=True)
            self.card.load_state_dict(checkpoint['card_state'],strict=True)

    def embed(self,observations,descriptors):
        original=super().embed(observations,descriptors)
        _,counts=N.contexts(observations,self.mechanics)
        cards=descriptors[:,A.OFF_CARD:A.OFF_CARD+A.W_CARD]
        selected=cards@self.mechanics
        properties=torch.cat((cards.sum(-1,keepdim=True),selected[:,:9],
            (descriptors[:,A.OFF_CARD_UPGRADE:A.OFF_CARD_UPGRADE+1]*A.SPECIAL_SCALE).clamp(0.,1.),
            (cards*counts).sum(-1,keepdim=True)/5.),-1)
        owned=observations[:,[N.RELIC_OFFSET+i for i in self.boss_identities]]
        extra=(properties[:,:,None]*owned[:,None,:]).flatten(1)
        is_relic=descriptors[:,A.AK_BOSS_RELIC]+descriptors[:,A.AK_BOSS_SKIP]
        extra=torch.where(is_relic[:,None].bool(),torch.zeros_like(extra),extra)
        return torch.cat((original,extra),-1)


def extend_checkpoint(old):
    """A zero-added-weight control, not a fitted or adopted new policy."""
    checkpoint={**old,'model_type':BossConditionedPolicy.model_type,'boss_conditioning_version':VERSION}
    extra=12*len(boss_ids(old['relic_support']))
    for stage in ('relic','card'):
        head=old[stage+'_state']
        checkpoint[stage+'_state']={
            'weight':torch.cat((head['weight'].clone(),torch.zeros(extra))),
            'scale':torch.cat((head['scale'].clone(),torch.ones(extra))),
            'static_scores':head['static_scores'].clone()}
    return checkpoint


def native_features(gc,stage,identity,extra,relic_support):
    original=N.native_features(gc,stage,identity,extra,relic_support)
    ids=boss_ids(relic_support)
    if stage=='relic' or identity>=A.CARD_CAP:return original+[0.]*(12*len(ids))
    _,counts=N.native_context(gc);card=R.sts.Card(R.sts.CardId(identity))
    properties=[1.,*(float(card.type==k) for k in (R.sts.CardType.ATTACK,R.sts.CardType.SKILL,R.sts.CardType.POWER)),
        *(float(card.id.name in words.split()) for words in N.TAGS.values()),
        float(extra[0]>0),counts.get(identity,0)/5.]
    owned={int(r.id) for r in gc.relics}
    return original+[value*float(i in owned) for value in properties for i in ids]
