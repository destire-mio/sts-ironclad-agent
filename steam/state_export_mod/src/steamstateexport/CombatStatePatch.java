package steamstateexport;

import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePostfixPatch;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.random.Random;
import com.megacrit.cardcrawl.cards.CardQueueItem;
import com.megacrit.cardcrawl.actions.GameActionManager;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.monsters.AbstractMonster;
import com.megacrit.cardcrawl.monsters.EnemyMoveInfo;
import communicationmod.CommandExecutor;
import communicationmod.GameStateConverter;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Collections;
import java.util.concurrent.atomic.AtomicLong;
import java.lang.reflect.Field;

@SpirePatch(clz = GameStateConverter.class, method = "getCombatState")
public class CombatStatePatch {
    // The installed BaseMod patch and the original Collections path use
    // different random sources. Observe the profile and raw shared state;
    // never instantiate or reseed the game's Random while exporting it.
    public static HashMap<String, Object> endTurnShuffleState() {
        HashMap<String, Object> state = new HashMap<>();
        try {
            boolean consistent = false;
            ClassLoader loader = CombatStatePatch.class.getClassLoader();
            try {
                Class<?> base = Class.forName("basemod.BaseMod", false, loader);
                Class.forName("basemod.patches.com.megacrit.cardcrawl.actions.common.DiscardAtEndOfTurnAction.ConsistentEtherealPatch", false, loader);
                consistent = base.getField("fixesEnabled").getBoolean(null);
            } catch (ClassNotFoundException absent) { }
            state.put("mode", consistent ? "basemod_seeded" : "java_shared");
            Field randomField = Collections.class.getDeclaredField("r");
            randomField.setAccessible(true);
            Object random = randomField.get(null);
            state.put("shared_rng_initialized", random != null);
            if (random != null) {
                Field seed = java.util.Random.class.getDeclaredField("seed");
                seed.setAccessible(true);
                state.put("shared_seed48", ((AtomicLong) seed.get(random)).get());
            }
        } catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
        return state;
    }

    private static HashMap<String, Object> rng(Random rng) {
        HashMap<String, Object> state = new HashMap<>();
        state.put("counter", rng.counter);
        state.put("seed0", Long.toUnsignedString(rng.random.getState(0)));
        state.put("seed1", Long.toUnsignedString(rng.random.getState(1)));
        return state;
    }

