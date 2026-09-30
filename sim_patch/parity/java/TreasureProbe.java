package spirelablogic;

import com.google.gson.*;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.core.Settings;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.helpers.RelicLibrary;
import com.megacrit.cardcrawl.random.Random;
import com.megacrit.cardcrawl.relics.AbstractRelic;
import com.megacrit.cardcrawl.rewards.RewardItem;
import com.megacrit.cardcrawl.rewards.chests.AbstractChest;
import com.megacrit.cardcrawl.rooms.AbstractRoom;
import com.megacrit.cardcrawl.rooms.TreasureRoom;
import java.util.ArrayList;
import java.util.Map;

/** Pre-chest inputs and read-only linked-reward observations; commands execute the game. */
public final class TreasureProbe {
    static final String[] STREAMS = {"aiRng", "monsterHpRng", "shuffleRng", "cardRandomRng", "miscRng",
        "potionRng", "relicRng", "cardRng", "merchantRng", "treasureRng"};
    static final String[] TYPES = {"GOLD", "RELIC", "POTION", "CARD", "SAPPHIRE_KEY", "EMERALD_KEY"};

    static JsonObject state() throws Exception {
        JsonObject outside = OutsideProbe.snapshot();
        JsonObject out = new JsonObject();
        for (String key : new String[]{"hp","max_hp","gold","deck","relics","potions"}) out.add(key,outside.get(key));
        out.addProperty("floor",AbstractDungeon.floorNum);
        JsonObject keys = new JsonObject();
        keys.addProperty("blue",Settings.hasSapphireKey); keys.addProperty("green",Settings.hasEmeraldKey);
        keys.addProperty("red",Settings.hasRubyKey); out.add("keys",keys);
        JsonObject allRng = ParityAudit.rngs(), rng = new JsonObject();
        for (String name : STREAMS) rng.add(name,allRng.get(name)); out.add("rng",rng);
        out.add("reward_state",EventRewardsProbe.rewardState());
        String phase = "outside";
        if (AbstractDungeon.screen == AbstractDungeon.CurrentScreen.GRID) phase = "grid";
        else if (AbstractDungeon.screen == AbstractDungeon.CurrentScreen.COMBAT_REWARD) phase = "rewards";
        else if (AbstractDungeon.screen == AbstractDungeon.CurrentScreen.MAP) phase = "map";
        else if (AbstractDungeon.getCurrRoom() instanceof TreasureRoom) {
            AbstractChest chest = ((TreasureRoom)AbstractDungeon.getCurrRoom()).chest;
            if (chest != null && !chest.isOpen) phase = "chest";
        }
        out.addProperty("phase",phase);
        JsonElement chestState = JsonNull.INSTANCE;
        if (phase.equals("chest")) {
            AbstractChest c = ((TreasureRoom)AbstractDungeon.getCurrRoom()).chest;
            JsonObject value = new JsonObject();
            value.addProperty("size",c.getClass().getSimpleName());
            value.addProperty("has_gold",c.goldReward);
            value.addProperty("relic_tier",c.relicReward.toString()); chestState = value;
        }
        out.add("chest",chestState);
        JsonObject selection = new JsonObject();
        selection.add("count",outside.get("selection_count")); selection.add("choices",outside.get("selection"));
        out.add("selection",selection);
        JsonObject groups = new JsonObject(); JsonArray order = new JsonArray();
        for (String type : TYPES) groups.add(type,new JsonArray());
        if (phase.equals("grid") || phase.equals("rewards")) {
            ArrayList<RewardItem> rewards = AbstractDungeon.combatRewardScreen.rewards;
            for (RewardItem reward : rewards) {
                String type = reward.type.toString();
                if (!groups.has(type)) throw new IllegalArgumentException("unsupported chest reward: " + type);
                JsonArray group = groups.getAsJsonArray(type); JsonObject reference = new JsonObject();
                reference.addProperty("type",type); reference.addProperty("index",group.size()); order.add(reference);
                JsonObject item = new JsonObject();
                if (reward.type == RewardItem.RewardType.GOLD) item.addProperty("gold",reward.goldAmt+reward.bonusGold);
                else if (reward.type == RewardItem.RewardType.RELIC) {
                    item.addProperty("id",reward.relic.relicId);
                    item.addProperty("linked_to_key",reward.relicLink != null && rewards.contains(reward.relicLink)
                        && reward.relicLink.type == RewardItem.RewardType.SAPPHIRE_KEY);
                } else if (reward.type == RewardItem.RewardType.POTION) item.addProperty("id",reward.potion.ID);
                else if (reward.type == RewardItem.RewardType.CARD) {
                    JsonArray cards = new JsonArray(); for (AbstractCard c : reward.cards) cards.add(OutsideProbe.card(c));
                    item.add("cards",cards);
                } else if (reward.type == RewardItem.RewardType.SAPPHIRE_KEY) {
                    int index = 0, linked = -1;
                    for (RewardItem candidate : rewards) if (candidate.type == RewardItem.RewardType.RELIC) {
                        if (candidate == reward.relicLink) linked = index;
                        ++index;
                    }
                    item.addProperty("relic_index",linked);
                }
                group.add(item);
            }
        }
        out.add("reward_groups",groups); out.add("reward_order",order);
        return out;
    }

