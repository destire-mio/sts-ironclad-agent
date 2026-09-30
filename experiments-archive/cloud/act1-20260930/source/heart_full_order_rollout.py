#!/usr/bin/env python3
"""One endpoint ablation: always use the existing card order within random rollouts."""
import argparse
import difflib
from pathlib import Path
import shutil
import subprocess

import heart_adaptive_search as B

REPO,sha,read,write=B.REPO,B.sha,B.read,B.write

SAMPLER='''        // Keep the accepted CARD/POTION/END_TURN draw and its original coin.
        // Every CARD rollout draw now uses the minimum expert ordering. On
        // former random draws that already selected a preferred card, keep the
        // choice and RNG stream. Tree expansion still includes all legal cards.
        if (tempNode.edges[selectedIdx].action.getActionType() == ActionType::CARD) {
            const bool oldExpertDraw = std::uniform_int_distribution<int>(0, 1)(randGen) == 1;
            int bestOrder = std::numeric_limits<int>::max();
            std::vector<int> preferred;
            for (int i = 0; i < static_cast<int>(tempNode.edges.size()); ++i) {
                const auto &candidate = tempNode.edges[i].action;
                if (candidate.getActionType() != ActionType::CARD) continue;
                const int order = search::Expert::getPlayOrdering(
                    state.cards.hand[candidate.getSourceIdx()].getId());
                if (order < bestOrder) {
                    bestOrder = order;
                    preferred.clear();
                }
                if (order == bestOrder) preferred.push_back(i);
            }
            const int selectedOrder = search::Expert::getPlayOrdering(
                state.cards.hand[tempNode.edges[selectedIdx].action.getSourceIdx()].getId());
            if (oldExpertDraw || selectedOrder != bestOrder) {
                selectedIdx = preferred[std::uniform_int_distribution<int>(
                    0, static_cast<int>(preferred.size()) - 1)(randGen)];
            }
        }

'''

FIXTURE=r'''
#include "sim/search/BattleScumSearcher2.h"
#include "sim/search/ExpertKnowledge.h"
#include "game/GameContext.h"
#include <iostream>
#include <string>
using namespace sts;
using namespace sts::search;
int main(int argc,char **argv) {
    if(argc!=2) return 2;
    const bool equal=std::string(argv[1])=="equal";
    GameContext gc(CharacterClass::IRONCLAD,12345678,20);
    if(equal) {
        gc.deck=Deck();
        for(int i=0;i<10;++i) gc.deck.obtainRaw(Card(CardId::STRIKE_RED));
    }
    BattleContext initial;
    initial.init(gc,MonsterEncounter::CULTIST);
    BattleScumSearcher2 query(initial);
    BattleScumSearcher2::Node root;
    query.enumerateActionsForNode(root,initial);
    int minimum=100000,maximum=-100000;
    for(const auto &edge:root.edges) if(edge.action.getActionType()==ActionType::CARD) {
        int order=Expert::getPlayOrdering(initial.cards.hand[edge.action.getSourceIdx()].getId());
        minimum=std::min(minimum,order); maximum=std::max(maximum,order);
    }
    if(equal ? minimum!=maximum : minimum==maximum) return 3;
    int cardDraws=0,nonpreferred=0;
    for(int i=0;i<(equal?64:512);++i) {
        BattleContext bc(initial);
        BattleScumSearcher2 search(bc);
        search.randGen.seed(i+9876);
        std::vector<sts::search::Action> actions;
        search.playoutRandom(bc,actions);
        if(actions.empty()) return 4;
        if(actions.front().getActionType()==ActionType::CARD) {
            ++cardDraws;
            nonpreferred+=Expert::getPlayOrdering(initial.cards.hand[actions.front().getSourceIdx()].getId())!=minimum;
        }
        if(equal) {
            std::cout<<i<<" "<<int(bc.outcome)<<" "<<bc.player.curHp<<" "<<bc.turn<<" ";
            for(const auto &a:actions) std::cout<<a.bits<<",";
            for(const Random *rng:{&bc.aiRng,&bc.cardRandomRng,&bc.miscRng,&bc.monsterHpRng,&bc.potionRng,&bc.shuffleRng})
                std::cout<<" "<<rng->counter<<","<<rng->seed0<<","<<rng->seed1;
            std::cout<<"\n";
        }
    }
    if(!equal) std::cout<<cardDraws<<" "<<nonpreferred<<"\n";
    return 0;
}
'''