    @SpirePostfixPatch
    public static HashMap<String, Object> postfix(HashMap<String, Object> result) {
        HashMap<String, Object> rngs = new HashMap<>();
        rngs.put("ai", rng(AbstractDungeon.aiRng));
        rngs.put("card_random", rng(AbstractDungeon.cardRandomRng));
        rngs.put("misc", rng(AbstractDungeon.miscRng));
        rngs.put("monster_hp", rng(AbstractDungeon.monsterHpRng));
        rngs.put("potion", rng(AbstractDungeon.potionRng));
        rngs.put("shuffle", rng(AbstractDungeon.shuffleRng));
        result.put("rngs", rngs);
        result.put("end_turn_shuffle", endTurnShuffleState());
        result.put("frame_delta_seconds", com.badlogic.gdx.Gdx.graphics.getDeltaTime());
        result.put("energy_per_turn", AbstractDungeon.player.energy.energy);
        result.put("card_draw_per_turn", AbstractDungeon.player.gameHandSize);
        result.put("is_bloodied", AbstractDungeon.player.isBloodied);
        result.put("cards_discarded_this_turn", GameActionManager.totalDiscardedThisTurn);
        int attacks = 0, skills = 0;
        for (AbstractCard card : AbstractDungeon.actionManager.cardsPlayedThisTurn) {
            if (card.type == AbstractCard.CardType.ATTACK) attacks++;
            if (card.type == AbstractCard.CardType.SKILL) skills++;
        }
        result.put("cards_played_this_turn", AbstractDungeon.actionManager.cardsPlayedThisTurn.size());
        result.put("attacks_played_this_turn", attacks);
        result.put("skills_played_this_turn", skills);
        int facing = -1;
        for (int i = 0; i < AbstractDungeon.getCurrRoom().monsters.monsters.size(); i++) {
            AbstractMonster monster = AbstractDungeon.getCurrRoom().monsters.monsters.get(i);
            if (!monster.isDeadOrEscaped() && (monster.drawX < AbstractDungeon.player.drawX) == AbstractDungeon.player.flipHorizontal) facing = i;
        }
        result.put("facing_monster_index", facing);
        Map<String, Object> relicState = new HashMap<>();
        for (com.megacrit.cardcrawl.relics.AbstractRelic relic : AbstractDungeon.player.relics) {
            if (relic.relicId.equals("Centennial Puzzle")) {
                try {
                    Field field = relic.getClass().getDeclaredField("usedThisCombat");
                    field.setAccessible(true);
                    relicState.put("centennial_puzzle_used", field.getBoolean(null));
                } catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
            }
            if (relic.relicId.equals("Red Skull")) {
                try {
                    Field field = relic.getClass().getDeclaredField("isActive");
                    field.setAccessible(true);
                    relicState.put("red_skull_active", field.getBoolean(relic));
                } catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
            }
            if (relic.relicId.equals("Necronomicon")) relicState.put("necronomicon_used", !relic.checkTrigger());
            if (relic.relicId.equals("OrangePellets")) {
                int mask = 0;
                String[] types = {"ATTACK", "SKILL", "POWER"};
                for (int bit = 0; bit < types.length; bit++) {
                    try { Field field = relic.getClass().getDeclaredField(types[bit]); field.setAccessible(true); if (field.getBoolean(null)) mask |= 1 << bit; }
                    catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
                }
                relicState.put("orange_pellets_mask", mask);
            }
        }
        result.put("relic_combat_state", relicState);
        List<Map<String, Object>> rows = (List<Map<String, Object>>) result.get("monsters");
        String[] fields = {"dmgThreshold", "isOpen", "thornsCount", "usedMegaDebuff", "stolenGold", "orbActiveCount", "numTurns", "currentCharge", "debuffTurnCount", "isOut", "biteDamage", "nipDmg", "stabCount", "idleCount", "asleep", "usedEntangle", "forgeTimes", "thresholdReached", "usedHaste", "usedStasis", "scytheCooldown"};
        for (int i = 0; i < rows.size(); i++) {
            AbstractMonster monster = AbstractDungeon.getCurrRoom().monsters.monsters.get(i);
            // CommunicationMod hides these fields with Runic Dome. The live
            // search contract includes internal state, regardless of UI intent.
            try {
                Field field = AbstractMonster.class.getDeclaredField("move");
                field.setAccessible(true);
                EnemyMoveInfo move = (EnemyMoveInfo) field.get(monster);
                Map<String, Object> row = rows.get(i);
                if (move != null) {
                    row.put("move_id", move.nextMove);
                    row.put("move_base_damage", move.baseDamage);
                    row.put("move_adjusted_damage", move.baseDamage > 0 ? monster.getIntentDmg() : move.baseDamage);
                    row.put("move_hits", move.isMultiDamage ? move.multiplier : 1);
                }
                row.put("move_history", new java.util.ArrayList<Byte>(monster.moveHistory));
                int count = monster.moveHistory.size();
                row.put("last_move_id", count >= 2 ? monster.moveHistory.get(count - 2) : -1);
                row.put("second_last_move_id", count >= 3 ? monster.moveHistory.get(count - 3) : -1);
            } catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
            Map<String, Object> internal = new HashMap<>();
            for (String name : fields) {
                try { Field field = monster.getClass().getDeclaredField(name); field.setAccessible(true); internal.put(name, field.get(monster)); }
                catch (NoSuchFieldException ignored) { }
                catch (IllegalAccessException error) { throw new IllegalStateException(error); }
            }
            rows.get(i).put("internal", internal);
            if (monster.id.equals("GremlinLeader")) {
                try {
                    Field field = monster.getClass().getDeclaredField("gremlins"); field.setAccessible(true);
                    AbstractMonster[] minions = (AbstractMonster[]) field.get(monster);
                    for (int slot = 0; slot < minions.length; slot++) {
                        int index = AbstractDungeon.getCurrRoom().monsters.monsters.indexOf(minions[slot]);
                        if (index >= 0) rows.get(index).put("gremlin_slot", slot);
                    }
                } catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
            }
            if (monster.id.equals("TheCollector")) {
                try {
                    Field field = monster.getClass().getDeclaredField("enemySlots"); field.setAccessible(true);
                    Map<Integer, AbstractMonster> minions = (Map<Integer, AbstractMonster>) field.get(monster);
                    for (Map.Entry<Integer, AbstractMonster> entry : minions.entrySet()) {
                        int index = AbstractDungeon.getCurrRoom().monsters.monsters.indexOf(entry.getValue());
                        if (index >= 0) rows.get(index).put("torch_slot", entry.getKey());
                    }
                } catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
            }
            if (monster.id.equals("Reptomancer")) {
                try {
                    Field field = monster.getClass().getDeclaredField("daggers"); field.setAccessible(true);
                    AbstractMonster[] daggers = (AbstractMonster[]) field.get(monster);
                    for (int slot = 0; slot < daggers.length; slot++) {
                        int index = AbstractDungeon.getCurrRoom().monsters.monsters.indexOf(daggers[slot]);
                        if (index >= 0) rows.get(index).put("dagger_slot", slot);
                    }
                } catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
            }
        }
        return result;
    }

    // CommunicationMod queues a card directly, bypassing the facing update in
    // AbstractPlayer.playCard. Reproduce that input behavior after validation.
    @SpirePatch(clz = CommandExecutor.class, method = "executePlayCommand")
    public static class TargetFacing {
        @SpirePostfixPatch
        public static void postfix() {
            if (!AbstractDungeon.player.hasPower("Surrounded") || AbstractDungeon.actionManager.cardQueue.isEmpty()) return;
            CardQueueItem item = AbstractDungeon.actionManager.cardQueue.get(AbstractDungeon.actionManager.cardQueue.size() - 1);
            if (item.monster != null) AbstractDungeon.player.flipHorizontal = item.monster.drawX < AbstractDungeon.player.drawX;
        }
    }
}
