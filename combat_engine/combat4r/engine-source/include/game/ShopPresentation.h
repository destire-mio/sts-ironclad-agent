#ifndef STS_SHOP_PRESENTATION_H
#define STS_SHOP_PRESENTATION_H

#include <array>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>
#include "game/Random.h"
#include "constants/Potions.h"

namespace sts {

// RNG-relevant presentation state for the installed fixed-frame shop protocol.
// This is external input, just like elapsed play time: a run seed cannot infer it.
// No state or random draws are imported after attaching the initial snapshot.
struct ShopPresentationState {
    enum class Effect { NONE, WAVY, SHAKY };
    struct Word { Effect effect=Effect::NONE; int characters=0; float timer=0; };
    struct Token { Effect effect=Effect::NONE; int characters=0; bool newline=false; };
    struct Floaty {
        float x=0, y=0, vx=0, vy=0, minV=0, maxV=0, threshold=0, speedScale=0;
    } floaty;
    struct Dialog {
        bool present=false, textDone=true;
        float duration=0, wordTimer=0;
        std::vector<Word> words;
        std::vector<Token> tokens;
        std::size_t nextToken=0;
    } dialog;

    bool configured=false, closed=false, characterWords=true, shopVisible=true, saidWelcome=true;
    bool trackPurge=false, trackRewards=false, trackObtain=false, trackUpgrade=false, disableEffects=false;
    struct UpgradeShine { float duration=.8f; bool clang1=false,clang2=false; std::uint64_t order=0; };
    struct UpgradeBrief { std::string id; int upgrades=0,misc=0; float duration=2.5f; };
    std::vector<UpgradeShine> upgradeShines;
    std::vector<UpgradeBrief> upgradeBriefs;
    std::vector<float> upgradeHammers,upgradeSparks;
    struct Tips {
        std::vector<std::string> remaining,refill;
        std::string selected,potionFull;
        bool hasSelected=false;
        std::uint64_t initialCollectionsSeed=0;
    } tips;
    struct HealLine { float duration=0,stagger=0; bool behind=false; };
    std::vector<HealLine> healLines,pendingHealLines;
    std::vector<float> healNumbers,pendingHealNumbers;
    struct PotionDisplay { Potion id=Potion::INVALID; float timer=0; };
    struct PotionParticle { float duration=0; bool rare=false,behind=false; std::uint64_t order=0; };
    std::array<PotionDisplay,3> stockPotions;
    std::vector<PotionDisplay> rewardPotions;
    std::vector<PotionParticle> potionParticles;
    bool rewardsVisible=false;
    float scale=1;
    std::uint64_t nextTopOrder=0,purgeOrder=0;
    struct Purge { bool present=false,fading=false; float duration=0; } purge;
    std::vector<float> topParticles,regularParticles;
    std::vector<float> drawGlows,discardAboveGlows,discardBelowGlows;
    struct Torch { std::string size; bool activated=true; float timer=0; };
    struct Scene {
        int width=0;
        std::vector<float> dust,fog,torchParticles,lightFlares,pendingTorchParticles,pendingLightFlares;
        std::vector<Torch> torches;
    } scene;
    std::int64_t frame=0;
    struct Timing { int card=0,potion=0,blockedPotion=0,relic=0,grid=0,discard=0;
        int purgeOpen=0,purgeConfirm=0,purgeCancel=0;
        int rewardCard=0,rewardPotion=0,rewardPeek=0,rewardBowl=0,rewardReturn=0,mirror=0,upgrade=0; } timing;
    float delta=1.0f/60.0f, speechTimer=0;
    std::array<std::vector<Token>,5> buyMessages;
    std::vector<Token> welcomeMessage,fullPotionMessage;
    std::vector<std::vector<Token>> idleMessages;

    bool active() const { return configured && !closed; }

    // Java float operations round separately; prevent fused multiply-add on ARM.
    static float add(float a,float b) { volatile float x=a+b; return x; }
    static float multiply(float a,float b) { volatile float x=a*b; return x; }
    static float sample(Random &rng,float lo,float hi) {
        return add(lo,multiply(rng.nextFloat(),add(hi,-lo)));
    }