def build(root):
    assert not root.exists()
    source=REPO/'runs/heart-binding-build-20260917-01'
    evidence=read(source/'build-report.json')
    for name,expected in evidence['inputs'].items():
        assert sha(source/name)==expected
    root.mkdir(parents=True)
    shutil.copytree(source/'inputs',root/'inputs')
    for name in ('slaythespire.cpp.o','bindings-util.cpp.o'):
        shutil.copy2(source/'fast'/name,root/'inputs'/name)
    shutil.copy2(__file__,root/'build_full_order.py')
    original=(root/'inputs/ordered.cpp').read_text()
    start=original.index("        // Preserve the accepted sampler's CARD/POTION/END_TURN choice.")
    end=original.index('        const auto action = tempNode.edges[selectedIdx].action;',start)
    changed=original[:start]+SAMPLER+original[end:]
    (root/'inputs/full_order.cpp').write_text(changed)
    (root/'inputs/order_contract.cpp').write_text(FIXTURE)
    (root/'full-order.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),changed.splitlines(True),
        fromfile='accepted-E32.cpp',tofile='full-order.cpp')))
    plan={'experiment':'E44',
        'activation':'Whole-game development only if E41 and E42 both fail their verified development gate and then E43 also fails its verified gate. Until then build and implementation contracts only.',
        'hypothesis':'The accepted half-expert rollout was a substantial whole-game gain in E25, whereas unrelated target/resource modifications failed. Test the remaining endpoint once: remove unstructured card-order draws in rollouts while retaining the full legal search tree.',
        'intervention':'Conditioned on CARD, always sample a minimum existing Expert::getPlayOrdering card-target edge. Preserve accepted CARD/POTION/END_TURN sampling, END weight, target-edge weighting, full tree, UCB, original NN, 8000/search and boss x3. Keep the old coin and skip extra resampling on former random draws that already selected a preferred card. No E38/E39/E40/E43 or NN changes.',
        'comparison_scope':'One fixed endpoint at probability1, compared to accepted probability0.5. No fractional probability sweep or post-result coefficient tuning. This changes rollout policy, not game rules or neural learning.',
        'contracts':'Four search-numeric checks; mixed-order synthetic battle confirms nonpreferred CARD first actions disappear only in candidate while all legal tree edges remain; 64 all-equal-order synthetic playouts exactly match accepted actions, terminal HP/turn and all six full RNG streams.',
        'development_gate':{'minimum_heart_wins':63,'maximum_original_wins_lost':10},
        'evaluation':'All1024 E23 natural development roots, zero faults, full terminal replay, every winner fresh NN/MCTS and route audit. Passing frozen candidate gets a new paired1024 acceptance outside all histories. Keep failures and assigned seeds; errors/timeouts are not deaths.',
        'limits':'More structured random rollout can miss useful ordering patterns; full-game validation decides. Total work/time may change despite same per-call budget. Simulator results, Java parity INCOMPLETE, Prismatic Shard excluded.'}
    write(root/'plan.json',plan)
    write(root/'synthetic-fixture-seeds.json',{'synthetic_game_roots':[12345678],
        'role':'Implementation fixture only; exclude from later fresh acceptance.'})
    compiler=['/usr/bin/c++','-std=gnu++17','-arch','arm64','-fPIC','-O2','-UNDEBUG','-I'+str(root/'inputs/include')]
    commands=[]
    def execute(command):
        commands.append(command)
        result=subprocess.run(command,capture_output=True,text=True)
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        return result.stdout
    candidate=root/'candidate';candidate.mkdir()
    obj=candidate/'search.o'
    execute(compiler+['-c',str(root/'inputs/full_order.cpp'),'-o',str(obj)])
    execute(['/usr/bin/c++','-arch','arm64','-bundle','-Wl,-headerpad_max_install_names',
        '-Xlinker','-undefined','-Xlinker','dynamic_lookup','-flto','-o',str(candidate/'slaythespire.cpython-312-darwin.so'),
        str(root/'inputs/slaythespire.cpp.o'),str(root/'inputs/bindings-util.cpp.o'),str(obj),str(root/'inputs/libsts_core.a')])
    results={}
    for arm,search in [('control',root/'inputs/accepted-search.o'),('candidate',obj)]:
        folder=root/arm;folder.mkdir(exist_ok=True)
        executable=folder/'order_contract'
        execute(compiler+[str(root/'inputs/order_contract.cpp'),str(search),str(root/'inputs/libsts_core.a'),'-o',str(executable)])
        for case in ('equal','mixed'):
            stdout=execute([str(executable),case]);(folder/(case+'.txt')).write_text(stdout)
        results[arm]={'mixed_counts':list(map(int,(folder/'mixed.txt').read_text().split())),
                      'equal_sha256':sha(folder/'equal.txt')}
    assert (root/'control/equal.txt').read_bytes()==(candidate/'equal.txt').read_bytes()
    assert results['control']['mixed_counts'][1]>0
    assert results['candidate']['mixed_counts'][0]>400 and results['candidate']['mixed_counts'][1]==0
    executable=candidate/'search_numerics'
    execute(compiler+[str(root/'inputs/search_numerics.cpp'),str(obj),str(root/'inputs/libsts_core.a'),'-o',str(executable)])
    numeric={case:execute([str(executable),case]) for case in ('negative_playout','equal_returns','return_translation','unvisited_edge')}
    write(root/'build-report.json',{'status':'complete','commands':commands,'contracts':results,'numeric_tests':numeric,
        'script_sha256':sha(root/'build_full_order.py'),'plan_sha256':sha(root/'plan.json'),
        'candidate_sha256':sha(candidate/'slaythespire.cpython-312-darwin.so'),
        'inputs':{str(p.relative_to(root)):sha(p) for p in (root/'inputs').rglob('*') if p.is_file()}})
    print({'status':'built_not_activated','contracts':results,'candidate_sha256':read(root/'build-report.json')['candidate_sha256']},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    build(parser.parse_args().root.resolve())
