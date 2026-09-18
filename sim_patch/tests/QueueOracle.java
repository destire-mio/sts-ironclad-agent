import com.megacrit.cardcrawl.actions.AbstractGameAction;
import com.megacrit.cardcrawl.actions.GameActionManager;
import java.util.ArrayList;

public class QueueOracle {
    static class Mark extends AbstractGameAction {
        final int id;
        Mark(int id, boolean clear) {
            this.id = id;
            this.actionType = clear ? ActionType.DRAW : ActionType.DAMAGE;
        }
        public void update() { this.isDone = true; }
    }
    public static void main(String[] args) {
        GameActionManager manager = new GameActionManager();
        for (int i=0; i<512; ++i) manager.actions.add(new Mark(i,false));
        if (manager.actions.size()!=512) throw new AssertionError();
        for (int i=0; i<512; ++i)
            if (((Mark)manager.actions.remove(0)).id!=i) throw new AssertionError();
        for (int i=0; i<6; ++i) manager.actions.add(new Mark(i,i==5));
        for (int i=0; i<4; ++i) manager.actions.remove(0);
        for (int i=6; i<10; ++i) manager.actions.add(new Mark(i,i==6 || i==9));
        manager.clearPostCombatActions();
        manager.actions.add(new Mark(10,false));
        manager.actions.add(0,new Mark(11,false));
        ArrayList<Integer> actual = new ArrayList<Integer>();
        for (AbstractGameAction action : manager.actions) actual.add(((Mark)action).id);
        if (!actual.toString().equals("[11, 4, 7, 8, 10]")) throw new AssertionError(actual);
        System.out.println("growth512=PASS; original_clear_then_append="+actual);
    }
}
