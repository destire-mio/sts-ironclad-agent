package spirelablogic;

import com.badlogic.gdx.math.MathUtils;
import com.badlogic.gdx.math.RandomXS128;
import com.google.gson.*;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.monsters.AbstractMonster;
import com.megacrit.cardcrawl.potions.AbstractPotion;
import com.megacrit.cardcrawl.potions.PotionSlot;
import com.megacrit.cardcrawl.random.Random;
import com.megacrit.cardcrawl.rooms.AbstractRoom;
import communicationmod.CommandExecutor;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/** Additional observation for disposable test instances, never game rules. */
public final class ParityAudit {
    static JsonObject scalars(Object object) throws Exception {
        JsonObject result = new JsonObject();
        if (object == null) return result;
        for (Class<?> type = object.getClass(); type != null; type = type.getSuperclass()) {
            for (Field field : type.getDeclaredFields()) {
                boolean puzzleState = type.getName().equals("com.megacrit.cardcrawl.relics.CentennialPuzzle")
                    && field.getName().equals("usedThisCombat");
                if ((Modifier.isStatic(field.getModifiers()) && !puzzleState) || field.isSynthetic()) continue;
                Class<?> valueType = field.getType();
                if (!valueType.isPrimitive() && !valueType.isEnum()) continue;
                field.setAccessible(true);
                result.add(type.getSimpleName() + "." + field.getName(), AlignmentProbe.JSON.toJsonTree(field.get(object)));
            }
        }
        return result;
    }

    static JsonArray objects(Iterable<?> values) throws Exception {
        JsonArray result = new JsonArray();
        for (Object value : values) {
            JsonObject row = new JsonObject();
            row.addProperty("class", value.getClass().getName());
            row.add("fields", scalars(value));
            result.add(row);
        }
        return result;
    }

    static JsonObject rngs() throws Exception {
        JsonObject result = new JsonObject();
        for (Field field : AbstractDungeon.class.getFields()) {
            if (!Modifier.isStatic(field.getModifiers()) || field.getType() != Random.class) continue;
            Random rng = (Random)field.get(null);
            if (rng == null) continue;
            JsonObject value = new JsonObject();
            value.addProperty("counter", rng.counter);
            value.addProperty("seed0", rng.random.getState(0));
            value.addProperty("seed1", rng.random.getState(1));
            result.add(field.getName(), value);
        }
        if (MathUtils.random instanceof RandomXS128) {
            RandomXS128 rng = (RandomXS128)MathUtils.random;
            JsonObject value = new JsonObject();
            value.addProperty("seed0", rng.getState(0));
            value.addProperty("seed1", rng.getState(1));
            result.add("MathUtils", value);
        }
        // Vanilla DiscardAtEndOfTurnAction uses this RNG. BaseMod's optional
        // ConsistentEtherealPatch substitutes a local seed-derived Random.
        // Read the shared 48-bit state without constructing or reseeding it.
        Field shuffleField = Collections.class.getDeclaredField("r");
        shuffleField.setAccessible(true);
        Object shuffleRandom = shuffleField.get(null);
        JsonObject shuffle = new JsonObject();
        shuffle.addProperty("initialized", shuffleRandom != null);
        if (shuffleRandom != null) {
            Field seedField = java.util.Random.class.getDeclaredField("seed");
            seedField.setAccessible(true);
            shuffle.addProperty("seed48", ((AtomicLong)seedField.get(shuffleRandom)).get());
        }
        result.add("java_util_Collections", shuffle);
        return result;
    }