    static bool space(char16_t c) {
        return c==u' ' || (c>=u'\t' && c<=u'\r');
    }
    static std::u16string utf16(const std::string &text) {
        std::u16string result;
        for (std::size_t i=0;i<text.size();) {
            const unsigned char first=text[i++];std::uint32_t cp=0;int extra=0;
            if (first<0x80) cp=first;
            else if (first>=0xc2 && first<=0xdf) {cp=first&31;extra=1;}
            else if (first>=0xe0 && first<=0xef) {cp=first&15;extra=2;}
            else if (first>=0xf0 && first<=0xf4) {cp=first&7;extra=3;}
            else throw std::invalid_argument("invalid UTF-8 shop message");
            if (i+extra>text.size()) throw std::invalid_argument("truncated UTF-8 shop message");
            for (int n=0;n<extra;++n) {
                const unsigned char next=text[i++];
                if ((next&0xc0)!=0x80) throw std::invalid_argument("invalid UTF-8 continuation");
                cp=(cp<<6)|(next&63);
            }
            if ((extra==1 && cp<0x80) || (extra==2 && cp<0x800) || (extra==3 && cp<0x10000) ||
                (cp>=0xd800 && cp<=0xdfff) || cp>0x10ffff)
                throw std::invalid_argument("invalid UTF-8 scalar");
            if (cp<0x10000) result.push_back(static_cast<char16_t>(cp));
            else {cp-=0x10000;result.push_back(static_cast<char16_t>(0xd800+(cp>>10)));result.push_back(static_cast<char16_t>(0xdc00+(cp&1023)));}
        }
        return result;
    }
    static std::vector<Token> parseMessage(const std::string &utf8) {
        const auto text=utf16(utf8);
        if (text.empty() || text.size()>512) throw std::invalid_argument("shop message outside supported size");
        std::vector<Token> result;
        for (std::size_t start=0;start<text.size();) {
            if (space(text[start])) {++start;continue;}
            auto end=start;
            while (end<text.size() && !space(text[end])) {
                // The shipped ENG/ZHS messages use ASCII whitespace. Do not
                // silently replace Java Scanner's wider whitespace semantics.
                const auto c=text[end];
                if ((c>=0x2000 && c<=0x200a) || c==0x2028 || c==0x2029 || c==0x205f || c==0x3000)
                    throw std::invalid_argument("unsupported shop message whitespace");
                ++end;
            }
            auto word=text.substr(start,end-start);start=end;
            Token token;
            if (word==u"NL") token.newline=true;
            else {
                if (word.size()>1 && word[0]==u'#' &&
                    (word[1]==u'r' || word[1]==u'g' || word[1]==u'b' || word[1]==u'y')) word.erase(0,2);
                if (word.size()>2 && word.front()==word.back() && (word[0]==u'~' || word[0]==u'@')) {
                    token.effect=word[0]==u'~'?Effect::WAVY:Effect::SHAKY;
                    word=word.substr(1,word.size()-2);
                }
                token.characters=static_cast<int>(word.size());
            }
            result.push_back(token);
        }
        return result;
    }

