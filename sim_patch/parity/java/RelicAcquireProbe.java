package spirelablogic;

import com.google.gson.*;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.core.Settings;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.events.AbstractEvent;
import com.megacrit.cardcrawl.helpers.RelicLibrary;
import com.megacrit.cardcrawl.random.Random;
import com.megacrit.cardcrawl.relics.AbstractRelic;
import com.megacrit.cardcrawl.saveAndContinue.SaveFile;

/** Controlled initial inputs, original acquisition methods, then ordinary combat commands. */
public final class RelicAcquireProbe {
    public static JsonObject snapshot() throws Exception {
        JsonObject out = new JsonObject();
        out.add("view", AlignmentProbe.view());
        out.add("outside", OutsideProbe.snapshot());
        if (AbstractDungeon.getCurrRoom().phase != com.megacrit.cardcrawl.rooms.AbstractRoom.RoomPhase.COMBAT) {
            // Read the game's actual save constructor; this does not write or reload a save.
            SaveFile save = new SaveFile(SaveFile.SaveType.POST_COMBAT);
            out.add("save", AlignmentProbe.JSON.toJsonTree(save));
        }
        return out;
    }

    public static JsonObject start(JsonObject q) throws Exception {
        RuleProbe.base();
        Settings.seed = q.get("seed").getAsLong();
        AbstractDungeon.floorNum = q.get("floor").getAsInt();
        AbstractDungeon.actNum = 2;
        RuleProbe.p().currentHealth = q.get("hp").getAsInt();
        RuleProbe.p().maxHealth = q.get("max_hp").getAsInt();
        RuleProbe.p().isBloodied = RuleProbe.p().currentHealth <= RuleProbe.p().maxHealth / 2;
        RuleProbe.p().gold = 1000;
        RuleProbe.p().masterDeck.clear();
        for (JsonElement value : q.getAsJsonArray("deck")) {
            JsonObject c = value.getAsJsonObject();
            JsonObject request = new JsonObject(); request.add("card", c.get("id")); request.add("upgrades", c.get("upgrades"));
            AbstractCard card = AlignmentProbe.card(request);
            card.inBottleFlame = c.has("bottled") && c.get("bottled").getAsBoolean();
            RuleProbe.p().masterDeck.addToTop(card);
        }
        if (q.get("drop_starter").getAsBoolean()) RuleProbe.p().loseRelic("Burning Blood");
        if (q.get("support_neow").getAsBoolean()) RuleProbe.equip("NeowsBlessing");
        RuleProbe.p().potions.clear(); RuleProbe.p().potionSlots = 2;
        for (int i=0;i<2;i++) RuleProbe.p().potions.add(new com.megacrit.cardcrawl.potions.PotionSlot(i));
        for (String name : new String[]{"aiRng", "monsterHpRng", "shuffleRng", "cardRandomRng", "miscRng"})
            AbstractDungeon.class.getField(name).set(null, new Random(Settings.seed + AbstractDungeon.floorNum));
        for (String name : new String[]{"potionRng", "relicRng", "cardRng"})
            AbstractDungeon.class.getField(name).set(null, new Random(Settings.seed));
        JsonObject result = new JsonObject();
        result.add("initial", snapshot()); result.add("pools", OutsideProbe.pools());
        JsonArray stages = new JsonArray();
        for (JsonElement value : q.getAsJsonArray("acquire")) {
            String id = value.getAsString();
            AbstractRelic relic;
            if (id.equals("Black Blood") && RuleProbe.p().hasRelic("Burning Blood")) {
                int slot = RuleProbe.p().relics.indexOf(RuleProbe.p().getRelic("Burning Blood"));
                relic = RelicLibrary.getRelic(id).makeCopy(); relic.instantObtain(RuleProbe.p(), slot, true);
            } else relic = RuleProbe.equip(id);
            RuleProbe.flush();
            if (AbstractDungeon.screen == AbstractDungeon.CurrentScreen.GRID && AbstractDungeon.gridSelectScreen.isJustForConfirming) {
                AbstractDungeon.gridSelectScreen.confirmButton.hb.clicked = true;
                AbstractDungeon.gridSelectScreen.update(); RuleProbe.flush();
            }
            if (AbstractDungeon.screen != AbstractDungeon.CurrentScreen.NONE)
                throw new IllegalStateException("acquisition requires unsupported UI: " + id);
            stages.add(snapshot());
        }
        if (q.has("altar") && q.get("altar").getAsBoolean()) {
            AbstractEvent altar = RuleProbe.event("Forgotten Altar");
            RuleProbe.choose(altar, 0); stages.add(snapshot());
        }
        result.add("stages", stages);
        if (q.get("fight").getAsBoolean()) {
            AbstractEvent event = RuleProbe.event("Colosseum");
            RuleProbe.choose(event, 0); RuleProbe.choose(event, 0);
            result.add("opening", snapshot());
        }
        return result;
    }
}
