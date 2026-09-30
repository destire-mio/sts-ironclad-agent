#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>
#include <nlohmann/json.hpp>
#include "combat_value_features.h"
#include "combat_search_reuse.h"
#include <fstream>
#include <chrono>
#include <mutex>

namespace py=pybind11;
using namespace sts;
using Search=search::BattleScumSearcher2;
using Clock=std::chrono::steady_clock;
static std::mutex engineMutex;

struct ValueNet {
    std::vector<float> w1,b1,w2,b2;
    explicit ValueNet(const std::string &path) {
        std::ifstream f(path);
        if(!f) throw std::invalid_argument("cannot read value model");
        nlohmann::json j; f>>j;
        if(j.at("schema")!="combat-value-v1" || j.at("width")!=combat_value::WIDTH ||
           j.at("hidden")!=combat_value::HIDDEN) throw std::invalid_argument("model schema mismatch");
        w1=j.at("w1").get<std::vector<float>>(); b1=j.at("b1").get<std::vector<float>>();
        w2=j.at("w2").get<std::vector<float>>(); b2=j.at("b2").get<std::vector<float>>();
        if(w1.size()!=512*32 || b1.size()!=32 || w2.size()!=64 || b2.size()!=2)
            throw std::invalid_argument("invalid model dimensions");
        for(const auto *v:{&w1,&b1,&w2,&b2}) for(float z:*v)
            if(!std::isfinite(z)) throw std::invalid_argument("nonfinite model parameter");
    }
    std::array<float,2> predict(const combat_value::Features &x) const {
        std::array<float,32> h;
        std::copy(b1.begin(),b1.end(),h.begin());
        for(int i=0;i<512;++i) if(x[i]!=0.f)
            for(int k=0;k<32;++k) h[k]+=x[i]*w1[i*32+k];
        std::array<float,2> y;
        for(int o=0;o<2;++o) {
            float s=b2[o];
            for(int k=0;k<32;++k) s+=std::max(0.f,h[k])*w2[o*32+k];
            y[o]=1.f/(1.f+std::exp(-s));
        }
        return y;
    }
    double value(const BattleContext &b) const {
        if(b.outcome!=Outcome::UNDECIDED) return b.outcome==Outcome::PLAYER_VICTORY ?
            .8+.2*std::clamp(b.player.curHp/double(std::max(1,b.player.maxHp)),0.,1.) : 0.;
        auto p=predict(combat_value::features(b));
        return .8*p[0]+.2*p[1];
    }
};

static void active(const GameContext &g) {
    if(g.screenState!=ScreenState::BATTLE || g.outcome!=GameOutcome::UNDECIDED)
        throw std::invalid_argument("requires a live battle entry");
}

