#ifndef STS_SHOP_PRESENTATION_JSON_H
#define STS_SHOP_PRESENTATION_JSON_H
#include <nlohmann/json.hpp>
#include "game/ShopPresentation.h"
namespace sts {
inline Potion shopPresentationPotion(const std::string &id) {
    for (int i=2;i<static_cast<int>(sizeof(potionIds)/sizeof(*potionIds));++i)
        if (id==potionIds[i]) return static_cast<Potion>(i);
    throw std::invalid_argument("unsupported shop potion identity");
}
inline ShopPresentationState::Effect shopWordEffect(const std::string &s) {
    using E=ShopPresentationState::Effect;
    if (s=="NONE") return E::NONE;if (s=="WAVY") return E::WAVY;if (s=="SHAKY") return E::SHAKY;
    throw std::invalid_argument("unsupported shop word effect");
}
inline const char *shopWordEffectName(ShopPresentationState::Effect e) {
    using E=ShopPresentationState::Effect;
    switch(e) {case E::NONE:return "NONE";case E::WAVY:return "WAVY";case E::SHAKY:return "SHAKY";}
    throw std::invalid_argument("unsupported shop word effect");
}
inline ShopPresentationState shopPresentationFromJson(const nlohmann::json &j) {
    const bool upgradeProfile=j.at("profile")=="installed-shop-v6";
    const bool obtainProfile=upgradeProfile || j.at("profile")=="installed-shop-v5";
    const bool rewardProfile=obtainProfile || j.at("profile")=="installed-shop-v4";
    const bool purgeProfile=rewardProfile || j.at("profile")=="installed-shop-v3";
    const bool extended=purgeProfile || j.at("profile")=="installed-shop-v2";
    if ((!extended && j.at("profile")!="installed-shop-card-v1") || !j.at("fast_mode").get<bool>() ||
        j.at("backgrounded").get<bool>() || !j.at("initial_effects_settled").get<bool>() ||
        j.at("touch_screen").get<bool>() || j.at("controller").get<bool>() || !j.at("effects").empty())
        throw std::invalid_argument("unsupported shop presentation environment");
    ShopPresentationState s;
    s.delta=j.at("delta");s.frame=j.at("frame");s.timing.card=j.at("purchase_frames");
    s.saidWelcome=j.value("said_welcome",true);s.trackPurge=purgeProfile;s.trackRewards=rewardProfile;s.trackObtain=obtainProfile;s.trackUpgrade=upgradeProfile;
    if (upgradeProfile) for (const auto *key:{"shines","briefs","hammers","sparks"}) {
        const auto &effects=j.at("upgrade_effects").at(key);
        if (!effects.is_array() || !effects.empty()) throw std::invalid_argument("initial upgrade effects must be empty");
    }
    if (rewardProfile) {
        if (j.at("debug_mode").get<bool>() || !j.at("healing").at("lines").empty() || !j.at("healing").at("numbers").empty())
            throw std::invalid_argument("unsupported initial reward environment or healing effects");
        const auto &tips=j.at("reward_tips");
        s.tips.remaining=tips.at("remaining").get<std::vector<std::string>>();
        s.tips.refill=tips.at("refill").get<std::vector<std::string>>();
        s.tips.hasSelected=!tips.at("selected").is_null();
        if (s.tips.hasSelected) s.tips.selected=tips.at("selected");
        s.tips.potionFull=tips.at("potion_full");
        if (!tips.at("collections_seed48").is_number_integer() || tips.at("collections_seed48")<0 ||
            tips.at("collections_seed48")>0xffffffffffffULL)
            throw std::invalid_argument("invalid initial Collections seed");
        s.tips.initialCollectionsSeed=tips.at("collections_seed48");
        s.scale=j.at("scale");s.rewardsVisible=j.at("rewards_visible");
        const auto &displays=j.at("potion_displays");
        if (!displays.at("rewards").is_array() || !displays.at("rewards").empty() ||
            !displays.at("shop").is_array() || !j.at("potion_particles").is_array() || !j.at("potion_particles").empty())
            throw std::invalid_argument("unsupported initial potion effects or rewards");
        int previousSlot=-1;
        for (const auto &p:displays.at("shop")) {
            if (!p.at("slot").is_number_integer()) throw std::invalid_argument("potion display slot must be integer");
            const int slot=p.at("slot");
            if (slot<=previousSlot || slot>=3) throw std::invalid_argument("potion display slots must be in original order");
            previousSlot=slot;s.stockPotions[slot]={shopPresentationPotion(p.at("id")),p.at("timer")};
        }
    }
    if (extended) {
        const auto &clock=j.at("action_frames");
        if (!clock.is_object()) throw std::invalid_argument("shop action clocks must be an object");
        for (const auto &item:clock.items()) {
            const auto &key=item.key();
            if (key!="CARD" && key!="LEAVE" && key!="POTION" && key!="BLOCKED_POTION" &&
                key!="RELIC" && key!="GRID" && key!="DISCARD" &&
                !(purgeProfile && (key=="REMOVE" || key=="PURGE_CONFIRM" || key=="PURGE_CANCEL")) &&
                !(rewardProfile && (key=="REWARD_CARD" || key=="REWARD_POTION" || key=="REWARD_PEEK" ||
                    key=="REWARD_BOWL" || key=="REWARD_RETURN")) && !(obtainProfile && key=="MIRROR") && !(upgradeProfile && key=="UPGRADE"))
                throw std::invalid_argument("unknown shop action clock");
            if (!item.value().is_number_integer() || item.value()<0 || item.value()>240)
                throw std::invalid_argument("shop action clock must be an integer in range");
        }
        s.saidWelcome=j.at("said_welcome");
        if (clock.at("CARD")!=s.timing.card || clock.at("LEAVE")!=4 ||
            j.at("bubble_hovered").get<bool>() || !j.at("bubble_matches_dialog").get<bool>())
            throw std::invalid_argument("unsupported shop timing or hovered dialogue");
        s.timing.potion=clock.value("POTION",0);s.timing.blockedPotion=clock.value("BLOCKED_POTION",0);
        s.timing.relic=clock.value("RELIC",0);s.timing.grid=clock.value("GRID",0);s.timing.discard=clock.value("DISCARD",0);
        if (obtainProfile) s.timing.mirror=clock.value("MIRROR",0);
        if (upgradeProfile) s.timing.upgrade=clock.value("UPGRADE",0);
        if (rewardProfile) {
            s.timing.rewardCard=clock.value("REWARD_CARD",0);s.timing.rewardPotion=clock.value("REWARD_POTION",0);
            s.timing.rewardPeek=clock.value("REWARD_PEEK",0);s.timing.rewardBowl=clock.value("REWARD_BOWL",0);
            s.timing.rewardReturn=clock.value("REWARD_RETURN",0);
        }
        if (purgeProfile) {
            s.timing.purgeOpen=clock.value("REMOVE",0);s.timing.purgeConfirm=clock.value("PURGE_CONFIRM",0);
            s.timing.purgeCancel=clock.value("PURGE_CANCEL",0);s.disableEffects=j.at("disable_effects");
            if (!j.at("purge_effect").is_null() || !j.at("purge_particles").at("top").is_array() ||
                !j.at("purge_particles").at("regular").is_array() || !j.at("purge_particles").at("top").empty() ||
                !j.at("purge_particles").at("regular").empty())
                throw std::invalid_argument("initial purge effects must be empty");
            const auto &glows=j.at("panel_glows");
            s.drawGlows=glows.at("draw").get<std::vector<float>>();
            s.discardAboveGlows=glows.at("discard_above").get<std::vector<float>>();
            s.discardBelowGlows=glows.at("discard_below").get<std::vector<float>>();
            const auto &scene=j.at("scene");
            if (scene.at("type")!="TheBottomScene" || !scene.at("width").is_number_integer())
                throw std::invalid_argument("unsupported shop leave scene");
            s.scene.width=scene.at("width");
            s.scene.dust=scene.at("dust").get<std::vector<float>>();s.scene.fog=scene.at("fog").get<std::vector<float>>();
            s.scene.torchParticles=scene.at("torch_particles").get<std::vector<float>>();
            s.scene.lightFlares=scene.at("light_flares").get<std::vector<float>>();
            if (!scene.at("torches").is_array()) throw std::invalid_argument("invalid shop scene torches");
            for (const auto &torch:scene.at("torches")) {
                if (torch.at("hovered").get<bool>()) throw std::invalid_argument("hovered shop scene torch outside scope");
                s.scene.torches.push_back({torch.at("size"),torch.at("activated"),torch.at("timer")});
            }
        }
        s.welcomeMessage=ShopPresentationState::parseMessage(j.at("welcome_message"));
        s.fullPotionMessage=ShopPresentationState::parseMessage(j.at("full_potion_message"));
        for (const auto &message:j.at("idle_messages")) s.idleMessages.push_back(ShopPresentationState::parseMessage(message));
        if (s.idleMessages.empty()) throw std::invalid_argument("shop idle messages missing");
    }
    s.characterWords=j.at("character_words");s.speechTimer=j.at("speech_timer");
    const auto &f=j.at("floaty");
    s.floaty={f.at("x"),f.at("y"),f.at("vx"),f.at("vy"),f.at("min_v"),f.at("max_v"),f.at("threshold"),f.at("speed_scale")};
    const auto &d=j.at("dialog");
    if (!d.is_null()) {
        s.dialog.present=true;s.dialog.duration=d.at("duration");s.dialog.wordTimer=d.at("word_timer");
        s.dialog.textDone=d.at("text_done");
        for (const auto &w:d.at("words")) s.dialog.words.push_back({shopWordEffect(w.at("effect")),w.at("characters"),w.at("timer")});
    }
    if (j.at("buy_messages").size()!=5) throw std::invalid_argument("five shop buy messages required");
    for (int i=0;i<5;++i) s.buyMessages[i]=ShopPresentationState::parseMessage(j.at("buy_messages").at(i));
    s.validateInitial();return s;
}
inline nlohmann::json shopPresentationToJson(const ShopPresentationState &s,const java::Random *collections=nullptr) {
    using J=nlohmann::json;
    if (!s.configured) return nullptr;
    const auto &f=s.floaty;
    J result={{"frame",s.frame},{"active",s.active() && s.shopVisible},{"character_words",s.characterWords},
        {"said_welcome",s.saidWelcome},
        {"speech_timer",s.speechTimer},{"floaty",{{"x",f.x},{"y",f.y},{"vx",f.vx},{"vy",f.vy},
            {"min_v",f.minV},{"max_v",f.maxV},{"threshold",f.threshold},{"speed_scale",f.speedScale}}},
        {"dialog",nullptr}};
    if (s.dialog.present) {
        J words=J::array();
        for (const auto &w:s.dialog.words) words.push_back({{"effect",shopWordEffectName(w.effect)},
            {"characters",w.characters},{"timer",w.timer}});
        result["dialog"]={{"duration",s.dialog.duration},{"word_timer",s.dialog.wordTimer},
            {"text_done",s.dialog.textDone},{"words",words}};
    }
    if (s.trackPurge) {
        result["disable_effects"]=s.disableEffects;
        result["purge_effect"]=nullptr;
        if (s.purge.present) result["purge_effect"]={{"duration",s.purge.duration},{"fading",s.purge.fading}};
        result["purge_particles"]={{"top",s.topParticles},{"regular",s.regularParticles}};
        result["panel_glows"]={{"draw",s.drawGlows},{"discard_above",s.discardAboveGlows},{"discard_below",s.discardBelowGlows}};
        J torches=J::array();
        for (const auto &torch:s.scene.torches) torches.push_back({{"size",torch.size},{"activated",torch.activated},
            {"timer",torch.timer},{"hovered",false}});
        result["scene"]={{"type","TheBottomScene"},{"width",s.scene.width},{"dust",s.scene.dust},{"fog",s.scene.fog},
            {"torches",torches},{"torch_particles",s.scene.torchParticles},{"light_flares",s.scene.lightFlares}};
    }
    if (s.trackRewards) {
        if (!collections) throw std::invalid_argument("reward snapshot needs the shared Collections state");
        result["reward_tips"]={{"remaining",s.tips.remaining},{"refill",s.tips.refill},
            {"selected",s.tips.hasSelected?J(s.tips.selected):J(nullptr)},
            {"potion_full",s.tips.potionFull},{"collections_seed48",collections->rawSeed()}};
        J lines=J::array();
        for (const auto &line:s.healLines) lines.push_back({{"duration",line.duration},{"stagger",line.stagger},{"behind",line.behind}});
        result["healing"]={{"lines",lines},{"numbers",s.healNumbers}};
        result["scale"]=s.scale;result["rewards_visible"]=s.rewardsVisible;
        J stock=J::array(),rewards=J::array(),particles=J::array();
        for (int i=0;i<3;++i) if (s.stockPotions[i].id!=Potion::INVALID) {
            const auto &p=s.stockPotions[i];stock.push_back({{"slot",i},{"id",potionIds[static_cast<int>(p.id)]},{"timer",p.timer}});
        }
        for (const auto &p:s.rewardPotions) rewards.push_back({{"id",potionIds[static_cast<int>(p.id)]},{"timer",p.timer}});
        for (const auto &p:s.potionParticles) particles.push_back({{"duration",p.duration},{"rare",p.rare},
            {"behind",p.behind},{"before_purge",s.purge.present && p.order<s.purgeOrder}});
        result["potion_displays"]={{"shop",stock},{"rewards",rewards}};result["potion_particles"]=particles;
    }
    if (s.trackUpgrade) {
        J shines=J::array(),briefs=J::array();
        for (const auto &e:s.upgradeShines) shines.push_back({{"duration",e.duration},{"clang1",e.clang1},{"clang2",e.clang2},
            {"before_purge",s.purge.present && e.order<s.purgeOrder}});
        for (const auto &e:s.upgradeBriefs) briefs.push_back({{"id",e.id},{"upgrades",e.upgrades},{"misc",e.misc},
            {"duration",e.duration},{"fading",e.duration<.6f}});
        result["upgrade_effects"]={{"shines",shines},{"briefs",briefs},{"hammers",s.upgradeHammers},{"sparks",s.upgradeSparks}};
    }
    return result;
}
}
#endif
