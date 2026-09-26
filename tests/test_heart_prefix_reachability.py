import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'agent'))
import heart_prefix_reachability as Q


class Tree:
    def __init__(self, edges, dead, turns=None):
        self.edges=edges; self.dead=set(dead); self.turns=turns or {}

    @staticmethod
    def canonical(bits): return bits
    @staticmethod
    def clone(state): return dict(state)
    def turn(self,state): return self.turns.get(state['id'],0)
    def hp(self,state): return 0 if state['id'] in self.dead else 10
    def terminal(self,state): return (state['id'] in self.dead,False)
    def actions(self,state): return list(self.edges.get(state['id'],{}))
    def valid(self,state,bits): return bits in self.edges.get(state['id'],{})
    def execute(self,state,action): state['id']=self.edges[state['id']][action]


class Certificates(unittest.TestCase):
    def run_tree(self, tree, **kw):
        return Q.search(tree,dict(id=0),3,kw.get('nodes',100),kw.get('depth',10),10)[0]

    def test_death_requires_every_legal_branch(self):
        tree=Tree({0:{10:1,20:2},1:{30:3,40:4}},[2,3,4])
        result=self.run_tree(tree)
        self.assertEqual(result['verdict'],'closed_dead')
        self.assertEqual(Q.verify(tree,dict(id=0),result)['leaves']['dead'],3)
        bad=copy.deepcopy(result);bad['nodes'][0]['menu'].pop()
        with self.assertRaisesRegex(ValueError,'omitted a legal action'):
            Q.verify(tree,dict(id=0),bad)

    def test_later_sibling_witness_prevents_false_impossibility(self):
        tree=Tree({0:{10:1,20:2}},[1],{2:3})
        result=self.run_tree(tree)
        self.assertEqual(result['verdict'],'surviving_prefix')
        self.assertEqual(result['actions'],[20])
        Q.verify(tree,dict(id=0),result)

    def test_node_limit_is_unknown(self):
        tree=Tree({0:{10:1,20:2}},[1,2])
        result=self.run_tree(tree,nodes=2)
        self.assertEqual(result['verdict'],'unknown_bound')
        Q.verify(tree,dict(id=0),result)
        result['verdict']='closed_dead'
        with self.assertRaisesRegex(ValueError,'incomplete tree'):
            Q.verify(tree,dict(id=0),result)

    def test_cycle_depth_limit_is_unknown(self):
        tree=Tree({0:{10:0}},[])
        result=self.run_tree(tree,depth=3)
        self.assertEqual(result['verdict'],'unknown_bound')
        Q.verify(tree,dict(id=0),result)

    def test_dead_at_target_turn_is_not_survival(self):
        tree=Tree({0:{10:1}},[1],{1:3})
        result=self.run_tree(tree)
        self.assertEqual(result['verdict'],'closed_dead')
        self.assertIsNone(Q.trace(tree,dict(id=0),[10],3))

    def test_signed_record_and_unsigned_menu_identify_the_same_action(self):
        tree=Tree({0:{2147483648:1}},[],{1:3})
        tree.canonical=Q.Native.canonical
        found=Q.trace(tree,dict(id=0),[-2147483648],3)
        self.assertEqual(found['actions'],[2147483648])

    def test_valid_recorded_alias_is_a_witness_without_changing_search_menu(self):
        tree=Tree({0:{10:1,20:1}},[],{1:3})
        tree.actions=lambda state:[10] if state['id']==0 else []
        self.assertEqual(Q.trace(tree,dict(id=0),[20],3)['actions'],[20])
        result=self.run_tree(tree)
        self.assertEqual(result['nodes'][0]['menu'],[10])
        Q.verify(tree,dict(id=0),result)


if __name__=='__main__': unittest.main()
