package steamstateexport;

import com.badlogic.gdx.math.MathUtils;
import com.badlogic.gdx.math.RandomXS128;
import com.megacrit.cardcrawl.actions.GameActionManager;
import com.megacrit.cardcrawl.core.Settings;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.neow.NeowEvent;
import com.megacrit.cardcrawl.random.Random;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.atomic.AtomicLong;

/** Read-only RNG export. Never initializes, copies, samples or reseeds a live RNG. */
public final class FullRngState {
    private FullRngState() { }

    private static Object privateField(Class<?> owner, String name, Object instance)
            throws ReflectiveOperationException {
        Field field = owner.getDeclaredField(name);
        field.setAccessible(true);
        return field.get(instance);
    }

    private static Map<String, Object> state(java.util.Random random)
            throws ReflectiveOperationException {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("initialized", random != null);
        if (random == null) return result;
        result.put("class", random.getClass().getName());
        // Unknown subclasses can own additional state; do not silently treat
        // them as java.util.Random or declare an incomplete export complete.
        if (random.getClass() == RandomXS128.class) {
            RandomXS128 xs = (RandomXS128) random;
            result.put("algorithm", "xorshift128plus");
            result.put("seed0", Long.toUnsignedString(xs.getState(0)));
            result.put("seed1", Long.toUnsignedString(xs.getState(1)));
        } else if (random.getClass() == java.util.Random.class) {
            result.put("algorithm", "java_lcg48");
            result.put("seed48", Long.toString(((AtomicLong)
                    privateField(java.util.Random.class, "seed", random)).get()));
        } else {
            throw new IllegalStateException("Unsupported RNG class: " + random.getClass().getName());
        }
        // RandomXS128 inherits nextGaussian() and its cached second sample.
        // State words alone do not describe the next Gaussian result.
        Map<String, Object> gaussian = new LinkedHashMap<>();
        gaussian.put("has_cached", privateField(java.util.Random.class, "haveNextNextGaussian", random));
        double cached = (Double) privateField(java.util.Random.class, "nextNextGaussian", random);
        gaussian.put("cached_double_bits", Long.toUnsignedString(Double.doubleToRawLongBits(cached)));
        result.put("gaussian", gaussian);
        return result;
    }

    private static Map<String, Object> state(Random random) throws ReflectiveOperationException {
        if (random == null) return state((java.util.Random) null);
        if (random.getClass() != Random.class || random.random == null)
            throw new IllegalStateException("Unsupported or corrupt game RNG wrapper");
        Map<String, Object> result = state(random.random);
        result.put("counter", random.counter);
        return result;
    }

    public static Map<String, Object> capture() {
        Map<String, Object> result = new LinkedHashMap<>();
        Map<String, Object> streams = new TreeMap<>();
        result.put("schema_version", 1);
        result.put("scope", "natural-run persistent RNGs; no daily-mode or third-party-mod RNGs");
        result.put("run_seed", Settings.seed == null ? null : Long.toString(Settings.seed));
        result.put("act", AbstractDungeon.actNum);
        result.put("floor", AbstractDungeon.floorNum);
        result.put("turn", GameActionManager.turn);
        result.put("streams", streams);
        result.put("complete", false);
        try {
            for (Field field : AbstractDungeon.class.getFields()) {
                if (Modifier.isStatic(field.getModifiers()) && field.getType() == Random.class)
                    streams.put(field.getName(), state((Random) field.get(null)));
            }
            streams.put("NeowEvent.rng", state(NeowEvent.rng));
            streams.put("MathUtils.random", state(MathUtils.random));
            streams.put("Collections.r", state((java.util.Random)
                    privateField(Collections.class, "r", null)));
            result.put("complete", true);
        } catch (ReflectiveOperationException | RuntimeException error) {
            // Preserve a playable game and report an explicit contract failure.
            // Consumers must reject complete=false, including partial streams.
            result.put("error", error.toString());
        }
        return result;
    }
}
