package steamstateexport;

import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePostfixPatch;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.random.Random;
import com.megacrit.cardcrawl.cards.CardQueueItem;
import com.megacrit.cardcrawl.actions.GameActionManager;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.monsters.AbstractMonster;
import communicationmod.CommandExecutor;
import communicationmod.GameStateConverter;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.lang.reflect.Field;

@SpirePatch(clz = GameStateConverter.class, method = "getCombatState")
public class CombatStatePatch {
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
        result.put("frame_delta_seconds", com.badlogic.gdx.Gdx.graphics.getDeltaTime());
        result.put("energy_per_turn", AbstractDungeon.player.energy.energy);
        result.put("card_draw_per_turn", AbstractDungeon.player.gameHandSize);
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