    void validateInitial() const {
        if (configured || closed || !shopVisible || frame!=0 || delta!=1.0f/60.0f || timing.card<31 || timing.card>240)
            throw std::invalid_argument("unsupported shop presentation clock or lifecycle");
        for (int n:{timing.potion,timing.blockedPotion,timing.relic,timing.grid,timing.discard,
                    timing.purgeOpen,timing.purgeConfirm,timing.purgeCancel,
                    timing.rewardCard,timing.rewardPotion,timing.rewardPeek,timing.rewardBowl,timing.rewardReturn,timing.mirror,timing.upgrade})
            if (n<0 || n>240) throw std::invalid_argument("shop action clock outside bound");
        if ((timing.grid && timing.grid<2) || (timing.relic && timing.relic<2) ||
            (timing.blockedPotion && timing.blockedPotion<121))
            throw std::invalid_argument("shop action clock precedes installed decision boundary");
        if ((timing.purgeOpen && timing.purgeOpen<2) || (timing.purgeConfirm && timing.purgeConfirm<4) ||
            (timing.purgeCancel && timing.purgeCancel<2) || purge.present || !topParticles.empty() || !regularParticles.empty())
            throw std::invalid_argument("unsupported initial purge effects or clock");
        if ((timing.purgeOpen || timing.purgeConfirm || timing.purgeCancel) && !trackPurge)
            throw std::invalid_argument("purge timing requires its presentation profile");
        if ((timing.rewardCard && timing.rewardCard<34) || (timing.rewardPeek && timing.rewardPeek<4) ||
            (timing.rewardBowl && timing.rewardBowl<4) || (timing.rewardReturn && timing.rewardReturn<4))
            throw std::invalid_argument("reward clock precedes installed decision boundary");
        if ((timing.rewardCard || timing.rewardPotion || timing.rewardPeek || timing.rewardBowl || timing.rewardReturn) && !trackRewards)
            throw std::invalid_argument("reward timing requires its presentation profile");
        if ((trackObtain && !trackRewards) || (timing.mirror && (!trackObtain || timing.mirror<61)))
            throw std::invalid_argument("mirror timing requires its obtain profile and settled decision boundary");
        if ((trackUpgrade && !trackObtain) || (timing.upgrade && (!trackUpgrade || timing.upgrade<2)) ||
            !upgradeShines.empty() || !upgradeBriefs.empty() || !upgradeHammers.empty() || !upgradeSparks.empty())
            throw std::invalid_argument("unsupported initial upgrade state or timing");
        if (trackRewards && (!trackPurge || tips.remaining.empty() || tips.remaining.size()>128 ||
            tips.refill.empty() || tips.refill.size()>128 || tips.potionFull.empty() || tips.initialCollectionsSeed>0xffffffffffffULL ||
            !healLines.empty() || !pendingHealLines.empty() || !healNumbers.empty() || !pendingHealNumbers.empty()))
            throw std::invalid_argument("unsupported initial shop reward state");
        if (trackRewards) {
            if (!std::isfinite(scale) || scale<=0 || scale>8 || rewardsVisible || !rewardPotions.empty() || !potionParticles.empty())
                throw std::invalid_argument("unsupported initial potion presentation");
            for (const auto &p:stockPotions) if (!std::isfinite(p.timer) || p.timer<0 || p.timer>.5f)
                throw std::invalid_argument("invalid potion sparkle timer");
        }
        for (const auto *group:{&drawGlows,&discardAboveGlows,&discardBelowGlows}) {
            const bool draw=group==&drawGlows;
            if (group->size()>(draw?25u:9u)) throw std::invalid_argument("shop panel glow count outside bound");
            for (float duration:*group) if (!std::isfinite(duration) || duration<0 || duration>(draw?5.0f:.9f))
                throw std::invalid_argument("invalid shop panel glow lifetime");
        }
        if (trackPurge) {
            if (scene.width<=0 || scene.width>16384 || scene.dust.size()>96 || scene.fog.size()>50 || scene.torches.size()>32 ||
                !scene.torchParticles.empty() || !scene.lightFlares.empty())
                throw std::invalid_argument("unsupported initial shop scene");
            for (const auto *group:{&scene.dust,&scene.fog}) for (float duration:*group)
                if (!std::isfinite(duration) || duration<0 || duration>(group==&scene.dust?14.0f:12.0f))
                    throw std::invalid_argument("invalid shop scene effect lifetime");
            for (const auto &torch:scene.torches)
                if ((torch.size!="S" && torch.size!="M" && torch.size!="L") ||
                    !std::isfinite(torch.timer) || torch.timer<0 || torch.timer>.1f)
                    throw std::invalid_argument("invalid shop scene torch");
        }
        const float values[]={floaty.x,floaty.y,floaty.vx,floaty.vy,floaty.minV,floaty.maxV,
            floaty.threshold,floaty.speedScale,speechTimer,dialog.duration,dialog.wordTimer};
        for (float v:values) if (!std::isfinite(v)) throw std::invalid_argument("non-finite shop presentation state");
        if (floaty.minV<0 || floaty.maxV<floaty.minV || floaty.threshold<=0 || floaty.speedScale<0 ||
            (idleMessages.empty() && speechTimer<=delta))
            throw std::invalid_argument("shop presentation requires a waiting merchant and valid Floaty state");
        if (!dialog.textDone || (dialog.present && dialog.duration<=0))
            throw std::invalid_argument("unfinished initial shop dialogue needs Scanner state");
        if (!dialog.present && !dialog.words.empty()) throw std::invalid_argument("words without shop dialogue");
        if (dialog.words.size()>512) throw std::invalid_argument("shop dialogue outside supported size");
        for (const auto &word:dialog.words)
            if (!std::isfinite(word.timer) || word.characters<0 || word.characters>512)
                throw std::invalid_argument("invalid shop word state");
        for (const auto &msg:buyMessages) if (msg.empty() || msg.size()>64)
            throw std::invalid_argument("missing or oversized shop buy message");
        if ((!idleMessages.empty() && welcomeMessage.empty()) || idleMessages.size()>128)
            throw std::invalid_argument("invalid shop idle messages");
        if ((timing.potion || timing.blockedPotion || timing.relic || timing.grid || timing.discard) &&
            (idleMessages.empty() || fullPotionMessage.empty()))
            throw std::invalid_argument("extended shop actions need idle and blocked-potion messages");
    }

    void updateFloaty(Random &rng) {
        auto &f=floaty;
        f.x=add(f.x,multiply(f.vx,delta));f.y=add(f.y,multiply(f.vy,delta));
        const float lo=multiply(f.minV,f.speedScale),hi=multiply(f.maxV,f.speedScale);
        if (f.y>f.threshold) f.vy=-sample(rng,lo,hi);
        else if (f.y< -f.threshold) f.vy=sample(rng,lo,hi);
        if (f.x>f.threshold) f.vx=-sample(rng,lo,hi);
        else if (f.x< -f.threshold) f.vx=sample(rng,lo,hi);
    }

