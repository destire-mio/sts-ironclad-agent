package steamstateexport;

import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePostfixPatch;
import communicationmod.GameStateConverter;
import java.util.HashMap;

/** Export at every in-game decision, including Neow, map and reward screens. */
@SpirePatch(clz = GameStateConverter.class, method = "getGameState")
public class GameRngPatch {
    @SpirePostfixPatch
    public static HashMap<String, Object> postfix(HashMap<String, Object> result) {
        // combat_state.rngs remains the six-stream legacy BattleContext schema.
        result.put("full_rng_state", FullRngState.capture());
        return result;
    }
}
