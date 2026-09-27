package spirelablogic;

import com.badlogic.gdx.math.MathUtils;
import com.badlogic.gdx.math.RandomXS128;
import com.google.gson.*;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.neow.NeowEvent;
import com.megacrit.cardcrawl.random.Random;
import steamstateexport.FullRngState;

import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/** Diagnostic only: verify exported states against future calls in the real JVM. */
public final class FullRngProbe {
    private static Field field(Class<?> owner, String name) throws Exception {
        Field field = owner.getDeclaredField(name);
        field.setAccessible(true);
        return field;
    }

    // Independent rollback data, never decoded from the exporter being tested.
    private static final class Saved {
        final java.util.Random random;
        final long a, b;
        final boolean gaussian;
        final double cached;
        Saved(java.util.Random random) throws Exception {
            this.random = random;
            if (random instanceof RandomXS128) {
                a = ((RandomXS128) random).getState(0);
                b = ((RandomXS128) random).getState(1);
            } else {
                a = ((AtomicLong) field(java.util.Random.class, "seed").get(random)).get();
                b = 0;
            }
            gaussian = field(java.util.Random.class, "haveNextNextGaussian").getBoolean(random);
            cached = field(java.util.Random.class, "nextNextGaussian").getDouble(random);
        }
        void restore() throws Exception {
            if (random instanceof RandomXS128) ((RandomXS128) random).setState(a, b);
            else ((AtomicLong) field(java.util.Random.class, "seed").get(random)).set(a);
            field(java.util.Random.class, "haveNextNextGaussian").setBoolean(random, gaussian);
            field(java.util.Random.class, "nextNextGaussian").setDouble(random, cached);
        }
    }

    private static java.util.Random decode(JsonObject data) throws Exception {
        java.util.Random result;
        if (data.get("algorithm").getAsString().equals("xorshift128plus")) {
            result = new RandomXS128(Long.parseUnsignedLong(data.get("seed0").getAsString()),
                    Long.parseUnsignedLong(data.get("seed1").getAsString()));
        } else if (data.get("algorithm").getAsString().equals("java_lcg48")) {
            result = new java.util.Random(0L);
            ((AtomicLong) field(java.util.Random.class, "seed").get(result))
                    .set(Long.parseLong(data.get("seed48").getAsString()));
        } else throw new IllegalArgumentException("unknown algorithm");
        JsonObject gaussian = data.getAsJsonObject("gaussian");
        field(java.util.Random.class, "haveNextNextGaussian").setBoolean(result,
                gaussian.get("has_cached").getAsBoolean());
        field(java.util.Random.class, "nextNextGaussian").setDouble(result,
                Double.longBitsToDouble(Long.parseUnsignedLong(gaussian.get("cached_double_bits").getAsString())));
        return result;
    }

    private static JsonArray samples(java.util.Random random) {
        JsonArray result = new JsonArray();
        for (int i = 0; i < 24; i++) {
            result.add(new JsonPrimitive(Long.toString(random.nextLong())));
            // Large bound exercises rejection, small bound resembles gameplay.
            result.add(new JsonPrimitive(random.nextInt(i % 2 == 0 ? 1073741825 : 73)));
            result.add(new JsonPrimitive(Integer.toUnsignedString(Float.floatToRawIntBits(random.nextFloat()))));
            result.add(new JsonPrimitive(random.nextBoolean()));
            result.add(new JsonPrimitive(Long.toUnsignedString(Double.doubleToRawLongBits(random.nextGaussian()))));
        }
        return result;
    }

    private static JsonObject one(String name, Random wrapper, java.util.Random live, JsonObject exported)
            throws Exception {
        JsonObject row = new JsonObject();
        row.addProperty("name", name);
        row.addProperty("initialized", live != null);
        if (live == null) {
            row.addProperty("matched", !exported.get("initialized").getAsBoolean());
            return row;
        }
        Saved saved = new Saved(live);
        int originalCounter = wrapper == null ? 0 : wrapper.counter;
        try {
            java.util.Random reconstructed = decode(exported);
            JsonArray expected = samples(reconstructed), actual = samples(live);
            row.add("expected", expected);
            row.add("actual", actual);
            boolean counterMatches = wrapper == null || exported.get("counter").getAsInt() == originalCounter;
            row.addProperty("matched", expected.equals(actual) && counterMatches);
            row.addProperty("counter_matched", counterMatches);
        } finally {
            saved.restore();
            if (wrapper != null) wrapper.counter = originalCounter;
        }
        return row;
    }

    public static JsonObject run() throws Exception {
        JsonObject before = AlignmentProbe.JSON.toJsonTree(FullRngState.capture()).getAsJsonObject();
        if (!before.get("complete").getAsBoolean()) throw new IllegalStateException(before.toString());
        JsonObject streams = before.getAsJsonObject("streams");
        JsonArray rows = new JsonArray();
        for (Field field : AbstractDungeon.class.getFields()) {
            if (Modifier.isStatic(field.getModifiers()) && field.getType() == Random.class) {
                Random rng = (Random) field.get(null);
                rows.add(one(field.getName(), rng, rng == null ? null : rng.random,
                        streams.getAsJsonObject(field.getName())));
            }
        }
        rows.add(one("NeowEvent.rng", NeowEvent.rng, NeowEvent.rng == null ? null : NeowEvent.rng.random,
                streams.getAsJsonObject("NeowEvent.rng")));
        rows.add(one("MathUtils.random", null, MathUtils.random, streams.getAsJsonObject("MathUtils.random")));
        rows.add(one("Collections.r", null, (java.util.Random) field(Collections.class, "r").get(null),
                streams.getAsJsonObject("Collections.r")));

        // Verify a pending Gaussian value too, not just the normal empty cache.
        java.util.Random math = MathUtils.random;
        Saved savedMath = new Saved(math);
        JsonObject cachedProbe;
        try {
            field(java.util.Random.class, "haveNextNextGaussian").setBoolean(math, false);
            math.nextGaussian();
            JsonObject state = AlignmentProbe.JSON.toJsonTree(FullRngState.capture()).getAsJsonObject();
            cachedProbe = one("MathUtils.random.cached_gaussian", null, math,
                    state.getAsJsonObject("streams").getAsJsonObject("MathUtils.random"));
        } finally { savedMath.restore(); }
        rows.add(cachedProbe);

        JsonObject after = AlignmentProbe.JSON.toJsonTree(FullRngState.capture()).getAsJsonObject();
        JsonObject result = new JsonObject();
        result.add("before", before);
        result.add("after", after);
        result.add("cases", rows);
        result.addProperty("persistent_rng_restored", before.equals(after));
        boolean matched = before.equals(after);
        for (JsonElement row : rows) matched &= row.getAsJsonObject().get("matched").getAsBoolean();
        result.addProperty("matched", matched);
        result.addProperty("scope", "RNG next-value roundtrip only; not game-state reload or SL replay");
        return result;
    }
}
