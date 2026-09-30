package spirelablogic;

import com.google.gson.*;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.core.Settings;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.events.AbstractEvent;
import com.megacrit.cardcrawl.helpers.RelicLibrary;
import com.megacrit.cardcrawl.random.Random;
import com.megacrit.cardcrawl.relics.AbstractRelic;

/** Sets the state before event construction. Player choices use normal commands. */
public final class EventEntryProbe {
    public static JsonObject start(JsonObject q) throws Exception {
        RuleProbe.base();
        Settings.seed = q.get("seed").getAsLong();
        AbstractDungeon.floorNum = q.get("floor").getAsInt();
        AbstractDungeon.actNum = q.get("act").getAsInt();
        if (q.has("deck")) {
            RuleProbe.p().masterDeck.clear();
            for (JsonElement value : q.getAsJsonArray("deck")) {
                JsonObject spec = value.getAsJsonObject();
                JsonObject cardSpec = new JsonObject();
                cardSpec.add("card", spec.get("id"));
                if (spec.has("upgrades")) cardSpec.add("upgrades", spec.get("upgrades"));
                AbstractCard card = AlignmentProbe.card(cardSpec);
                RuleProbe.p().masterDeck.addToTop(card);
            }
        }
        for (JsonElement value : q.getAsJsonArray("relics")) {
            String id = value.isJsonPrimitive() ? value.getAsString() : value.getAsJsonObject().get("id").getAsString();
            AbstractRelic relic = RelicLibrary.getRelic(id).makeCopy();
            RuleProbe.p().relics.add(relic);
            relic.onEquip();
            if (value.isJsonObject() && value.getAsJsonObject().has("counter"))
                relic.setCounter(value.getAsJsonObject().get("counter").getAsInt());
        }
        RuleProbe.p().maxHealth = q.get("max_hp").getAsInt();
        RuleProbe.p().currentHealth = q.get("hp").getAsInt();
        RuleProbe.p().isBloodied = RuleProbe.p().currentHealth <= RuleProbe.p().maxHealth / 2;
        RuleProbe.p().gold = q.get("gold").getAsInt();
        RuleProbe.p().potions.clear();
        RuleProbe.p().potionSlots = 2;
        for (int i = 0; i < 2; i++) RuleProbe.p().potions.add(new com.megacrit.cardcrawl.potions.PotionSlot(i));
        // These four streams are seeded at room transition in AbstractDungeon.
        for (String name : new String[]{"aiRng", "monsterHpRng", "shuffleRng", "cardRandomRng"})
            AbstractDungeon.class.getField(name).set(null, new Random(Settings.seed + AbstractDungeon.floorNum));
        for (String name : new String[]{"potionRng", "relicRng", "cardRng", "merchantRng"})
            AbstractDungeon.class.getField(name).set(null, new Random(Settings.seed));
        AbstractDungeon.miscRng = new Random(q.get("misc_seed").getAsLong());
        JsonObject result = new JsonObject();
        result.add("initial_rng", ParityAudit.rngs());
        result.add("initial_outside", OutsideProbe.snapshot());
        result.add("pools", OutsideProbe.pools());
        AbstractEvent event = RuleProbe.event(q.get("id").getAsString());
        event.onEnterRoom();
        RuleProbe.flush();
        result.add("event_view", AlignmentProbe.view());
        return result;
    }
}