static py::dict resolve(GameContext &gc, const ValueNet *net, const std::string &mode,
        int simulations, double bossMultiplier, double seconds, double roundSeconds) {
    active(gc);
    if(mode!="reuse" && mode!="prior" && mode!="rollout") throw std::invalid_argument("invalid value mode");
    if(mode!="reuse" && !net) throw std::invalid_argument("value mode requires a model");
    if(simulations<=0 || !std::isfinite(bossMultiplier) || bossMultiplier<=0 ||
       simulations*bossMultiplier>=static_cast<double>(INT64_MAX) || !std::isfinite(seconds) ||
       seconds<0 || !std::isfinite(roundSeconds) || roundSeconds<0)
        throw std::invalid_argument("invalid search budget");
    std::lock_guard<std::mutex> lock(engineMutex);
    BattleContext battle; battle.init(gc);
    const int64_t budget=isBossEncounter(battle.encounter)?simulations*bossMultiplier:simulations;
    if(budget<1) throw std::invalid_argument("empty search budget");
    const int initialHp=battle.player.curHp;
    search::ScumSearchAgent2 agent; agent.recordActions=true;
    std::vector<search::Action> bestActions;
    int bestHp=-1,rounds=0,reused=0;
    int64_t total=0,evaluations=0;
    std::unique_ptr<Search> owned;
    std::vector<double> roundTimes;
    const auto start=Clock::now();
    auto elapsed=[&](){return std::chrono::duration<double>(Clock::now()-start).count();};
    while(battle.outcome==Outcome::UNDECIDED) {
        if(battle.turn>=500) throw std::runtime_error("nonterminal at 500 turns");
        if(!owned) {
            owned=std::make_unique<Search>(battle);
            if(mode=="prior") owned->valuePriorEvaluator=[net](const BattleContext &b){return net->value(b);};
            if(mode=="rollout") owned->rolloutValueEvaluator=[net](const BattleContext &b){return net->value(b);};
        }
        auto &s=*owned;
        const auto old=s.root.simulationCount, oldEval=s.valueEvaluations;
        const auto before=elapsed();
        if(seconds==0) s.search(budget);
        else {
            const double slice=roundSeconds>0?roundSeconds:seconds;
            const double until=std::min(seconds,before+slice);
            // One complete rollout is the minimum atomic operation: it supplies
            // an executable terminal witness even when the deadline is tiny.
            do {s.search(16);} while(elapsed()<until);
        }
        roundTimes.push_back(elapsed()-before);
        total+=s.root.simulationCount-old; evaluations+=s.valueEvaluations-oldEval;
        if(s.outcomePlayerHp>bestHp) {
            bestActions.assign(s.bestActionSequence.rbegin(),s.bestActionSequence.rend());
            bestHp=s.outcomePlayerHp;
        }
        const auto priorCount=agent.gameActionHistory.size();
        if(++rounds>=256 || (seconds>0 && elapsed()>=seconds)) {
            if(bestHp<=0 && s.outcomePlayerHp<0) throw std::runtime_error("deadline without terminal witness");
            auto actions=bestHp>0?bestActions:std::vector(s.bestActionSequence.rbegin(),s.bestActionSequence.rend());
            while(!actions.empty() && battle.outcome==Outcome::UNDECIDED) {
                agent.takeAction(battle,actions.back());actions.pop_back();
            }
            if(battle.outcome==Outcome::UNDECIDED) throw std::runtime_error("witness did not terminate");
        } else if(bestHp>0) agent.stepThroughSolution(battle,bestActions);
        else agent.stepThroughSearchTree(battle,s);
        const auto executed=agent.gameActionHistory.size()-priorCount;
        bool keep=battle.outcome==Outcome::UNDECIDED && executed>0 && executed<=s.bestActionSequence.size();
        auto *retained=&s.root;
        for(std::size_t i=0;i<executed && keep;++i) {
            const auto bits=static_cast<uint32_t>(agent.gameActionHistory[priorCount+i]);
            if(s.bestActionSequence[i].bits!=bits){keep=false;break;}
            Search::Node *child=nullptr;
            for(auto &e:retained->edges) if(e.action.bits==bits){child=&e.node;break;}
            if(!child || child->simulationCount==0){keep=false;break;}
            retained=child;
        }
        if(keep) {
            ++reused;s.retainSubtree(*retained);
            s.rootState=std::make_unique<BattleContext>(battle);
            s.bestActionSequence.erase(s.bestActionSequence.begin(),s.bestActionSequence.begin()+executed);
        } else owned.reset();
    }
    const double used=elapsed();
    py::dict out;
    out["outcome"]=static_cast<int>(battle.outcome);out["win"]=battle.outcome==Outcome::PLAYER_VICTORY;
    out["hp"]=battle.player.curHp;out["max_hp"]=battle.player.maxHp;out["hp_before"]=initialHp;
    out["turns"]=battle.turn+1;out["actions"]=agent.gameActionHistory;out["simulations"]=total;
    out["seconds"]=used;out["round_seconds"]=roundTimes;out["search_rounds"]=rounds;
    out["reused_trees"]=reused;out["value_evaluations"]=evaluations;
    battle.exitBattle(gc);
    return out;
}

