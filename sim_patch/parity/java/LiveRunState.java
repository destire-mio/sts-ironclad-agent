package spirelablogic;

import com.google.gson.*;
import com.megacrit.cardcrawl.cards.*;
import com.megacrit.cardcrawl.core.*;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.helpers.EventHelper;
import com.megacrit.cardcrawl.map.*;
import com.megacrit.cardcrawl.neow.*;
import com.megacrit.cardcrawl.relics.*;
import com.megacrit.cardcrawl.potions.AbstractPotion;
import com.megacrit.cardcrawl.rewards.*;
import com.megacrit.cardcrawl.rooms.*;
import com.megacrit.cardcrawl.shop.ShopScreen;
import com.megacrit.cardcrawl.shop.StoreRelic;
import com.megacrit.cardcrawl.shop.StorePotion;
import java.lang.reflect.*;
import java.util.*;

/** Read-only run state. Export identities and hidden rule inputs, never UI objects. */
public final class LiveRunState {
 static Object field(Object object, String name) throws Exception {
  Class<?> c=object instanceof Class?(Class<?>)object:object.getClass();
  while(c!=null){try{Field f=c.getDeclaredField(name);f.setAccessible(true);return f.get(object instanceof Class?null:object);}catch(NoSuchFieldException e){c=c.getSuperclass();}}
  throw new NoSuchFieldException(name);
 }
 static JsonObject card(AbstractCard c){JsonObject o=OutsideProbe.card(c);o.addProperty("uuid",c.uuid.toString());return o;}
 static JsonArray cards(Iterable<AbstractCard> cs){JsonArray a=new JsonArray();for(AbstractCard c:cs)a.add(card(c));return a;}
 static JsonArray rewards(List<RewardItem> rs){JsonArray a=new JsonArray();for(RewardItem r:rs){JsonObject o=new JsonObject();o.addProperty("type",r.type.name());o.addProperty("done",r.isDone);if(r.relic!=null)o.addProperty("relic",r.relic.relicId);if(r.potion!=null)o.addProperty("potion",r.potion.ID);if(r.cards!=null)o.add("cards",cards(r.cards));o.addProperty("gold",r.goldAmt+r.bonusGold);a.add(o);}return a;}
 static JsonObject simpleFields(Object obj)throws Exception {
  JsonObject out=new JsonObject();if(obj==null)return out;
  for(Class<?> c=obj.getClass();c!=null&&c!=Object.class;c=c.getSuperclass())for(Field f:c.getDeclaredFields()){
   if((Modifier.isStatic(f.getModifiers())&&Modifier.isFinal(f.getModifiers()))||out.has(f.getName()))continue;f.setAccessible(true);Object v=f.get(obj);
   if(v==null)continue;
   if(v instanceof Number||v instanceof Boolean||v instanceof String)out.add(f.getName(),AlignmentProbe.JSON.toJsonTree(v));
   else if(v instanceof Enum)out.addProperty(f.getName(),v.toString());
   else if(v instanceof AbstractCard)out.add(f.getName(),card((AbstractCard)v));
   else if(v instanceof AbstractRelic)out.addProperty(f.getName(),((AbstractRelic)v).relicId);
   else if(v instanceof AbstractPotion){JsonObject p=new JsonObject();p.addProperty("id",((AbstractPotion)v).ID);p.addProperty("slot",((AbstractPotion)v).slot);out.add(f.getName(),p);}
   else if(v instanceof Iterable){JsonArray a=new JsonArray();boolean supported=true;for(Object x:(Iterable<?>)v){if(x instanceof String||x instanceof Number||x instanceof Boolean)a.add(AlignmentProbe.JSON.toJsonTree(x));else if(x instanceof AbstractCard)a.add(card((AbstractCard)x));else {supported=false;break;}}if(supported)out.add(f.getName(),a);}
  }return out;
 }
 static JsonObject snapshot()throws Exception {
  JsonObject out=new JsonObject();out.add("outside",OutsideProbe.snapshot());out.add("pools",OutsideProbe.pools());
  out.addProperty("x",AbstractDungeon.currMapNode.x);out.addProperty("y",AbstractDungeon.currMapNode.y);
  out.addProperty("room",AbstractDungeon.getCurrRoom().getClass().getSimpleName());out.addProperty("boss",AbstractDungeon.bossKey);
  for(String n:new String[]{"monsterList","eliteMonsterList","bossList","eventList","shrineList","specialOneTimeEventList"})out.add(n,AlignmentProbe.JSON.toJsonTree(field(AbstractDungeon.class,n)));
  out.addProperty("card_rarity_factor",AbstractDungeon.cardBlizzRandomizer);out.addProperty("potion_chance",AbstractRoom.blizzardPotionMod);
  out.addProperty("purge_cost",ShopScreen.purgeCost);out.add("event_chances",AlignmentProbe.JSON.toJsonTree(EventHelper.getChances()));
  out.add("deck",cards(AbstractDungeon.player.masterDeck.group));
  out.add("rewards",rewards(AbstractDungeon.combatRewardScreen.rewards));
  out.add("room_rewards",rewards(AbstractDungeon.getCurrRoom().rewards));
  Object event=AbstractDungeon.getCurrRoom().event;out.add("event_fields",simpleFields(event));
  if(event instanceof NeowEvent){JsonArray a=new JsonArray();for(Object obj:(Iterable<?>)field(event,"rewards")){NeowReward r=(NeowReward)obj;JsonObject v=new JsonObject();v.addProperty("bonus",r.type.name());v.addProperty("drawback",r.drawback.name());a.add(v);}out.add("neow",a);}
  if(AbstractDungeon.screen==AbstractDungeon.CurrentScreen.GRID){
   out.add("grid_fields",simpleFields(AbstractDungeon.gridSelectScreen));
   out.add("grid_cards",cards(((CardGroup)field(AbstractDungeon.gridSelectScreen,"targetGroup")).group));
   out.add("grid_selected",cards(AbstractDungeon.gridSelectScreen.selectedCards));
  }
  if(AbstractDungeon.screen==AbstractDungeon.CurrentScreen.SHOP){
   JsonObject slots=new JsonObject();
   JsonArray rs=new JsonArray();for(Object obj:(Iterable<?>)field(AbstractDungeon.shopScreen,"relics")){StoreRelic v=(StoreRelic)obj;if(v.isPurchased)continue;JsonObject item=new JsonObject();item.addProperty("id",v.relic.relicId);item.addProperty("slot",(Integer)field(v,"slot"));rs.add(item);}slots.add("relics",rs);
   JsonArray ps=new JsonArray();for(Object obj:(Iterable<?>)field(AbstractDungeon.shopScreen,"potions")){StorePotion v=(StorePotion)obj;if(v.isPurchased)continue;JsonObject item=new JsonObject();item.addProperty("id",v.potion.ID);item.addProperty("slot",(Integer)field(v,"slot"));ps.add(item);}slots.add("potions",ps);
   out.add("shop_slots",slots);
  }
  JsonArray relics=new JsonArray();for(AbstractRelic r:AbstractDungeon.player.relics){JsonObject o=simpleFields(r);o.addProperty("id",r.relicId);relics.add(o);}out.add("relic_fields",relics);
  return out;
 }
}
