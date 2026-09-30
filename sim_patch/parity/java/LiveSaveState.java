package spirelablogic;

import com.badlogic.gdx.math.MathUtils;
import com.badlogic.gdx.math.RandomXS128;
import com.google.gson.*;
import com.megacrit.cardcrawl.characters.AbstractPlayer;
import com.megacrit.cardcrawl.core.*;
import com.megacrit.cardcrawl.dungeons.*;
import com.megacrit.cardcrawl.neow.NeowEvent;
import com.megacrit.cardcrawl.saveAndContinue.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.concurrent.atomic.AtomicLong;
import steamstateexport.FullRngState;

/** SL uses the actual autosave, followed by a recorded first-decision RNG restore. */
public final class LiveSaveState {
 static String saved=null;
 static JsonObject rng=null;
 static int floor=-1;
 static Field field(Class<?> c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
 static JsonObject checkpoint()throws Exception {
  String data=SaveAndContinue.loadSaveString(AbstractDungeon.player.chosenClass);
  SaveFile file=AlignmentProbe.JSON.fromJson(data,SaveFile.class);
  if(file.seed!=Settings.seed||file.floor_num!=AbstractDungeon.floorNum||file.post_combat)
   throw new IllegalStateException("autosave is not this natural pre-combat room");
  saved=data;floor=file.floor_num;rng=AlignmentProbe.JSON.toJsonTree(FullRngState.capture()).getAsJsonObject();
  JsonObject out=new JsonObject();out.add("save",AlignmentProbe.JSON.fromJson(data,JsonObject.class));out.add("rng",rng);return out;
 }
 static void restoreRandom(java.util.Random random,JsonObject row)throws Exception {
  if(random instanceof RandomXS128)((RandomXS128)random).setState(Long.parseUnsignedLong(row.get("seed0").getAsString()),Long.parseUnsignedLong(row.get("seed1").getAsString()));
  else ((AtomicLong)field(java.util.Random.class,"seed").get(random)).set(Long.parseLong(row.get("seed48").getAsString()));
  JsonObject cache=row.getAsJsonObject("gaussian");
  field(java.util.Random.class,"haveNextNextGaussian").setBoolean(random,cache.get("has_cached").getAsBoolean());
  field(java.util.Random.class,"nextNextGaussian").setDouble(random,Double.longBitsToDouble(Long.parseUnsignedLong(cache.get("cached_double_bits").getAsString())));
 }
 static void reload()throws Exception {
  if(saved==null)throw new IllegalStateException("no natural checkpoint");
  Path path=Paths.get(AbstractDungeon.player.getSaveFilePath());Files.write(path,saved.getBytes(StandardCharsets.UTF_8));
  CardCrawlGame.loadingSave=true;Method load=CardCrawlGame.class.getDeclaredMethod("loadPlayerSave",AbstractPlayer.class);load.setAccessible(true);load.invoke(SpireLabLogic.listener,AbstractDungeon.player);
  SaveFile file=CardCrawlGame.saveFile;
  if(file.act_num==1)CardCrawlGame.dungeon=new Exordium(AbstractDungeon.player,file);
  else if(file.act_num==2)CardCrawlGame.dungeon=new TheCity(AbstractDungeon.player,file);
  else if(file.act_num==3)CardCrawlGame.dungeon=new TheBeyond(AbstractDungeon.player,file);
  else CardCrawlGame.dungeon=new TheEnding(AbstractDungeon.player,file);
  Method post=CardCrawlGame.class.getDeclaredMethod("loadPostCombat",SaveFile.class);post.setAccessible(true);post.invoke(SpireLabLogic.listener,file);
  RuleProbe.flush();AlignmentProbe.settle();
  if(AbstractDungeon.floorNum!=floor)throw new IllegalStateException("SL floor changed");
  restoreEnvelope(rng);
 }
 static void restoreEnvelope(JsonObject envelope)throws Exception {
  if(envelope.get("schema_version").getAsInt()!=1||!envelope.get("complete").getAsBoolean()||Long.parseLong(envelope.get("run_seed").getAsString())!=Settings.seed||envelope.get("act").getAsInt()!=AbstractDungeon.actNum||envelope.get("floor").getAsInt()!=AbstractDungeon.floorNum)
   throw new IllegalArgumentException("RNG restore must target this seed, act and floor");
  JsonObject streams=envelope.getAsJsonObject("streams");
  JsonObject before=AlignmentProbe.JSON.toJsonTree(FullRngState.capture()).getAsJsonObject();
  if(!before.get("complete").getAsBoolean())throw new IllegalStateException("cannot roll back an incomplete RNG export");
  JsonObject previous=before.getAsJsonObject("streams");
  if(streams.entrySet().size()!=16)throw new IllegalArgumentException("all sixteen named RNG streams required");
  for(java.util.Map.Entry<String,JsonElement> e:previous.entrySet())if(!streams.has(e.getKey()))throw new IllegalArgumentException("missing RNG stream: "+e.getKey());
  // Parse every field before touching any live object. A malformed late stream
  // must not leave the earlier streams restored and the remaining ones stale.
  for(java.util.Map.Entry<String,JsonElement> e:streams.entrySet()){
   JsonObject row=e.getValue().getAsJsonObject();String name=e.getKey();
   if(!row.get("initialized").getAsBoolean()){
    if(name.equals("MathUtils.random"))throw new IllegalArgumentException("MathUtils RNG must exist");
    continue;
   }
   boolean lcg=name.equals("Collections.r");
   if(!row.get("class").getAsString().equals(lcg?"java.util.Random":"com.badlogic.gdx.math.RandomXS128")||!row.get("algorithm").getAsString().equals(lcg?"java_lcg48":"xorshift128plus"))throw new IllegalArgumentException("RNG algorithm changed: "+name);
   if(lcg){long seed=Long.parseLong(row.get("seed48").getAsString());if(seed<0||seed>=(1L<<48))throw new IllegalArgumentException("invalid Java RNG state");}
   else {Long.parseUnsignedLong(row.get("seed0").getAsString());Long.parseUnsignedLong(row.get("seed1").getAsString());}
   JsonObject cache=row.getAsJsonObject("gaussian");cache.get("has_cached").getAsBoolean();Long.parseUnsignedLong(cache.get("cached_double_bits").getAsString());
   if(!name.equals("MathUtils.random")&&!lcg){int counter=row.get("counter").getAsInt();if(counter<0)throw new IllegalArgumentException("negative RNG counter");}
  }
  try {
   applyStreams(streams);
   JsonObject actual=AlignmentProbe.JSON.toJsonTree(FullRngState.capture()).getAsJsonObject();
   if(!actual.getAsJsonObject("streams").equals(streams))throw new IllegalStateException("RNG restore verification failed");
  }catch(Exception error){try{applyStreams(previous);}catch(Exception rollback){error.addSuppressed(rollback);}throw error;}
 }
 static void applyStreams(JsonObject streams)throws Exception {
  for(java.util.Map.Entry<String,JsonElement> e:streams.entrySet()){
   String name=e.getKey();
   JsonObject row=e.getValue().getAsJsonObject();boolean initialized=row.get("initialized").getAsBoolean();
   if(name.equals("MathUtils.random")){
    if(!initialized)throw new IllegalArgumentException("MathUtils RNG must exist");
    restoreRandom(MathUtils.random,row);
   }else if(name.equals("Collections.r")){
    Field f=field(Collections.class,"r");
    if(!initialized){f.set(null,null);continue;}
    java.util.Random r=(java.util.Random)f.get(null);
    if(r==null){r=new java.util.Random(0L);f.set(null,r);}restoreRandom(r,row);
   }else {
    Field f=name.equals("NeowEvent.rng")?NeowEvent.class.getField("rng"):AbstractDungeon.class.getField(name);
    if(f.getType()!=com.megacrit.cardcrawl.random.Random.class)throw new IllegalArgumentException("not a game RNG: "+name);
    if(!initialized){f.set(null,null);continue;}
    com.megacrit.cardcrawl.random.Random r=(com.megacrit.cardcrawl.random.Random)f.get(null);
    if(r==null){r=new com.megacrit.cardcrawl.random.Random(0L);f.set(null,r);}
    restoreRandom(r.random,row);r.counter=row.get("counter").getAsInt();
   }
  }
 }
}
