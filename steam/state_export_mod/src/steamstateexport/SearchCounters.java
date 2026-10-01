package steamstateexport;

import com.evacipated.cardcrawl.modthespire.lib.*;
import com.megacrit.cardcrawl.characters.AbstractPlayer;
import communicationmod.CommandExecutor;
import com.megacrit.cardcrawl.ui.panels.EnergyPanel;
import java.util.ArrayDeque;

/** Observation only: no game state, action queue or RNG changes. */
public class SearchCounters {
    public static int cardsDrawn = 0, energyWasted = 0;
    private static final ArrayDeque<Integer> draws = new ArrayDeque<Integer>();

    @SpirePatch(clz=AbstractPlayer.class, method="preBattlePrep")
    public static class Reset {
        @SpirePrefixPatch public static void before() {
            cardsDrawn=0; energyWasted=0; draws.clear();
        }
    }
    // draw() delegates to draw(int); count only cards that leave the draw pile.
    @SpirePatch(clz=AbstractPlayer.class, method="draw", paramtypez={int.class})
    public static class Draw {
        @SpirePrefixPatch public static void before(AbstractPlayer __instance) {
            draws.push(__instance.drawPile.size());
        }
        @SpirePostfixPatch public static void after(AbstractPlayer __instance) {
            cardsDrawn += draws.pop()-__instance.drawPile.size();
        }
    }
    // The production statistic counts explicit END_TURN actions only.
    // Time Warp calls callEndTurnEarlySequence and deliberately contributes zero.
    @SpirePatch(clz=CommandExecutor.class, method="executeEndCommand")
    public static class EndTurn {
        @SpirePrefixPatch public static void before() {
            energyWasted += EnergyPanel.totalCount;
        }
    }
}
