// Search-result distillation and value-guided exploration on frozen game code.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <unordered_map>
#include <memory>
#include "heart_combat_features.h"
#include "sim/search/BattleScumSearcher2.h"
#include "sim/search/ScumSearchAgent2.h"

namespace py=pybind11;
using namespace sts;
using namespace combat_value;
using Native=search::BattleScumSearcher2;
using Node=Native::Node;
using Move=search::Action;

struct Terminal {
    std::vector<Move> actions;double value;Outcome outcome;int hp;
};

static std::uint64_t pathHash(const std::vector<Move> &path) {
    std::uint64_t h=1469598103934665603ULL;
    for(auto a:path)for(int byte=0;byte<4;++byte){h^=(a.bits>>(byte*8))&255;h*=1099511628211ULL;}
    return h;
}
static std::vector<std::uint32_t> bits(const std::vector<Move> &path) {
    std::vector<std::uint32_t> result;for(auto a:path)result.push_back(a.bits);return result;
}

// This driver follows Native::step, retaining the terminal witness which
// established each node's maximum. Native enumeration, sampling, UCB and backup
// functions perform all search decisions. Recording consumes no random draws.
static py::dict collect(const BattleContext &root,int budget,int minimumVisits,int maximumRows) {
    if(budget<=0 || minimumVisits<=0 || maximumRows<=0)throw std::invalid_argument("positive collection limits required");
    Native search(root);search::g_debug_scum_search=&search;
    if(search.isTerminalState(root)) {
        search.search(budget);py::dict out;out["rows"]=py::list();out["eligible_nodes"]=0;out["unknown_nodes"]=0;
        out["simulations"]=search.root.simulationCount;out["search_transitions"]=0;out["tree_replay_transitions"]=0;
        out["best_actions"]=bits(search.bestActionSequence);out["best_value"]=search.bestActionValue;
        out["best_hp"]=search.outcomePlayerHp;return out;
    }
    std::vector<Terminal> terminals;std::unordered_map<Node*,int> witness;
    std::int64_t transitions=0;
    for(int simulation=0;simulation<budget;++simulation) {
        BattleContext state=root;std::vector<Node*> stack{&search.root};std::vector<Move> path;
        while(!search.isTerminalState(state)) {
            auto &node=*stack.back();const bool leaf=node.edges.empty();
            if(leaf)search.enumerateActionsForNode(node,state);
            int chosen=leaf?search.selectFirstActionForLeafNode(node):search.selectBestEdgeToSearch(node);
            const auto &edge=node.edges[chosen];edge.action.execute(state);++transitions;
            path.push_back(edge.action);stack.push_back(&node.edges[chosen].node);
            if(leaf){const auto before=path.size();search.playoutRandom(state,path);transitions+=path.size()-before;break;}
        }
        const double value=Native::evaluateEndState(state);const int index=terminals.size();
        terminals.push_back({path,value,state.outcome,state.player.curHp});
        for(auto *node:stack)if(node->simulationCount==0 || value>node->evaluationSum)witness[node]=index;
        search.updateFromPlayout(stack,path,state);
    }
    struct Row {Node *node;BattleContext state;std::vector<Move> path;std::uint64_t rank;};
    std::vector<Row> pending;pending.push_back({&search.root,root,{},pathHash({})});
    std::vector<Row> selected;std::int64_t eligible=0,unknown=0,replayed=0;
    while(!pending.empty()) {
        auto row=std::move(pending.back());pending.pop_back();
        if(row.node->simulationCount>=minimumVisits && row.state.outcome==Outcome::UNDECIDED) {
            const auto &terminal=terminals.at(witness.at(row.node));
            if(terminal.outcome==Outcome::UNDECIDED)++unknown;
            else {
                ++eligible;
                // Keep the smallest outcome-blind path hashes with bounded memory.
                if(static_cast<int>(selected.size())<maximumRows)selected.push_back(row);
                else {
                    auto worst=std::max_element(selected.begin(),selected.end(),[](auto &a,auto &b){return a.rank<b.rank;});
                    if(row.rank<worst->rank)*worst=row;
                }
            }
        }
        for(auto &edge:row.node->edges)if(edge.node.simulationCount>=minimumVisits) {
            auto child=row.state;edge.action.execute(child);++replayed;auto path=row.path;path.push_back(edge.action);
            const auto rank=pathHash(path);pending.push_back({&edge.node,std::move(child),std::move(path),rank});
        }
    }
    std::sort(selected.begin(),selected.end(),[](auto &a,auto &b){return a.rank<b.rank;});
    py::list rows;
    for(auto &row:selected) {
        const auto &terminal=terminals.at(witness.at(row.node));
        if(terminal.value!=row.node->evaluationSum || terminal.actions.size()<row.path.size()
            || !std::equal(row.path.begin(),row.path.end(),terminal.actions.begin()))
            throw std::runtime_error("node target is not backed by its recorded terminal path");
        const auto encoded=features(row.state);
        py::dict value;value["path"]=bits(row.path);value["terminal_path"]=bits(terminal.actions);
        value["features"]=encoded.values;value["width"]=encoded.offset;
        value["target"]=quality(terminal.value,row.state);value["native_value"]=terminal.value;
        value["outcome"]=static_cast<int>(terminal.outcome);value["terminal_hp"]=terminal.hp;
        value["visits"]=row.node->simulationCount;rows.append(value);
    }
    py::dict out;out["rows"]=rows;out["eligible_nodes"]=eligible;out["unknown_nodes"]=unknown;
    out["simulations"]=search.root.simulationCount;out["search_transitions"]=transitions;
    out["tree_replay_transitions"]=replayed;out["best_actions"]=bits(search.bestActionSequence);
    out["best_value"]=search.bestActionValue;out["best_hp"]=search.outcomePlayerHp;
    return out;
}

static py::dict encoderTests(const BattleContext &root) {
    const auto original=features(root).values;py::dict out;
    auto b=root;b.seed^=481516;b.shuffleRng.seed0^=54321;b.cardRandomRng.seed1^=67890;
    out["hidden_rng_and_seed_ignored"]=original==features(b).values;
    b=root;std::reverse(b.cards.drawPile.begin(),b.cards.drawPile.end());
    out["draw_order_ignored"]=original==features(b).values;
    b=root;++b.player.curHp;out["HP_changes_input"]=original!=features(b).values;
    b=root;++b.cards.hand[0].costForTurn;out["hand_cost_changes_input"]=original!=features(b).values;
    b=root;++b.cards.hand[0].uniqueId;out["card_instance_ID_ignored"]=original==features(b).values;
    b=root;++b.player.incenseBurnerCounter;out["relic_counter_changes_input"]=original!=features(b).values;
    b=root;b.player.setHasRelic<RelicId::RUNIC_DOME>(true);auto before=features(b).values;
    for(auto &m:b.monsters.arr)m.moveHistory[0]=MMID::INVALID;
    out["runic_dome_masks_intent"]=before==features(b).values;
    return out;
}

PYBIND11_MODULE(heart_combat_value,m) {
    m.def("features",[](const BattleContext &b){auto f=features(b);return py::make_tuple(f.offset,f.values);});
    m.def("quality",&quality);m.def("collect",&collect);m.def("encoder_tests",&encoderTests);
    m.def("terminal_value",&Native::evaluateEndState);
}
