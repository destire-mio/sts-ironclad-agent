package spirelablogic;

import com.google.gson.*;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.helpers.RelicLibrary;
import com.megacrit.cardcrawl.helpers.PotionHelper;
import com.megacrit.cardcrawl.rooms.ShopRoom;
import com.megacrit.cardcrawl.relics.AbstractRelic;
import com.megacrit.cardcrawl.shop.*;
import communicationmod.ChoiceScreenUtils;
import java.lang.reflect.*;
import java.util.ArrayList;

/** Controlled pre-purchase stock, then ordinary UI commands; reads actual remaining stock. */
public final class ShopContinuationProbe {
    static boolean inventoryAudit=false;
    static boolean sharedMathAudit=false;
    static ObservedMath observedMath=null;
    static long renderFrame=0;
    @com.evacipated.cardcrawl.modthespire.lib.SpirePatch(clz=com.megacrit.cardcrawl.core.CardCrawlGame.class,method="render")
    public static class CountFrames {
        @com.evacipated.cardcrawl.modthespire.lib.SpirePrefixPatch
        public static void beforeRender() {if (sharedMathAudit) ++renderFrame;}
    }
    /** Inherit the licensed RNG algorithm; retain its returned value and state. */
    static final class ObservedMath extends com.badlogic.gdx.math.RandomXS128 {
        final JsonArray draws=new JsonArray();
        ObservedMath(long seed0,long seed1) {super(seed0,seed1);}
        @Override public long nextLong() {
            long value=super.nextLong();
            if (draws!=null) {
                if (draws.size()>=20000) throw new IllegalStateException("shared RNG trace exceeded bound");
                JsonObject draw=new JsonObject();draw.addProperty("index",draws.size());draw.addProperty("value",value);
                draw.addProperty("frame",renderFrame);
                draw.addProperty("seed0",getState(0));draw.addProperty("seed1",getState(1));JsonArray callers=new JsonArray();
                for (StackTraceElement caller:Thread.currentThread().getStackTrace()) {
                    String name=caller.getClassName();
                    if (name.startsWith("com.megacrit.") || name.startsWith("communicationmod."))
                        callers.add(name+"."+caller.getMethodName());
                }
                draw.add("callers",callers);draws.add(draw);
            }
            return value;
        }
    }
    static boolean quietInventoryScreen() {
        com.megacrit.cardcrawl.actions.GameActionManager manager=AbstractDungeon.actionManager;
        return inventoryAudit && !AbstractDungeon.isFadingIn && !AbstractDungeon.isFadingOut
            && !manager.usingCard && manager.actions.isEmpty() && manager.preTurnActions.isEmpty()
            && manager.cardQueue.isEmpty() && manager.monsterQueue.isEmpty()
            && (manager.currentAction==null || manager.currentAction.isDone)
            && !AlignmentProbe.pendingRuleEffect() && SpireLabLogic.effectsSettled();
    }
    static Object field(Object owner,String name) throws Exception {
        Field f=owner.getClass().getDeclaredField(name); f.setAccessible(true); return f.get(owner);
    }
    static void set(Object owner,String name,Object value) throws Exception {
        Field f=owner.getClass().getDeclaredField(name); f.setAccessible(true); f.set(owner,value);
    }
    static JsonArray choices() throws Exception {
        JsonArray out=new JsonArray();
        if (AbstractDungeon.screen!=AbstractDungeon.CurrentScreen.SHOP) return out;
        Method method=ChoiceScreenUtils.class.getDeclaredMethod("getAvailableShopItems"); method.setAccessible(true);
        for (Object item : (ArrayList<?>)method.invoke(null)) {
            JsonObject ref=new JsonObject();
            if (item instanceof StoreRelic) {ref.addProperty("type","RELIC");ref.addProperty("index",(Integer)field(item,"slot"));}
            else if (item instanceof StorePotion) {ref.addProperty("type","POTION");ref.addProperty("index",(Integer)field(item,"slot"));}
            else if (item instanceof AbstractCard) {ref.addProperty("type","CARD");ref.addProperty("index",ChoiceScreenUtils.getShopScreenCards().indexOf(item));}
            else {ref.addProperty("type","REMOVE");ref.addProperty("index",0);}
            out.add(ref);
        }
        return out;
    }
    static JsonObject potionDisplay(com.megacrit.cardcrawl.potions.AbstractPotion potion) throws Exception {
        Field timer=com.megacrit.cardcrawl.potions.AbstractPotion.class.getDeclaredField("sparkleTimer");timer.setAccessible(true);
        JsonObject out=new JsonObject();out.addProperty("id",potion.ID);out.addProperty("timer",timer.getFloat(potion));return out;
    }
    static JsonObject stock() throws Exception {
        JsonObject out=new JsonObject(); JsonArray cards=new JsonArray(),relics=new JsonArray(),potions=new JsonArray();
        for (AbstractCard c : ChoiceScreenUtils.getShopScreenCards()) {
            JsonObject value=OutsideProbe.card(c);value.addProperty("price",c.price);cards.add(value);
        }
        for (StoreRelic r : ChoiceScreenUtils.getShopScreenRelics()) if (!r.isPurchased) {
            JsonObject value=new JsonObject();value.addProperty("slot",(Integer)field(r,"slot"));
            value.addProperty("id",r.relic.relicId);value.addProperty("price",r.price);relics.add(value);
        }
        for (StorePotion p : ChoiceScreenUtils.getShopScreenPotions()) if (!p.isPurchased) {
            JsonObject value=new JsonObject();value.addProperty("slot",(Integer)field(p,"slot"));
            value.addProperty("id",p.potion.ID);value.addProperty("price",p.price);potions.add(value);
        }
        out.add("cards",cards);out.add("relics",relics);out.add("potions",potions);
        out.addProperty("remove_cost",AbstractDungeon.shopScreen.purgeAvailable?ShopScreen.actualPurgeCost:-1);
        return out;
    }
    static JsonArray effectLifetimes(Object panel,String name) throws Exception {
        JsonArray out=new JsonArray();
        for (Object value:(ArrayList<?>)field(panel,name)) {
            com.megacrit.cardcrawl.vfx.AbstractGameEffect effect=(com.megacrit.cardcrawl.vfx.AbstractGameEffect)value;
            if (!effect.isDone) out.add(effect.duration);
        }
        return out;
    }
    static java.util.concurrent.atomic.AtomicLong collectionsSeed() throws Exception {
        Field shared=java.util.Collections.class.getDeclaredField("r");shared.setAccessible(true);
        Object random=shared.get(null);
        if (random==null) throw new IllegalStateException("GameTips has not initialized Collections RNG");
        Field seed=java.util.Random.class.getDeclaredField("seed");seed.setAccessible(true);
        return (java.util.concurrent.atomic.AtomicLong)seed.get(random);
    }
    static ArrayList<String> tipSource() {
        ArrayList<String> result=new ArrayList<>();
        java.util.Collections.addAll(result,com.megacrit.cardcrawl.core.CardCrawlGame.languagePack.getTutorialString("Random Tips").TEXT);
        if (!com.megacrit.cardcrawl.core.Settings.isConsoleBuild)
            java.util.Collections.addAll(result,com.megacrit.cardcrawl.core.CardCrawlGame.languagePack.getTutorialString("PC Tips").TEXT);
        return result;
    }
    static JsonObject presentation() throws Exception {
        JsonObject out=new JsonObject();
        out.addProperty("frame",renderFrame);out.addProperty("delta",com.badlogic.gdx.Gdx.graphics.getDeltaTime());
        out.addProperty("language",com.megacrit.cardcrawl.core.Settings.language.toString());
        out.addProperty("character_words",com.megacrit.cardcrawl.core.Settings.lineBreakViaCharacter);
        out.addProperty("fast_mode",com.megacrit.cardcrawl.core.Settings.FAST_MODE);
        out.addProperty("backgrounded",com.megacrit.cardcrawl.core.Settings.isBackgrounded);
        out.addProperty("mute_background",com.megacrit.cardcrawl.core.CardCrawlGame.MUTE_IF_BG);
        out.addProperty("effects_settled",SpireLabLogic.effectsSettled() && !AlignmentProbe.pendingRuleEffect());
        out.addProperty("touch_screen",com.megacrit.cardcrawl.core.Settings.isTouchScreen);
        out.addProperty("controller",com.megacrit.cardcrawl.core.Settings.isControllerMode);
        JsonArray effects=new JsonArray();
        for (ArrayList<com.megacrit.cardcrawl.vfx.AbstractGameEffect> group:java.util.Arrays.asList(
                AbstractDungeon.topLevelEffects,AbstractDungeon.topLevelEffectsQueue,AbstractDungeon.effectList,AbstractDungeon.effectsQueue))
            for (com.megacrit.cardcrawl.vfx.AbstractGameEffect effect:group) if (!effect.isDone) effects.add(effect.getClass().getName());
        out.add("effects",effects);
        out.addProperty("disable_effects",com.megacrit.cardcrawl.core.Settings.DISABLE_EFFECTS);
        JsonArray purges=new JsonArray(),topParticles=new JsonArray(),regularParticles=new JsonArray();
        for (com.megacrit.cardcrawl.vfx.AbstractGameEffect effect:AbstractDungeon.topLevelEffects) if (!effect.isDone) {
            if (effect instanceof com.megacrit.cardcrawl.vfx.cardManip.PurgeCardEffect) {
                JsonObject value=new JsonObject();value.addProperty("duration",effect.duration);
                value.addProperty("fading",((AbstractCard)field(effect,"card")).fadingOut);purges.add(value);
            } else if (effect instanceof com.megacrit.cardcrawl.vfx.combat.DamageImpactCurvyEffect)
                topParticles.add(effect.duration);
        }
        for (com.megacrit.cardcrawl.vfx.AbstractGameEffect effect:AbstractDungeon.effectList)
            if (!effect.isDone && effect instanceof com.megacrit.cardcrawl.vfx.combat.DamageImpactCurvyEffect)
                regularParticles.add(effect.duration);
        out.add("purge_effects",purges);
        JsonObject particles=new JsonObject();particles.add("top",topParticles);particles.add("regular",regularParticles);
        out.add("purge_particles",particles);
        JsonObject glows=new JsonObject();
        glows.add("draw",effectLifetimes(AbstractDungeon.overlayMenu.combatDeckPanel,"vfxBelow"));
        glows.add("discard_above",effectLifetimes(AbstractDungeon.overlayMenu.discardPilePanel,"vfxAbove"));
        glows.add("discard_below",effectLifetimes(AbstractDungeon.overlayMenu.discardPilePanel,"vfxBelow"));
        out.add("panel_glows",glows);
        JsonObject scene=new JsonObject();scene.addProperty("type",AbstractDungeon.scene.getClass().getSimpleName());
        scene.addProperty("width",com.megacrit.cardcrawl.core.Settings.WIDTH);
        if (AbstractDungeon.scene instanceof com.megacrit.cardcrawl.scenes.TheBottomScene) {
            scene.add("dust",effectLifetimes(AbstractDungeon.scene,"dust"));
            scene.add("fog",effectLifetimes(AbstractDungeon.scene,"fog"));
            JsonArray torches=new JsonArray(),torchParticles=new JsonArray(),lightFlares=new JsonArray();
            for (Object torch:(ArrayList<?>)field(AbstractDungeon.scene,"torches")) {
                JsonObject value=new JsonObject();value.addProperty("size",field(torch,"size").toString());
                value.addProperty("activated",(Boolean)field(torch,"activated"));
                value.addProperty("timer",(Float)field(torch,"particleTimer1"));
                value.addProperty("hovered",((com.megacrit.cardcrawl.helpers.Hitbox)field(torch,"hb")).hovered);
                torches.add(value);
            }
            for (com.megacrit.cardcrawl.vfx.AbstractGameEffect effect:AbstractDungeon.effectList) if (!effect.isDone) {
                String name=effect.getClass().getSimpleName();
                if (name.equals("TorchParticleSEffect") || name.equals("TorchParticleMEffect") || name.equals("TorchParticleLEffect"))
                    torchParticles.add(effect.duration);
                if (name.equals("LightFlareSEffect") || name.equals("LightFlareMEffect") || name.equals("LightFlareLEffect"))
                    lightFlares.add(effect.duration);
            }
            scene.add("torches",torches);scene.add("torch_particles",torchParticles);scene.add("light_flares",lightFlares);
        }
        out.add("scene",scene);
        JsonObject tips=new JsonObject();
        tips.add("remaining",AlignmentProbe.JSON.toJsonTree(field(com.megacrit.cardcrawl.core.CardCrawlGame.tips,"tips")));
        tips.add("refill",AlignmentProbe.JSON.toJsonTree(tipSource()));
        tips.add("selected",AlignmentProbe.JSON.toJsonTree(field(AbstractDungeon.combatRewardScreen,"tip")));
        tips.addProperty("potion_full",com.megacrit.cardcrawl.helpers.GameTips.LABEL[0]);
        tips.addProperty("collections_seed48",collectionsSeed().get());
        out.add("reward_tips",tips);
        JsonObject healing=new JsonObject();JsonArray lines=new JsonArray(),numbers=new JsonArray();
        for (com.megacrit.cardcrawl.vfx.AbstractGameEffect effect:AbstractDungeon.effectList) if (!effect.isDone) {
            if (effect instanceof com.megacrit.cardcrawl.vfx.combat.HealVerticalLineEffect) {
                JsonObject value=new JsonObject();value.addProperty("duration",effect.duration);
                value.addProperty("stagger",(Float)field(effect,"staggerTimer"));value.addProperty("behind",effect.renderBehind);
                lines.add(value);
            } else if (effect instanceof com.megacrit.cardcrawl.vfx.combat.HealNumberEffect) numbers.add(effect.duration);
        }
        healing.add("lines",lines);healing.add("numbers",numbers);out.add("healing",healing);
        out.addProperty("scale",com.megacrit.cardcrawl.core.Settings.scale);
        out.addProperty("rewards_visible",AbstractDungeon.screen==AbstractDungeon.CurrentScreen.COMBAT_REWARD);
        JsonObject displays=new JsonObject();JsonArray shopPotions=new JsonArray(),rewardPotions=new JsonArray(),potionParticles=new JsonArray();
        for (StorePotion item:ChoiceScreenUtils.getShopScreenPotions()) if (!item.isPurchased) {
            JsonObject value=potionDisplay(item.potion);value.addProperty("slot",(Integer)field(item,"slot"));shopPotions.add(value);
        }
        for (com.megacrit.cardcrawl.rewards.RewardItem reward:AbstractDungeon.combatRewardScreen.rewards)
            if (reward.type==com.megacrit.cardcrawl.rewards.RewardItem.RewardType.POTION) rewardPotions.add(potionDisplay(reward.potion));
        int purgeIndex=-1;
        for (int i=0;i<AbstractDungeon.topLevelEffects.size();++i)
            if (!AbstractDungeon.topLevelEffects.get(i).isDone && AbstractDungeon.topLevelEffects.get(i) instanceof com.megacrit.cardcrawl.vfx.cardManip.PurgeCardEffect) purgeIndex=i;
        for (int i=0;i<AbstractDungeon.topLevelEffects.size();++i) {
            com.megacrit.cardcrawl.vfx.AbstractGameEffect effect=AbstractDungeon.topLevelEffects.get(i);
            boolean rare=effect instanceof com.megacrit.cardcrawl.vfx.RarePotionParticleEffect;
            if (!effect.isDone && (rare || effect instanceof com.megacrit.cardcrawl.vfx.UncommonPotionParticleEffect)) {
                JsonObject value=new JsonObject();value.addProperty("duration",effect.duration);value.addProperty("rare",rare);
                value.addProperty("behind",effect.renderBehind);value.addProperty("before_purge",purgeIndex>=0 && i<purgeIndex);
                potionParticles.add(value);
            }
        }
        displays.add("shop",shopPotions);displays.add("rewards",rewardPotions);out.add("potion_displays",displays);out.add("potion_particles",potionParticles);
        JsonObject upgrades=new JsonObject();
        JsonArray shines=new JsonArray(),briefs=new JsonArray(),hammers=new JsonArray(),sparks=new JsonArray();
        for (int i=0;i<AbstractDungeon.topLevelEffects.size();++i) {
            com.megacrit.cardcrawl.vfx.AbstractGameEffect effect=AbstractDungeon.topLevelEffects.get(i);
            if (effect.isDone) continue;
            if (effect instanceof com.megacrit.cardcrawl.vfx.UpgradeShineEffect) {
                JsonObject value=new JsonObject();value.addProperty("duration",effect.duration);
                value.addProperty("clang1",(Boolean)field(effect,"clang1"));value.addProperty("clang2",(Boolean)field(effect,"clang2"));
                value.addProperty("before_purge",purgeIndex>=0 && i<purgeIndex);shines.add(value);
            } else if (effect instanceof com.megacrit.cardcrawl.vfx.cardManip.ShowCardBrieflyEffect) {
                AbstractCard card=(AbstractCard)field(effect,"card");JsonObject value=new JsonObject();
                value.addProperty("id",card.cardID);value.addProperty("upgrades",card.timesUpgraded);value.addProperty("misc",card.misc);
                value.addProperty("duration",effect.duration);value.addProperty("fading",card.fadingOut);briefs.add(value);
            } else if (effect instanceof com.megacrit.cardcrawl.vfx.UpgradeHammerImprintEffect) hammers.add(effect.duration);
            else if (effect instanceof com.megacrit.cardcrawl.vfx.UpgradeShineParticleEffect) sparks.add(effect.duration);
        }
        upgrades.add("shines",shines);upgrades.add("briefs",briefs);upgrades.add("hammers",hammers);upgrades.add("sparks",sparks);
        out.add("upgrade_effects",upgrades);
        out.addProperty("debug_mode",com.megacrit.cardcrawl.core.Settings.isDebug);
        ShopScreen shop=AbstractDungeon.shopScreen;
        out.add("shop",ParityAudit.scalars(shop));out.add("floaty",ParityAudit.scalars(field(shop,"f_effect")));
        Object dialog=field(shop,"dialogTextEffect");out.add("dialog",ParityAudit.scalars(dialog));
        out.add("idle_messages",AlignmentProbe.JSON.toJsonTree(field(shop,"idleMessages")));
        out.addProperty("full_potion_message",StorePotion.TEXT[0]);
        com.megacrit.cardcrawl.vfx.ShopSpeechBubble bubble=(com.megacrit.cardcrawl.vfx.ShopSpeechBubble)field(shop,"speechBubble");
        out.addProperty("bubble_hovered",bubble!=null && bubble.hb.hovered);
        out.addProperty("bubble_matches_dialog",(bubble==null)==(dialog==null) && (bubble==null ||
            Float.floatToIntBits(bubble.duration)==Float.floatToIntBits(((com.megacrit.cardcrawl.vfx.AbstractGameEffect)dialog).duration)));
        JsonArray words=new JsonArray();
        if (dialog!=null) for (Object word:(ArrayList<?>)field(dialog,"words")) {
            JsonObject value=ParityAudit.scalars(word);value.addProperty("text",(String)field(word,"word"));words.add(value);
        }
        out.add("words",words);out.add("shop_names",AlignmentProbe.JSON.toJsonTree(ShopScreen.NAMES));
        return out;
    }
    public static JsonObject advanceTo(JsonObject q) throws Exception {
        long target=q.get("frame").getAsLong();
        if (!sharedMathAudit || target<renderFrame || target-renderFrame>240)
            throw new IllegalArgumentException("declared shop observation frame exceeded or outside wait bound");
        while (renderFrame<target) SpireLabLogic.listener.render();
        if (!SpireLabLogic.effectsSettled() || AlignmentProbe.pendingRuleEffect())
            throw new IllegalStateException("declared shop observation frame has pending rule effects");
        return snapshot();
    }
    public static JsonObject snapshot() throws Exception {
        JsonObject state=TreasureProbe.state();
        if (AbstractDungeon.screen==AbstractDungeon.CurrentScreen.SHOP) state.addProperty("phase","shop");
        else if (AbstractDungeon.screen==AbstractDungeon.CurrentScreen.NONE) state.addProperty("phase","shop_room");
        state.add("stock",stock());
        JsonArray choices=choices(),legal=new JsonArray();
        for (JsonElement value:choices) if (value.getAsJsonObject().get("type").getAsString().equals("RELIC"))
            legal.add(value.getAsJsonObject().get("index"));
        state.add("legal_relic_slots",legal);
        if (inventoryAudit) state.add("shop_actions",choices);
        if (sharedMathAudit) state.add("math_rng",ParityAudit.rngs().get("MathUtils"));
        JsonObject out=new JsonObject();out.add("state",state);out.add("shop_choices",choices);out.add("view",AlignmentProbe.view());
        if (observedMath!=null) out.add("math_trace",observedMath.draws);
        if (sharedMathAudit) out.add("presentation",presentation());
        return out;
    }
    public static JsonObject start(JsonObject q) throws Exception {
        inventoryAudit=q.has("inventory_audit") && q.get("inventory_audit").getAsBoolean();
        sharedMathAudit=q.has("math_rng");observedMath=null;
        TreasureProbe.initialize(q);
        if (q.has("initial_potions")) {
            JsonArray declaredPotions=q.getAsJsonArray("initial_potions");
            if (declaredPotions.size()!=RuleProbe.p().potionSlots) throw new IllegalArgumentException("initial potion capacity differs");
            for (int i=0;i<declaredPotions.size();i++) {
                String id=declaredPotions.get(i).getAsString();
                if (id.equals("Potion Slot")) continue;
                com.megacrit.cardcrawl.potions.AbstractPotion potion=PotionHelper.getPotion(id);
                potion.slot=i;RuleProbe.p().potions.set(i,potion);
            }
        }
        ShopRoom room=new ShopRoom();AbstractDungeon.currMapNode.room=room;room.onPlayerEntry();
        ShopScreen shop=AbstractDungeon.shopScreen;JsonObject declared=q.getAsJsonObject("stock");
        ArrayList<AbstractCard> colored=new ArrayList<AbstractCard>(),colorless=new ArrayList<AbstractCard>();
        for (JsonElement value:declared.getAsJsonArray("cards")) {
            JsonObject spec=value.getAsJsonObject(),request=new JsonObject();request.add("card",spec.get("id"));request.add("upgrades",spec.get("upgrades"));
            AbstractCard card=AlignmentProbe.card(request);card.price=spec.get("price").getAsInt();
            (card.color==AbstractCard.CardColor.COLORLESS?colorless:colored).add(card);
        }
        set(shop,"coloredCards",colored);set(shop,"colorlessCards",colorless);
        ArrayList<StoreRelic> relics=new ArrayList<StoreRelic>();
        for (JsonElement value:declared.getAsJsonArray("relics")) {
            JsonObject spec=value.getAsJsonObject();int slot=spec.get("slot").getAsInt();
            AbstractRelic relic=RelicLibrary.getRelic(spec.get("id").getAsString()).makeCopy();
            if (!relic.canSpawn() || (slot==2)!=(relic.tier==AbstractRelic.RelicTier.SHOP))
                throw new IllegalArgumentException("unavailable shop fixture relic: "+relic.relicId);
            StoreRelic item=new StoreRelic(relic,slot,shop);item.price=spec.get("price").getAsInt();relics.add(item);
        }
        set(shop,"relics",relics);
        ArrayList<StorePotion> potions=new ArrayList<StorePotion>();
        for (JsonElement value:declared.getAsJsonArray("potions")) {
            JsonObject spec=value.getAsJsonObject();StorePotion item=new StorePotion(PotionHelper.getPotion(spec.get("id").getAsString()),spec.get("slot").getAsInt(),shop);
            item.price=spec.get("price").getAsInt();potions.add(item);
        }
        set(shop,"potions",potions);shop.purgeAvailable=true;ShopScreen.purgeCost=75;
        ShopScreen.actualPurgeCost=declared.get("remove_cost").getAsInt();
        // Setup and stock generation are outside this fixture's purchase boundary.
        // Reset the declared RNG inputs after constructing the presentation objects.
        TreasureProbe.resetRandomInputs(q);AbstractDungeon.cardBlizzRandomizer=5;
        shop.open();RuleProbe.flush();
        if (sharedMathAudit) {
            // An explicit initial rendering configuration, never changed after
            // pairing MathUtils or during a purchase/selection sequence.
            if (q.has("disable_effects")) com.megacrit.cardcrawl.core.Settings.DISABLE_EFFECTS=q.get("disable_effects").getAsBoolean();
            if (q.has("initial_tip_indices")) {
                ArrayList<String> source=tipSource(),selected=new ArrayList<>();
                for (JsonElement index:q.getAsJsonArray("initial_tip_indices")) selected.add(source.get(index.getAsInt()));
                if (selected.isEmpty()) throw new IllegalArgumentException("initial tip fixture must be nonempty");
                set(com.megacrit.cardcrawl.core.CardCrawlGame.tips,"tips",selected);
            }
            if (q.has("collections_seed48")) {
                long seed=q.get("collections_seed48").getAsLong();
                if (seed<0 || seed>=(1L<<48)) throw new IllegalArgumentException("Collections state outside 48 bits");
                collectionsSeed().set(seed);
            }
            if (q.has("initial_scene_torches")) {
                if (!(AbstractDungeon.scene instanceof com.megacrit.cardcrawl.scenes.TheBottomScene))
                    throw new IllegalArgumentException("torch fixture needs TheBottomScene");
                ArrayList<com.megacrit.cardcrawl.vfx.scene.InteractableTorchEffect> torches=new ArrayList<>();
                for (JsonElement entry:q.getAsJsonArray("initial_scene_torches")) {
                    JsonObject value=entry.getAsJsonObject();
                    com.megacrit.cardcrawl.vfx.scene.InteractableTorchEffect torch=new com.megacrit.cardcrawl.vfx.scene.InteractableTorchEffect(
                        960,600+40*torches.size(),com.megacrit.cardcrawl.vfx.scene.InteractableTorchEffect.TorchSize.valueOf(value.get("size").getAsString()));
                    set(torch,"activated",value.get("activated").getAsBoolean());set(torch,"particleTimer1",value.get("timer").getAsFloat());
                    torches.add(torch);
                }
                set(AbstractDungeon.scene,"torches",torches);
            }
            int extra=q.has("setup_extra_frames")?q.get("setup_extra_frames").getAsInt():0;
            if (extra<0 || extra>1200) throw new IllegalArgumentException("setup frame count outside diagnostic bound");
            for (int i=0;i<extra;i++) SpireLabLogic.listener.render();
            JsonObject rng=q.getAsJsonObject("math_rng");long seed0=rng.get("seed0").getAsLong(),seed1=rng.get("seed1").getAsLong();
            if (seed0==0 && seed1==0) throw new IllegalArgumentException("invalid zero shared RNG state");
            if (!(com.badlogic.gdx.math.MathUtils.random instanceof com.badlogic.gdx.math.RandomXS128))
                throw new IllegalStateException("unexpected shared RNG implementation");
            // Pair once after setup, before the first command. Never reset at
            // later observations or after any purchase.
            if (q.has("trace_math") && q.get("trace_math").getAsBoolean()) {
                observedMath=new ObservedMath(seed0,seed1);com.badlogic.gdx.math.MathUtils.random=observedMath;
            } else ((com.badlogic.gdx.math.RandomXS128)com.badlogic.gdx.math.MathUtils.random).setState(seed0,seed1);
            renderFrame=0;
        }
        JsonObject out=new JsonObject();out.add("pools",OutsideProbe.pools());out.add("checkpoint",snapshot());return out;
    }
}
