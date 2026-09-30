package spirelablogic;

import com.google.gson.*;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.core.Settings;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.events.AbstractEvent;
import com.megacrit.cardcrawl.helpers.RelicLibrary;
import com.megacrit.cardcrawl.random.Random;
import com.megacrit.cardcrawl.relics.AbstractRelic;

/** Controlled room entry only. Subsequent fights use normal player commands. */
public final class ColosseumProbe {
    public static JsonObject start(JsonObject q) throws Exception {
        RuleProbe.base();
        Settings.seed = q.get("seed").getAsLong();
        AbstractDungeon.floorNum = q.get("floor").getAsInt();
        AbstractDungeon.actNum = 2;
        RuleProbe.p().currentHealth = q.has("hp") ? q.get("hp").getAsInt() : 60;
        RuleProbe.p().maxHealth = q.has("max_hp") ? q.get("max_hp").getAsInt() : 80;
        RuleProbe.p().gold = 1000;
        RuleProbe.p().masterDeck.clear();
        for (JsonElement value : q.getAsJsonArray("deck")) {
            JsonObject spec = value.getAsJsonObject();
            JsonObject cardSpec = new JsonObject();
            cardSpec.add("card", spec.get("id"));
            cardSpec.add("upgrades", spec.get("upgrades"));
            AbstractCard card = AlignmentProbe.card(cardSpec);
            if (spec.has("bottled") && spec.get("bottled").getAsBoolean())
                card.inBottleFlame = true;
            RuleProbe.p().masterDeck.addToBottom(card);
        }
        RuleProbe.p().relics.clear();
        for (JsonElement value : q.getAsJsonArray("relics")) {
            JsonObject spec = value.getAsJsonObject();
            AbstractRelic relic = RelicLibrary.getRelic(spec.get("id").getAsString()).makeCopy();
            RuleProbe.p().relics.add(relic);
            relic.onEquip();
            relic.setCounter(spec.get("counter").getAsInt());
        }
        RuleProbe.p().potions.clear();
        RuleProbe.p().potionSlots = 2;
        for (int i = 0; i < 2; i++) RuleProbe.p().potions.add(new com.megacrit.cardcrawl.potions.PotionSlot(i));
        if (q.has("potions")) {
            int slot = 0;
            for (JsonElement id : q.getAsJsonArray("potions"))
                RuleProbe.p().obtainPotion(slot++, com.megacrit.cardcrawl.helpers.PotionHelper.getPotion(id.getAsString()));
        }
        for (String name : new String[]{"aiRng", "monsterHpRng", "shuffleRng", "cardRandomRng", "miscRng"})
            AbstractDungeon.class.getField(name).set(null, new Random(Settings.seed + AbstractDungeon.floorNum));
        JsonObject result = new JsonObject();
        result.add("initial_rng", ParityAudit.rngs());
        result.add("initial_outside", OutsideProbe.snapshot());
        result.add("pools", OutsideProbe.pools());
        JsonArray stages = new JsonArray();
        stages.add(OutsideProbe.snapshot());
        if (q.has("before_rooms")) for (JsonElement name : q.getAsJsonArray("before_rooms")) {
            com.megacrit.cardcrawl.rooms.AbstractRoom room;
            if (name.getAsString().equals("REST")) room = new com.megacrit.cardcrawl.rooms.RestRoom();
            else if (name.getAsString().equals("SHOP")) room = new com.megacrit.cardcrawl.rooms.ShopRoom();
            else throw new IllegalArgumentException("unsupported initial room callback");
            room.phase = com.megacrit.cardcrawl.rooms.AbstractRoom.RoomPhase.COMPLETE;
            AbstractDungeon.currMapNode.room = room;
            for (AbstractRelic relic : RuleProbe.p().relics) relic.onEnterRoom(room);
            if (room instanceof com.megacrit.cardcrawl.rooms.RestRoom)
                for (AbstractRelic relic : RuleProbe.p().relics) relic.onEnterRestRoom();
            for (AbstractRelic relic : RuleProbe.p().relics) relic.justEnteredRoom(room);
            stages.add(OutsideProbe.snapshot());
        }
        result.add("setup_stages", stages);
        AbstractEvent event = RuleProbe.event("Colosseum");
        RuleProbe.choose(event, 0);
        RuleProbe.choose(event, 0);
        result.add("view", AlignmentProbe.view());
        return result;
    }
}
