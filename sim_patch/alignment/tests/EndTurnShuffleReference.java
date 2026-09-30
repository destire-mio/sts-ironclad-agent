// Independent golden data from the JRE used by the local original game.
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Random;
import java.util.concurrent.atomic.AtomicLong;

public class EndTurnShuffleReference {
    private static final Field SEED;
    static {
        try { SEED = Random.class.getDeclaredField("seed"); SEED.setAccessible(true); }
        catch (Exception e) { throw new RuntimeException(e); }
    }
    static AtomicLong state(Random r) throws Exception { return (AtomicLong) SEED.get(r); }
    public static void main(String[] args) throws Exception {
        System.out.print("{\"shuffles\":[");
        boolean comma = false;
        long[] seeds = {0, 1, 123, 399, Long.MIN_VALUE, Long.MAX_VALUE, -1};
        for (long seed : seeds) for (int size = 0; size <= 10; ++size) {
            Random random = new Random(seed);
            long before = state(random).get();
            ArrayList<Integer> cards = new ArrayList<Integer>();
            for (int i = 0; i < size; ++i) cards.add(i);
            Collections.shuffle(cards, random);
            if (comma) System.out.print(","); comma = true;
            System.out.print("{\"seed\":\"" + Long.toUnsignedString(seed) + "\",\"size\":" + size
                + ",\"before\":" + before + ",\"order\":" + cards + ",\"after\":" + state(random).get() + "}");
        }
        System.out.print("],\"bounded\":["); comma = false;
        int[] bounds = {1, 2, 3, 7, 10, 1073741825, Integer.MAX_VALUE};
        for (long seed : seeds) for (int bound : bounds) {
            Random random = new Random(seed);
            long before = state(random).get();
            ArrayList<Integer> values = new ArrayList<Integer>();
            for (int i = 0; i < 32; ++i) values.add(random.nextInt(bound));
            if (comma) System.out.print(","); comma = true;
            System.out.print("{\"seed\":\"" + Long.toUnsignedString(seed) + "\",\"bound\":" + bound
                + ",\"before\":" + before + ",\"values\":" + values + ",\"after\":" + state(random).get() + "}");
        }
        System.out.println("]}");
    }
}
