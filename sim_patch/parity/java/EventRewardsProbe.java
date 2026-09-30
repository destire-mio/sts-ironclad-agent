package spirelablogic;

import com.google.gson.*;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.rooms.AbstractRoom;
import com.megacrit.cardcrawl.relics.AbstractRelic;
import com.megacrit.cardcrawl.helpers.RelicLibrary;
import com.megacrit.cardcrawl.rewards.RewardItem;
import com.megacrit.cardcrawl.cards.AbstractCard;
import java.util.ArrayList;
import java.util.Map;
import java.lang.reflect.Field;

/** Initial reward inputs and read-only observations; ordinary commands run the game. */
public final class EventRewardsProbe {
    static Field upgradedChance() throws Exception {
        Field f = AbstractDungeon.class.getDeclaredField("cardUpgradedChance");
        f.setAccessible(true);
        return f;
    }
    public static JsonObject rewardState() throws Exception {
        JsonObject out = new JsonObject();
        out.addProperty("potion_chance", AbstractRoom.blizzardPotionMod);
        out.addProperty("card_rarity_factor", AbstractDungeon.cardBlizzRandomizer);
        out.addProperty("card_upgraded_chance", upgradedChance().getFloat(null));
        return out;
    }
    public static JsonObject snapshot() throws Exception {
        JsonObject out = RelicAcquireProbe.snapshot();
        out.add("reward_state", rewardState());
        JsonObject selection = new JsonObject();
        JsonObject outside = out.getAsJsonObject("outside");
        selection.addProperty("selecting", AbstractDungeon.screen == AbstractDungeon.CurrentScreen.GRID);
        selection.add("count", outside.get("selection_count"));
        selection.add("choices", outside.get("selection"));
        JsonArray pending = new JsonArray();
        if (AbstractDungeon.screen == AbstractDungeon.CurrentScreen.GRID ||
            AbstractDungeon.screen == AbstractDungeon.CurrentScreen.COMBAT_REWARD ||
            AbstractDungeon.screen == AbstractDungeon.CurrentScreen.CARD_REWARD) {
            for (RewardItem reward : AbstractDungeon.combatRewardScreen.rewards) {
                JsonObject item = new JsonObject(); item.addProperty("type", reward.type.toString());
                if (reward.type == RewardItem.RewardType.GOLD) item.addProperty("gold", reward.goldAmt + reward.bonusGold);
                else if (reward.type == RewardItem.RewardType.RELIC) item.addProperty("id", reward.relic.relicId);
                else if (reward.type == RewardItem.RewardType.POTION) item.addProperty("id", reward.potion.ID);
                else if (reward.type == RewardItem.RewardType.CARD) {
                    JsonArray cards = new JsonArray();
                    for (AbstractCard card : reward.cards) cards.add(OutsideProbe.card(card));
                    item.add("cards", cards);
                }
                pending.add(item);
            }
        }
        selection.add("pending_rewards", pending);
        out.add("selection_state", selection);
        return out;
    }
    public static JsonObject start(JsonObject q) throws Exception {
        int act = q.get("act").getAsInt();
        AbstractRoom.blizzardPotionMod = 0;
        upgradedChance().setFloat(null, act == 1 ? 0f : (act == 2 ? .125f : .25f));
        if (q.has("pool_overrides")) {
            for (Map.Entry<String, JsonElement> entry : q.getAsJsonObject("pool_overrides").entrySet()) {
                String name = entry.getKey();
                if (!name.equals("common") && !name.equals("uncommon") && !name.equals("rare"))
                    throw new IllegalArgumentException("unsupported fixture relic pool: " + name);
                ArrayList<String> values = new ArrayList<String>();
                for (JsonElement value : entry.getValue().getAsJsonArray()) {
                    String id = value.getAsString(); AbstractRelic relic = RelicLibrary.getRelic(id);
                    if (relic == null || !relic.tier.toString().equalsIgnoreCase(name))
                        throw new IllegalArgumentException("relic fixture tier differs: " + id);
                    values.add(id);
                }
                @SuppressWarnings("unchecked")
                ArrayList<String> pool = (ArrayList<String>)AbstractDungeon.class.getField(name + "RelicPool").get(null);
                pool.clear(); pool.addAll(values);
            }
        }
        JsonObject out = EventEntryProbe.start(q);
        out.add("reward_state", rewardState());
        return out;
    }
}