    static JsonObject rawState() throws Exception {
        JsonObject raw = new JsonObject();
        raw.add("rng", rngs());
        raw.add("player", scalars(AbstractDungeon.player));
        raw.addProperty("player_energy", com.megacrit.cardcrawl.ui.panels.EnergyPanel.totalCount);
        raw.add("powers", objects(AbstractDungeon.player.powers));
        raw.add("relics", objects(AbstractDungeon.player.relics));
        raw.add("hand", objects(AbstractDungeon.player.hand.group));
        raw.add("draw_pile", objects(AbstractDungeon.player.drawPile.group));
        raw.add("discard_pile", objects(AbstractDungeon.player.discardPile.group));
        raw.add("exhaust_pile", objects(AbstractDungeon.player.exhaustPile.group));
        if (AbstractDungeon.getCurrRoom().monsters != null)
            raw.add("monsters", objects(AbstractDungeon.getCurrRoom().monsters.monsters));
        raw.add("actions", objects(AbstractDungeon.actionManager.actions));
        raw.add("pre_turn_actions", objects(AbstractDungeon.actionManager.preTurnActions));
        raw.add("action_manager", scalars(AbstractDungeon.actionManager));
        return raw;
    }

    static boolean targetable(AbstractMonster monster) {
        return monster.currentHealth > 0 && !monster.halfDead && !monster.isDeadOrEscaped() && !monster.isDying;
    }

    public static JsonObject snapshot() throws Exception {
        JsonObject result = new JsonObject();
        result.addProperty("schema_version", 1);
        JsonObject runtime = new JsonObject();
        runtime.addProperty("basemod_fixes_enabled", basemod.BaseMod.fixesEnabled);
        runtime.addProperty("game_seed", com.megacrit.cardcrawl.core.Settings.seed);
        runtime.addProperty("floor", AbstractDungeon.floorNum);
        runtime.addProperty("turn", com.megacrit.cardcrawl.actions.GameActionManager.turn);
        runtime.addProperty("ethereal_shuffle_mode", (String)steamstateexport.CombatStatePatch.endTurnShuffleState().get("mode"));
        result.add("runtime", runtime);
        JsonObject before = rawState();
        result.add("raw_state", before);
        JsonArray actions = new JsonArray();
        Collection<String> commands = CommandExecutor.getAvailableCommands();
        boolean normal = AbstractDungeon.getCurrRoom().phase == AbstractRoom.RoomPhase.COMBAT
            && !AbstractDungeon.isScreenUp && commands.contains("end");
        if (normal) {
            if (commands.contains("play")) {
                int index = 0;
                for (AbstractCard card : AbstractDungeon.player.hand.group) {
                    index++;
                    if (card.target == AbstractCard.CardTarget.ENEMY || card.target == AbstractCard.CardTarget.SELF_AND_ENEMY) {
                        int target = 0;
                        for (AbstractMonster monster : AbstractDungeon.getCurrRoom().monsters.monsters) {
                            if (targetable(monster) && card.canUse(AbstractDungeon.player, monster))
                                actions.add(new JsonPrimitive("play " + index + " " + target));
                            target++;
                        }
                    } else if (card.canUse(AbstractDungeon.player, null)) {
                        actions.add(new JsonPrimitive("play " + index));
                    }
                }
            }
            if (commands.contains("potion")) {
                int slot = 0;
                for (AbstractPotion potion : AbstractDungeon.player.potions) {
                    if (!(potion instanceof PotionSlot)) {
                        if (potion.canDiscard()) actions.add(new JsonPrimitive("potion discard " + slot));
                        if (potion.canUse()) {
                            if (potion.targetRequired) {
                                int target = 0;
                                for (AbstractMonster monster : AbstractDungeon.getCurrRoom().monsters.monsters) {
                                    if (targetable(monster)) actions.add(new JsonPrimitive("potion use " + slot + " " + target));
                                    target++;
                                }
                            } else actions.add(new JsonPrimitive("potion use " + slot));
                        }
                    }
                    slot++;
                }
            }
            actions.add(new JsonPrimitive("end"));
        }
        JsonObject after = rawState();
        result.addProperty("observer_state_unchanged", before.equals(after));
        result.addProperty("legal_complete", normal && before.equals(after));
        result.add("legal_actions", actions);
        if (!before.equals(after)) result.add("after_legality_observation", after);
        result.addProperty("legal_scope", "normal combat card/target/potion/end inputs; UI keys/clicks excluded");
        return result;
    }
}