    public static JsonObject snapshot() throws Exception {
        JsonObject out = new JsonObject(); out.add("state",state()); out.add("view",AlignmentProbe.view()); return out;
    }

    static void initialize(JsonObject q) throws Exception {
        RuleProbe.base();
        Settings.seed=q.get("seed").getAsLong(); AbstractDungeon.floorNum=q.get("floor").getAsInt();
        AbstractDungeon.actNum=q.get("act").getAsInt();
        RuleProbe.p().masterDeck.clear();
        for (JsonElement value : q.getAsJsonArray("deck")) {
            JsonObject spec=value.getAsJsonObject(), request=new JsonObject();
            request.add("card",spec.get("id")); request.add("upgrades",spec.get("upgrades"));
            RuleProbe.p().masterDeck.addToBottom(AlignmentProbe.card(request));
        }
        for (JsonElement value : q.getAsJsonArray("relics")) {
            String id=value.isJsonPrimitive()?value.getAsString():value.getAsJsonObject().get("id").getAsString();
            AbstractRelic relic=RelicLibrary.getRelic(id).makeCopy(); RuleProbe.p().relics.add(relic); relic.onEquip();
            if (value.isJsonObject() && value.getAsJsonObject().has("counter")) relic.setCounter(value.getAsJsonObject().get("counter").getAsInt());
        }
        RuleProbe.p().currentHealth=q.get("hp").getAsInt(); RuleProbe.p().maxHealth=q.get("max_hp").getAsInt();
        RuleProbe.p().isBloodied=RuleProbe.p().currentHealth<=RuleProbe.p().maxHealth/2; RuleProbe.p().gold=q.get("gold").getAsInt();
        RuleProbe.p().potions.clear(); RuleProbe.p().potionSlots=2;
        for (int i=0;i<2;i++) RuleProbe.p().potions.add(new com.megacrit.cardcrawl.potions.PotionSlot(i));
        Settings.hasSapphireKey=q.get("blue_key").getAsBoolean(); Settings.hasRubyKey=false; Settings.hasEmeraldKey=false;
        AbstractRoom.blizzardPotionMod=0;
        EventRewardsProbe.upgradedChance().setFloat(null,AbstractDungeon.actNum==1?0f:(AbstractDungeon.actNum==2?.125f:.25f));
        resetRandomInputs(q);
    }

    static void resetRandomInputs(JsonObject q) throws Exception {
        for (String name : STREAMS) AbstractDungeon.class.getField(name).set(null,new Random(Settings.seed));
        if (q.has("pool_overrides")) for (Map.Entry<String,JsonElement> entry : q.getAsJsonObject("pool_overrides").entrySet()) {
            String name=entry.getKey();
            if (!name.equals("common") && !name.equals("uncommon") && !name.equals("rare")) throw new IllegalArgumentException("unsupported fixture pool");
            ArrayList<String> values=new ArrayList<String>();
            for (JsonElement value : entry.getValue().getAsJsonArray()) {
                String id=value.getAsString(); AbstractRelic relic=RelicLibrary.getRelic(id);
                if (relic==null || !relic.tier.toString().equalsIgnoreCase(name)) throw new IllegalArgumentException("fixture tier differs: "+id);
                values.add(id);
            }
            @SuppressWarnings("unchecked") ArrayList<String> pool=(ArrayList<String>)AbstractDungeon.class.getField(name+"RelicPool").get(null);
            pool.clear(); pool.addAll(values);
        }
    }

    public static JsonObject start(JsonObject q) throws Exception {
        initialize(q);
        JsonObject out=new JsonObject(); out.add("initial",state()); out.add("pools",OutsideProbe.pools());
        TreasureRoom room=new TreasureRoom(); AbstractDungeon.currMapNode.room=room; room.onPlayerEntry(); RuleProbe.flush();
        out.add("checkpoint",snapshot()); return out;
    }
}