// All branch states descend from a real, unmodified natural battle entry.
// Teacher uses the same deterministic game RNG and independent search RNG.
static py::dict collect(const GameContext &gc, int trajectories, int samples, int teacherSims, uint32_t seed) {
    active(gc);
    if(trajectories<1 || samples<1 || teacherSims<1) throw std::invalid_argument("invalid collection budget");
    std::lock_guard<std::mutex> lock(engineMutex);
    std::vector<combat_value::Features> xs;
    std::vector<std::array<float,2>> ys;
    std::vector<std::array<int,3>> meta;
    int faults=0;
    BattleContext root;root.init(gc);
    for(int t=0;t<trajectories;++t) {
        Search sampler(root);sampler.randGen.seed(seed+104729*t);
        std::vector<search::Action> path;
        if(t%2==0){sampler.search(teacherSims);path=sampler.bestActionSequence;}
        else {BattleContext end(root);sampler.playoutRandom(end,path);}
        if(path.empty()){++faults;continue;}
        BattleContext state(root);
        // Concentrate on the first half: near-terminal easy labels otherwise dominate.
        const int extent=std::max(1,static_cast<int>(path.size()/2));
        int next=0;
        for(int i=0;i<extent && state.outcome==Outcome::UNDECIDED;++i) {
            if(i>=next) {
                Search teacher(state);teacher.randGen.seed(seed+104729*t+8191*i+7);
                teacher.search(teacherSims);
                BattleContext end(state);
                for(const auto &a:teacher.bestActionSequence) a.execute(end);
                if(end.outcome==Outcome::UNDECIDED){++faults;}
                else {
                    const bool win=end.outcome==Outcome::PLAYER_VICTORY;
                    xs.push_back(combat_value::features(state));
                    ys.push_back({win?1.f:0.f,win?std::clamp(end.player.curHp/float(std::max(1,end.player.maxHp)),0.f,1.f):0.f});
                    meta.push_back({t,i,state.turn});
                }
                next+=std::max(1,(extent+samples-1)/samples);
            }
            path[i].execute(state);
        }
    }
    py::array_t<float> x({static_cast<py::ssize_t>(xs.size()),py::ssize_t(512)});
    py::array_t<float> y({static_cast<py::ssize_t>(ys.size()),py::ssize_t(2)});
    if(!xs.empty()){std::memcpy(x.mutable_data(),xs.data(),xs.size()*sizeof(xs[0]));std::memcpy(y.mutable_data(),ys.data(),ys.size()*sizeof(ys[0]));}
    py::dict out;out["x"]=x;out["y"]=y;out["meta"]=meta;out["faults"]=faults;
    return out;
}

PYBIND11_MODULE(combat_value,m) {
    m.attr("schema")="combat-value-v1";
    py::class_<ValueNet>(m,"ValueNet").def(py::init<const std::string &>())
      .def("predict",[](const ValueNet &n,py::array_t<float,py::array::c_style|py::array::forcecast> x){
        if(x.ndim()!=2 || x.shape(1)!=512) throw std::invalid_argument("expected [N,512]");
        py::array_t<float> out({x.shape(0),py::ssize_t(2)});
        for(py::ssize_t i=0;i<x.shape(0);++i){combat_value::Features f;std::copy(x.data(i),x.data(i)+512,f.begin());auto y=n.predict(f);std::copy(y.begin(),y.end(),out.mutable_data(i));}
        return out;
      });
    m.def("collect",&collect,py::arg("game"),py::arg("trajectories")=12,py::arg("samples")=8,
          py::arg("teacher_sims")=256,py::arg("seed")=1);
    m.def("resolve",&resolve,py::arg("game"),py::arg("model")=nullptr,py::arg("mode")="reuse",
          py::arg("simulations")=32000,py::arg("boss_multiplier")=12.,py::arg("seconds")=0.,py::arg("round_seconds")=0.);
}