    void updateDialog(Random &rng) {
        if (!dialog.present) return;
        dialog.wordTimer=add(dialog.wordTimer,-delta);
        if (dialog.wordTimer<0 && !dialog.textDone) {
            dialog.wordTimer=.03f;
            if (dialog.nextToken==dialog.tokens.size()) dialog.textDone=true;
            else {
                const auto &token=dialog.tokens[dialog.nextToken++];
                if (!token.newline) for (int i=0;i<(characterWords?token.characters:1);++i) {
                    Word word;word.effect=token.effect;word.characters=characterWords?1:token.characters;
                    if (word.effect==Effect::WAVY) word.timer=multiply(rng.nextFloat(),1.5707964f);
                    dialog.words.push_back(word);
                }
            }
        }
        for (auto &word:dialog.words) {
            if (word.effect==Effect::SHAKY) {
                word.timer=add(word.timer,-delta);
                if (word.timer<0) {rng.nextFloat();rng.nextFloat();word.timer=.02f;}
            } else if (word.effect==Effect::WAVY) word.timer=add(word.timer,multiply(delta,5.0f));
        }
        dialog.duration=add(dialog.duration,-delta);
        if (dialog.duration<0) dialog=Dialog{};
    }

    void createSpeech(Random &rng,const std::vector<Token> &tokens) {
        rng.nextBoolean();sample(rng,660,1260);
        dialog=Dialog{};dialog.present=true;dialog.textDone=false;dialog.duration=4;dialog.tokens=tokens;
    }
    void buySpeech(Random &rng) {
        rng.nextInt(3); // voice selection, without randomized pitch
        const int message=rng.nextInt(5);createSpeech(rng,buyMessages[message]);
    }
    void updateSpeech(Random &rng) {
        updateDialog(rng);speechTimer=add(speechTimer,-delta);
        if (!dialog.present && speechTimer<=0) {
            if (idleMessages.empty()) throw std::runtime_error("shop idle speech outside declared presentation scope");
            speechTimer=sample(rng,40,60);
            if (!saidWelcome) {createSpeech(rng,welcomeMessage);saidWelcome=true;rng.nextInt(3);}
            else {rng.nextInt(6);const int message=rng.nextInt(static_cast<int>(idleMessages.size()));createSpeech(rng,idleMessages[message]);}
        }
    }
    void beginShopFrame(Random &rng) {++frame;updateFloaty(rng);}
    void update(Random &rng) {
        if (shopVisible) {beginShopFrame(rng);updateSpeech(rng);} else ++frame;
    }
    void render(Random &rng) {
        if (trackRewards) {
            if (shopVisible) for (auto &p:stockPotions) sparkle(rng,p);
            if (rewardsVisible) for (auto &p:rewardPotions) sparkle(rng,p);
        }
        if (shopVisible && dialog.present) for (const auto &word:dialog.words) if (word.effect==Effect::SHAKY)
            for (int i=0;i<word.characters;++i) {rng.nextFloat();rng.nextFloat();}
    }
    static void requireClock(int n) {
        if (!n) throw std::invalid_argument("shop action outside declared presentation timing scope");
    }
    void updateLifetimes(std::vector<float> &group) {
        for (std::size_t i=0;i<group.size();) {
            group[i]=add(group[i],-delta);
            if (group[i]<0) group.erase(group.begin()+i);else ++i;
        }
    }
    void updatePanels(Random &rng) {
        if (!trackPurge) return;
        // OverlayMenu updates these panels even when hidden. BaseMod's pool
        // calls the original constructor body as setup(), preserving draw order.
        updateLifetimes(drawGlows);
        if (!disableEffects && drawGlows.size()<25) {
            const float duration=sample(rng,2,5);
            rng.nextFloat();rng.nextFloat();rng.nextBoolean();rng.nextBoolean();
            rng.nextFloat();rng.nextInt(6);rng.nextFloat();rng.nextFloat();rng.nextFloat();
            drawGlows.push_back(duration);
        }
        updateLifetimes(discardAboveGlows);updateLifetimes(discardBelowGlows);
        for (auto *group:{&discardAboveGlows,&discardBelowGlows}) if (!disableEffects && group->size()<9) {
            rng.nextInt(6);rng.nextInt(10); // image, then perimeter position
            const float duration=sample(rng,.4f,.9f);
            for (int field=0;field<5;++field) rng.nextFloat();
            rng.nextBoolean();rng.nextFloat();
            group->push_back(duration);
        }
    }
    void updateScene(Random &rng) {
        if (!trackPurge) return;
        // TheBottomScene runs only while the dungeon screen is NONE. During
        // the installed leave protocol this is the second and third frame.
        updateLifetimes(scene.dust);
        if (!disableEffects && scene.dust.size()<96) {
            const float duration=sample(rng,5,14);
            rng.nextInt(6);rng.nextFloat();rng.nextInt(scene.width+1);
            for (int field=0;field<6;++field) rng.nextFloat();
            scene.dust.push_back(duration);
        }
        if (!disableEffects && scene.fog.size()<50) {
            rng.nextBoolean();rng.nextBoolean();
            const float duration=sample(rng,10,12);rng.nextInt(3);
            for (int field=0;field<8;++field) rng.nextFloat();
            scene.fog.push_back(duration);
        }
        updateLifetimes(scene.fog); // Newly added fog updates in its spawn frame.
        for (auto &torch:scene.torches) if (torch.activated && !disableEffects) {
            torch.timer=add(torch.timer,-delta);
            if (torch.timer<0) {
                torch.timer=.1f;
                const float particle=sample(rng,1.5f,3);rng.nextInt(3);
                for (int field=0;field<7;++field) rng.nextFloat();
                const float flare=sample(rng,2,3);rng.nextInt(2);
                for (int field=0;field<5;++field) rng.nextFloat();
                // They join effectsQueue, which is drained after global updates.
                scene.pendingTorchParticles.push_back(particle);scene.pendingLightFlares.push_back(flare);
            }
        }
    }
    void updateTorchParticles() {
        updateLifetimes(scene.torchParticles);updateLifetimes(scene.lightFlares);
        scene.torchParticles.insert(scene.torchParticles.end(),scene.pendingTorchParticles.begin(),scene.pendingTorchParticles.end());
        scene.lightFlares.insert(scene.lightFlares.end(),scene.pendingLightFlares.begin(),scene.pendingLightFlares.end());
        scene.pendingTorchParticles.clear();scene.pendingLightFlares.clear();
    }
    void createUpgrade(const std::vector<UpgradeBrief> &cards) {
        requireUpgrade();
        if (cards.empty()) return;
        upgradeBriefs.insert(upgradeBriefs.end(),cards.begin(),cards.end());
        upgradeShines.push_back({.8f,false,false,nextTopOrder++});
    }
    void upgradeClank(Random &rng) {
        // The hammer exists even with effects disabled. New queued particles
        // render this frame and start their lifetime updates next frame.
        rng.nextFloat();rng.nextFloat();upgradeHammers.push_back(.7f);
        if (!disableEffects) for (int i=0;i<30;++i) {
            rng.nextFloat();rng.nextFloat(); // spawn position, before constructor
            rng.nextBoolean();
            const float duration=sample(rng,.5f,1);
            for (int field=0;field<8;++field) rng.nextFloat();
            upgradeSparks.push_back(duration);
        }
    }
    void updateUpgrades(Random &rng,bool hadPurge,bool beforePurge) {
        for (std::size_t i=0;i<upgradeShines.size();) {
            auto &e=upgradeShines[i];
            if ((!hadPurge || e.order<purgeOrder)!=beforePurge) {++i;continue;}
            // Original tests the first two thresholds before subtracting delta,
            // and the last threshold afterwards. Keep Java float32 rounding.
            if (e.duration<.6f && !e.clang1) {e.clang1=true;upgradeClank(rng);}
            if (e.duration<.2f && !e.clang2) {e.clang2=true;upgradeClank(rng);}
            e.duration=add(e.duration,-delta);
            if (e.duration<0) {upgradeClank(rng);upgradeShines.erase(upgradeShines.begin()+i);}
            else ++i;
        }
    }
    void updateTopEffects(Random &rng) {
        // New particles enter their queues after this frame's updates. Existing
        // particles have no RNG consumers; their lifetimes remain value-owned.
        updateLifetimes(topParticles);updateLifetimes(regularParticles);
        updateLifetimes(upgradeHammers);updateLifetimes(upgradeSparks);
        for (std::size_t i=0;i<upgradeBriefs.size();) {
            auto &e=upgradeBriefs[i];e.duration=add(e.duration,-delta);
            if (e.duration<0) upgradeBriefs.erase(upgradeBriefs.begin()+i);else ++i;
        }
        for (std::size_t i=0;i<potionParticles.size();) {
            potionParticles[i].duration=add(potionParticles[i].duration,-delta);
            if (potionParticles[i].duration<0) potionParticles.erase(potionParticles.begin()+i);else ++i;
        }
        const bool hadPurge=purge.present;
        updateUpgrades(rng,hadPurge,true);
        if (purge.present) purge.duration=add(purge.duration,-delta);
        if (purge.present && purge.duration<.5f && !purge.fading) {
            purge.fading=true;
            if (!disableEffects) for (int i=0;i<24;++i) {
                const float duration=sample(rng,.8f,1.1f);
                // DamageImpactCurvyEffect: duration, speed, target speed,
                // rotation, wave intensity, wave speed and final target speed.
                for (int field=0;field<6;++field) rng.nextFloat();
                (i<16?topParticles:regularParticles).push_back(duration);
            }
        }
        if (purge.present && purge.duration<0) purge=Purge{};
        updateUpgrades(rng,hadPurge,false);
        updateTorchParticles();
    }
    void updateRegularEffects(Random &rng) {
        // Existing effectList entries update before its queue is drained. A
        // newly constructed heal line renders this frame but updates next frame.
        updateLifetimes(healNumbers);
        for (std::size_t i=0;i<healLines.size();) {
            auto &line=healLines[i];
            if (line.stagger>0) line.stagger=add(line.stagger,-delta);
            else {line.duration=add(line.duration,-delta);rng.nextFloat();}
            if (line.duration<0) healLines.erase(healLines.begin()+i);else ++i;
        }
    }
    void drainHealingQueues() {
        healLines.insert(healLines.end(),pendingHealLines.begin(),pendingHealLines.end());pendingHealLines.clear();
        healNumbers.insert(healNumbers.end(),pendingHealNumbers.begin(),pendingHealNumbers.end());pendingHealNumbers.clear();
    }
    void updateEffects(Random &rng) {updateTopEffects(rng);updateRegularEffects(rng);}
    void renderHeal(Random &rng) {
        // Both effectList passes precede the screen (merchant speech) and
        // topLevelEffects (purge). Preserve each line's renderBehind identity.
        for (bool behind:{true,false}) for (const auto &line:healLines)
            if (line.behind==behind && line.stagger<=0) for (int i=0;i<4;++i) rng.nextFloat();
    }
    void renderEffects(Random &rng) {
        auto particles=[&](bool before) {
            for (const auto &p:potionParticles) if (!p.behind && (purge.present && p.order<purgeOrder)==before)
                for (int i=0;i<(p.rare?1:2);++i) rng.nextFloat();
        };
        particles(true);
        // PurgeCardEffect.renderVfx samples two scales for each of three layers.
        if (purge.present) for (int layer=0;layer<3;++layer) {rng.nextFloat();rng.nextFloat();}
        particles(false);
        // Each remaining top-level effect only samples render coordinates or
        // scales here. Their pure float draws do not alter stored lifetime state.
        for (std::size_t i=0;i<upgradeHammers.size();++i) {rng.nextFloat();rng.nextFloat();}
        for (std::size_t i=0;i<upgradeSparks.size();++i)
            for (int field=0;field<4;++field) rng.nextFloat();
    }
    void sparkle(Random &rng,PotionDisplay &p) {
        if (disableEffects || p.id==Potion::INVALID) return;
        const auto rarity=potionRarities[static_cast<int>(p.id)];
        if (rarity!=PotionRarity::RARE && rarity!=PotionRarity::UNCOMMON) return;
        p.timer=add(p.timer,-delta);if (p.timer>=0) return;
        PotionParticle particle;particle.rare=rarity==PotionRarity::RARE;particle.order=nextTopOrder++;
        particle.duration=sample(rng,particle.rare?.9f:.8f,particle.rare?1.2f:1.0f);
        const float particleScale=multiply(sample(rng,.4f,particle.rare?.6f:.7f),scale);
        rng.nextFloat();rng.nextFloat();rng.nextFloat(); // color and position
        if (!particle.rare) {rng.nextFloat();rng.nextFloat();} // velocity
        particle.behind=rng.nextFloat()<add(.2f,add(particleScale,-.5f));rng.nextFloat(); // rotation
        potionParticles.push_back(particle);
        p.timer=sample(rng,particle.rare?.35f:.25f,particle.rare?.5f:.3f);
    }
    void obtainSoul(Random &rng) {sample(rng,4,6);sample(rng,1,1.5f);rng.nextBoolean();rng.nextInt(360);}
    void finishAfterEffects(Random &rng,bool obtainsCard=false) {
        if (obtainsCard) obtainSoul(rng);
        // A regular-effect callback can add healing after older lines update.
        // All queued lines render now and start lifetime updates next frame.
        drainHealingQueues();
        updatePanels(rng);renderHeal(rng);render(rng);renderEffects(rng);
    }
    void finishFrame(Random &rng,bool obtainsCard=false) {
        updateEffects(rng);finishAfterEffects(rng,obtainsCard);
    }
    void advance(Random &rng,int frames) {for (int i=0;i<frames;++i) {update(rng);finishFrame(rng);}}
    void beforeCardPurchase(Random &rng) { update(rng); }
    void beforeShopCardObtain(Random &rng) {
        // Shop cards enter topLevelEffects after the existing top-level effects,
        // following purchase speech and before regular healing updates.
        speechTimer=sample(rng,40,60);
        buySpeech(rng);
        updateTopEffects(rng);
    }
    void afterShopCardObtain(Random &rng) {
        obtainSoul(rng);updateRegularEffects(rng);finishAfterEffects(rng);
        // Frame count is declared before the action, never obtained from an
        // original post-state or trace. Fast-mode Soul callbacks finish by 31.
        advance(rng,timing.card-1);
    }
    void finishEarlyPurchase(Random &rng,int frames,bool opensGrid=false) {
        // Relic/potion updates run before ShopScreen.updateSpeech. Even a relic
        // opening GRID finishes the current shop update, but GRID is rendered.
        updateSpeech(rng);shopVisible=!opensGrid;finishFrame(rng);advance(rng,frames-1);
    }
    void reopenShop() {shopVisible=true;rewardsVisible=false;dialog=Dialog{};speechTimer=1.5f;}
    void finishBottleSelection(Random &rng,bool returnsToShop=true) {
        requireClock(timing.grid);
        // GRID closes during its update; openPreviousScreen(SHOP) calls open().
        ++frame;if (returnsToShop) reopenShop();else rewardsVisible=true;finishFrame(rng);advance(rng,timing.grid-1);
    }
    void requireUpgrade() const {
        if (!trackUpgrade || timing.upgrade<2 || timing.upgrade>240)
            throw std::invalid_argument("upgrade relic requires its presentation scope and clock");
    }
    void requireObtain() const {
        if (!trackObtain) throw std::invalid_argument("on-equip obtain callbacks outside shop presentation scope");
    }
    void requireMirror() const {
        requireObtain();
        if (timing.mirror<61 || timing.mirror>240)
            throw std::invalid_argument("mirror action requires a declared settled frame boundary");
    }
    int beforeMirrorObtain(Random &rng,bool returnsToShop) {
        requireMirror();
        // GRID closes first. OverlayMenu updates the hidden pile panels before
        // Dolly constructs the effect; effectList has already updated this frame.
        ++frame;if (returnsToShop) reopenShop();else rewardsVisible=true;
        updateEffects(rng);drainHealingQueues();updatePanels(rng);
        // ShowCardAndObtainEffect queues 50 CardPoofParticles. Their later
        // update/render has no RNG, and all have expired at the settled boundary.
        for (int i=0;i<50;++i) {
            rng.nextBoolean();rng.nextBoolean();rng.nextInt(3);
            for (int field=0;field<9;++field) rng.nextFloat();
        }
        renderHeal(rng);render(rng);renderEffects(rng);
        float duration=.5f;int elapsed=1;
        for (;;) {
            update(rng);
            ++elapsed;duration=add(duration,-delta);
            if (duration<0) {
                // Old effectList entries precede the newly appended obtain
                // effect. Execute its deck callback and Soul after their update.
                updateEffects(rng);return elapsed;
            }
            finishFrame(rng);
        }
    }
    void afterMirrorObtain(Random &rng,int elapsed,bool obtained) {
        finishAfterEffects(rng,obtained);advance(rng,timing.mirror-elapsed);
    }
    void requirePurge() const {
        requireClock(timing.purgeOpen);requireClock(timing.purgeConfirm);requireClock(timing.purgeCancel);
        if (!trackPurge) throw std::invalid_argument("purge outside shop presentation scope");
    }
    void openPurge(Random &rng,std::size_t candidates) {
        requirePurge();
        // Installed CommunicationMod opens the grid directly in its command,
        // before the next frame; it does not click ShopScreen.updatePurgeCard.
        for (std::size_t i=0;i<candidates;++i) rng.nextFloat();
        shopVisible=false;rewardsVisible=false;advance(rng,timing.purgeOpen);
    }
    void beforePurgeSettlement(Random &rng) {
        requirePurge();
        // One preview frame, then GRID closes during the confirm frame. Two
        // following shop frames satisfy the installed purge notification.
        advance(rng,1);++frame;reopenShop();finishFrame(rng);
        beginShopFrame(rng);
    }
    void createPurgeEffect(Random &rng) {
        rng.nextFloat(); // SHOP_PURCHASE pitch; CARD_BURN has no randomized pitch
        purge={true,false,2.0f};
        purgeOrder=nextTopOrder++;
    }
    void afterPurgeSettlement(Random &rng) {
        updateSpeech(rng);finishFrame(rng);advance(rng,timing.purgeConfirm-3);
    }
    void finishPurgeToRewards(Random &rng) {
        requirePurge();advance(rng,1);rewardsVisible=true;advance(rng,timing.purgeConfirm-1);
    }
    void cancelPurge(Random &rng,bool returnsToShop=true) {
        requirePurge();++frame;if (returnsToShop) reopenShop();else rewardsVisible=true;finishFrame(rng);advance(rng,timing.purgeCancel-1);
    }
    void discard(Random &rng) {
        requireClock(timing.discard);advance(rng,timing.discard);
    }
    void requireRewards() const {
        if (!trackRewards) throw std::invalid_argument("reward callbacks outside shop presentation scope");
        requireClock(timing.rewardReturn);
    }
    void openRewards(Random &rng,java::Random &collections) {
        requireRewards();
        rewardsVisible=true;
        const int index=rng.nextInt(static_cast<int>(tips.remaining.size()));
        tips.selected=tips.remaining[index];tips.hasSelected=true;
        tips.remaining.erase(tips.remaining.begin()+index);
        if (tips.remaining.empty()) {
            tips.remaining=tips.refill;
            java::Collections::shuffleWithState(tips.remaining.begin(),tips.remaining.end(),collections);
        }
    }
    void beforeRewardCardObtain(Random &rng) {
        requireRewards();requireClock(timing.rewardCard);
        // Open CARD_REWARD for two frames, click on the third. The queued
        // FastCardObtainEffect reaches Soul on the fourth frame.
        rewardsVisible=false;advance(rng,2);rewardsVisible=true;advance(rng,1);
        update(rng);updateEffects(rng);
    }
    void afterRewardCardObtain(Random &rng) {
        finishAfterEffects(rng,true);advance(rng,timing.rewardCard-4);
    }
    void peekReward(Random &rng) {
        requireRewards();requireClock(timing.rewardPeek);
        rewardsVisible=false;advance(rng,2);rewardsVisible=true;advance(rng,timing.rewardPeek-2);
    }
    void finishRewardPotionClick(Random &rng,bool obtainedPotion) {
        requireRewards();requireClock(timing.rewardPotion);
        update(rng);if (obtainedPotion) rng.nextInt(3);finishFrame(rng);advance(rng,timing.rewardPotion-1);
    }
    void beforeRewardBowl(Random &rng) {
        requireRewards();requireClock(timing.rewardBowl);
        rewardsVisible=false;advance(rng,2);rewardsVisible=true;
        rng.nextFloat(); // The installed command invokes onClick before frame 3.
    }
    void createHealing(Random &rng) {
        rng.nextInt(3); // HealEffect sound
        rng.nextFloat();rng.nextBoolean();rng.nextFloat(); // HealNumberEffect
        pendingHealNumbers.push_back(1.2f);
        for (int i=0;i<18;++i) {
            rng.nextFloat();rng.nextFloat(); // HealEffect position jitter
            HealLine line;line.duration=sample(rng,.6f,1.3f);line.stagger=sample(rng,0,.5f);
            rng.nextFloat();rng.nextBoolean();line.behind=rng.nextFloat()<.3f;
            pendingHealLines.push_back(line);
        }
    }
    void afterRewardBowl(Random &rng) {advance(rng,timing.rewardBowl-2);}
    void beforeRewardReturn(Random &rng) {
        requireRewards();
        update(rng);rewardsVisible=false;finishFrame(rng); // Overlay cancel, before render.
        ++frame; // ShopRoom.updatePurge settles pending removal before scene.update.
    }
    void afterRewardReturn(Random &rng) {
        updateScene(rng);finishFrame(rng);
        ++frame;reopenShop();updateScene(rng);finishFrame(rng);advance(rng,timing.rewardReturn-3);
    }
    void leave(Random &rng) {
        // CancelButton closes SHOP after its update and before its render.
        update(rng);updateEffects(rng);drainHealingQueues();updatePanels(rng);shopVisible=false;renderHeal(rng);renderEffects(rng);
        // Global purge effects keep updating/rendering across SHOP close and
        // MAP open. Map sound occurs in the overlay update after global effects.
        ++frame;updateScene(rng);finishFrame(rng);
        ++frame;updateScene(rng);updateEffects(rng);drainHealingQueues();updatePanels(rng);
        rng.nextBoolean();rng.nextFloat();renderHeal(rng);renderEffects(rng);
        ++frame;finishFrame(rng);closed=true;
    }
};
}
#endif
