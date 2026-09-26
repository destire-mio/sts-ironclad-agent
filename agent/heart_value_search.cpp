// Value-guided exploration only; native rules, full rollouts and max backups.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <unordered_map>
#include <chrono>
#include "heart_combat_features.h"
#include "sim/search/BattleScumSearcher2.h"
#include "sim/search/ScumSearchAgent2.h"

namespace py=pybind11;
using namespace sts;
using Native=search::BattleScumSearcher2;
using Node=Native::Node;
using Move=search::Action;

struct ValueNetwork {
    int width;std::vector<float> w1,b1,w2,b2,w3;float b3;
    using Array=py::array_t<float,py::array::c_style|py::array::forcecast>;
    ValueNetwork(Array a,Array b,Array c,Array d,Array e,Array f) {
        if(a.ndim()!=2 || a.shape(0)!=64 || b.size()!=64 || c.ndim()!=2 || c.shape(0)!=64 || c.shape(1)!=64
            || d.size()!=64 || e.size()!=64 || f.size()!=1)throw std::invalid_argument("expected width-64-64-1 model");
        width=a.shape(1);w1.resize(width*64);b1.assign(b.data(),b.data()+64);w2.assign(c.data(),c.data()+4096);
        b2.assign(d.data(),d.data()+64);w3.assign(e.data(),e.data()+64);b3=*f.data();
        for(int feature=0;feature<width;++feature)for(int unit=0;unit<64;++unit)w1[feature*64+unit]=a.data()[unit*width+feature];
        for(const auto *weights:{&w1,&b1,&w2,&b2,&w3})for(float v:*weights)
            if(!std::isfinite(v))throw std::invalid_argument("nonfinite model parameter");
        if(!std::isfinite(b3))throw std::invalid_argument("nonfinite output bias");
    }
    float sparse(const combat_value::Builder &f) const {
        if(f.offset!=width)throw std::invalid_argument("encoder width differs from fitted model");
        float h1[64],h2[64];std::copy(b1.begin(),b1.end(),h1);
        for(auto [index,value]:f.values){const float *weight=&w1[index*64];for(int i=0;i<64;++i)h1[i]+=weight[i]*value;}
        for(auto &value:h1)value=std::max(0.f,value);
        for(int i=0;i<64;++i){float value=b2[i];for(int j=0;j<64;++j)value+=w2[i*64+j]*h1[j];h2[i]=std::max(0.f,value);}
        float logit=b3;for(int i=0;i<64;++i)logit+=w3[i]*h2[i];
        return 1.f/(1.f+std::exp(-logit));
    }
    float predict(const BattleContext &b) const{return sparse(combat_value::features(b));}
};

struct Cost {
    std::int64_t simulations=0,searchTransitions=0,priorTransitions=0,predictions=0,expanded=0;
    int replans=0;double seconds=0;
    void add(const Cost &c){simulations+=c.simulations;searchTransitions+=c.searchTransitions;priorTransitions+=c.priorTransitions;
        predictions+=c.predictions;expanded+=c.expanded;replans+=c.replans;seconds+=c.seconds;}
    py::dict dict() const {py::dict d;d["simulations"]=simulations;d["search_transitions"]=searchTransitions;
        d["prior_transitions"]=priorTransitions;d["predictions"]=predictions;d["expanded_nodes"]=expanded;
        d["replans"]=replans;d["search_seconds"]=seconds;return d;}
};

struct Guided {
    Native base;const ValueNetwork &model;bool learned;
    std::unordered_map<const Node*,std::vector<double>> priors;Cost cost;
    Guided(const BattleContext &b,const ValueNetwork &m,bool l):base(b),model(m),learned(l){}
    void expand(Node &node,const BattleContext &state) {
        base.enumerateActionsForNode(node,state);++cost.expanded;
        if(node.edges.empty())throw std::runtime_error("nonterminal node has no legal action");
        std::vector<double> p;double maximum=-1;
        for(auto &edge:node.edges) {
            auto child=state;edge.action.execute(child);++cost.priorTransitions;
            double value=.5;
            if(base.isTerminalState(child))value=combat_value::quality(Native::evaluateEndState(child),child);
            else if(learned){value=model.predict(child);++cost.predictions;}
            p.push_back(value/.2);maximum=std::max(maximum,p.back());
        }
        double total=0;for(auto &value:p){value=std::exp(value-maximum);total+=value;}
        for(auto &value:p)value=.9*value/total+.1/p.size();priors.emplace(&node,std::move(p));
    }
    int select(const Node &node,bool leaf) {
        const auto &p=priors.at(&node);
        if(leaf)return std::discrete_distribution<int>(p.begin(),p.end())(base.randGen);
        double best=-std::numeric_limits<double>::infinity();int selected=0;
        const double range=base.bestActionValue-base.minActionValue;
        for(int i=0;i<static_cast<int>(node.edges.size());++i) {
            const auto &child=node.edges[i].node;double quality=0;
            if(child.simulationCount>0 && std::isfinite(range) && range>0)quality=(child.evaluationSum-base.minActionValue)/range;
            const double value=quality+base.explorationParameter*p[i]*std::sqrt(node.simulationCount+1.)/(child.simulationCount+1.);
            if(value>best){best=value;selected=i;}
        }
        return selected;
    }
    void run(int budget) {
        auto started=std::chrono::steady_clock::now();search::g_debug_scum_search=&base;
        if(base.isTerminalState(*base.rootState))base.search(budget);
        else for(int sim=0;sim<budget;++sim) {
            BattleContext state=*base.rootState;std::vector<Node*> stack{&base.root};std::vector<Move> path;
            while(!base.isTerminalState(state)) {
                auto &node=*stack.back();bool leaf=node.edges.empty();if(leaf)expand(node,state);
                auto &edge=node.edges[select(node,leaf)];edge.action.execute(state);++cost.searchTransitions;
                path.push_back(edge.action);stack.push_back(&edge.node);
                if(leaf){auto count=path.size();base.playoutRandom(state,path);cost.searchTransitions+=path.size()-count;break;}
            }
            // Predicted values never replace a real terminal outcome in backups.
            base.updateFromPlayout(stack,path,state);
        }
        cost.simulations=base.root.simulationCount;cost.replans=1;
        cost.seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
    }
};

static py::dict resolve(BattleContext &battle,int simulations,double bossMultiplier,const ValueNetwork &model,const std::string &arm) {
    if(simulations<=0 || !std::isfinite(bossMultiplier) || bossMultiplier<1)throw std::invalid_argument("invalid budget");
    if(arm!="stock" && arm!="learned" && arm!="constant")throw std::invalid_argument("unknown search arm");
    search::ScumSearchAgent2 solver;solver.simulationCountBase=simulations;solver.bossSimulationMultiplier=bossMultiplier;solver.recordActions=true;
    Cost costs;
    if(arm=="stock") {
        auto start=std::chrono::steady_clock::now();solver.playoutBattle(battle);costs.simulations=solver.simulationCountTotal;
        costs.seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    } else {
        std::vector<Move> bestActions;int bestHp=-1,rounds=0;
        while(battle.outcome==Outcome::UNDECIDED) {
            if(battle.turn>=500)throw std::runtime_error("battle remains undecided at the500-turn search limit");
            const int budget=isBossEncounter(battle.encounter)?bossMultiplier*simulations:simulations;
            Guided guided(battle,model,arm=="learned");guided.run(budget);auto &s=guided.base;costs.add(guided.cost);
            if(s.outcomePlayerHp>bestHp){bestActions=std::vector(s.bestActionSequence.rbegin(),s.bestActionSequence.rend());bestHp=s.outcomePlayerHp;}
            if(++rounds>=256) {
                if(bestHp<=0 && s.outcomePlayerHp<0)throw std::runtime_error("replanning limit without a terminal plan");
                auto actions=bestHp>0?bestActions:std::vector(s.bestActionSequence.rbegin(),s.bestActionSequence.rend());
                while(!actions.empty() && battle.outcome==Outcome::UNDECIDED){solver.takeAction(battle,actions.back());actions.pop_back();}
                if(battle.outcome==Outcome::UNDECIDED)throw std::runtime_error("terminal plan did not reach promised outcome");
                continue;
            }
            if(bestHp>0)solver.stepThroughSolution(battle,bestActions);else solver.stepThroughSearchTree(battle,s);
        }
    }
    py::dict result;result["actions"]=solver.gameActionHistory;result["simulations"]=costs.simulations;
    result["turns"]=battle.turn+1;result["outcome"]=static_cast<int>(battle.outcome);result["cost"]=costs.dict();return result;
}

PYBIND11_MODULE(heart_value_search,m) {
    py::class_<ValueNetwork>(m,"ValueNetwork")
        .def(py::init<ValueNetwork::Array,ValueNetwork::Array,ValueNetwork::Array,ValueNetwork::Array,ValueNetwork::Array,ValueNetwork::Array>())
        .def("predict",&ValueNetwork::predict);
    m.def("resolve_state",&resolve);
    m.def("resolve_battle",[](GameContext &gc,int simulations,double bossMultiplier,const ValueNetwork &model,const std::string &arm) {
        if(gc.screenState!=ScreenState::BATTLE || gc.outcome!=GameOutcome::UNDECIDED)throw std::invalid_argument("requires active battle");
        BattleContext battle;battle.init(gc);auto result=resolve(battle,simulations,bossMultiplier,model,arm);battle.exitBattle(gc);return result;
    });
    m.def("profile",[](const BattleContext &battle,int budget,const ValueNetwork &model,const std::string &arm){
        if(budget<=0 || (arm!="learned" && arm!="constant"))throw std::invalid_argument("invalid search request");
        Guided search(battle,model,arm=="learned");search.run(budget);py::dict out;std::vector<std::uint32_t> actions;
        for(auto a:search.base.bestActionSequence)actions.push_back(a.bits);
        out["actions"]=actions;out["native_value"]=search.base.bestActionValue;out["hp"]=search.base.outcomePlayerHp;
        out["cost"]=search.cost.dict();return out;
    });
}
