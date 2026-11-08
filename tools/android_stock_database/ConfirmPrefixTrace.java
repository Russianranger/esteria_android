package io.github.russianranger.esteria.runtime;
import io.github.russianranger.esteria.core.runtime.StockWinePrefix;
import org.json.JSONObject;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
/** Calls the candidate's actual read-only gates. Exports only controlled checks on a disposable Android store. */
final class ConfirmPrefixTrace {
 private static Object call(Class<?> type,String name,Object target,Class<?>[] signature,Object... args)throws Exception {
    Method m=type.getDeclaredMethod(name,signature);m.setAccessible(true);
    try{return m.invoke(target,args);}catch(InvocationTargetException e){Throwable cause=e.getCause();JSONObject o=new JSONObject();o.put("type",cause.getClass().getSimpleName());String msg=cause.getMessage();
        if(msg!=null && (msg.matches("Registry [a-z ]{2,40}") || msg.startsWith("Duplicate") || msg.startsWith("Linked observed") || msg.startsWith("Duplicate/bounded observed")))o.put("reason",msg);
        StackTraceElement[] trace=cause.getStackTrace();for(StackTraceElement f:trace)if(f.getClassName().startsWith("io.github.russianranger.esteria")){o.put("site",f.getClassName()+":"+f.getLineNumber());break;}return o;}
 }
 static JSONObject inspect(Path work, Path root,String archive) throws Exception {
    JSONObject d=new JSONObject();Class<?> c=StockWinePrefix.class,r=Class.forName("io.github.russianranger.esteria.core.runtime.StockWinePrefixRegistry");
    Class<?>[] fp={Path.class};Path p=work.resolve("home/.wine"),system=p.resolve("drive_c/windows/system32"),inf=root.resolve("opt/wine/share/wine/wine.inf");
    if(!Files.isDirectory(p))return d;StockWinePrefix s=StockWinePrefix.inspect(work,root,archive);
    d.put("classify",String.valueOf(call(c,"classify",s,new Class<?>[0])));
    for(String n:Arrays.asList(".update-timestamp","system.reg","user.reg","userdef.reg")){
       JSONObject f=new JSONObject();Path path=p.resolve(n);f.put("privateFile",call(c,"privateFile",null,fp,path));
       if(Files.isRegularFile(path)) {try{f.put("nlink",Files.getAttribute(path,"unix:nlink",LinkOption.NOFOLLOW_LINKS));}catch(RuntimeException ex){f.put("nlinkError",ex.getClass().getSimpleName());}}
       d.put(n,f);
    }
    d.put("runtimeDir",call(c,"directory",null,fp,root));d.put("runtimeInode",call(c,"inode",null,fp,root));d.put("prefixInode",call(c,"inode",null,fp,p));
    d.put("dosdevicesDir",call(c,"directory",null,fp,p.resolve("dosdevices")));d.put("system32Dir",call(c,"directory",null,fp,system));
    d.put("driverStoreAbsent",Files.notExists(system.resolve("driverstore"),LinkOption.NOFOLLOW_LINKS));d.put("manifestAbsent",Files.notExists(system.resolve("winevulkan.json"),LinkOption.NOFOLLOW_LINKS));
    try{d.put("cDriveMatch",p.getFileSystem().getPath("../drive_c").equals(Files.readSymbolicLink(p.resolve("dosdevices/c:"))));}catch(Exception e){d.put("cDriveError",e.getClass().getSimpleName());}
    long time=Files.getLastModifiedTime(inf,LinkOption.NOFOLLOW_LINKS).toMillis()/1000;d.put("javaInfMtime",time);
    d.put("markerMatches",call(c,"matches",null,new Class<?>[]{Path.class,byte[].class},p.resolve(".update-timestamp"),(time+"\r\n").getBytes(StandardCharsets.US_ASCII)));
    d.put("infPinned",call(c,"pinned",null,new Class<?>[]{Path.class,int.class,String.class},inf,58179,"c2042873062d575d2700672e3187674240019f64e740e4f36e82cc90fe75b4c0"));
    d.put("imagesPinned",call(c,"matchesPrefixImages",null,fp,system));
    d.put("stage",String.valueOf(call(r,"inspect",null,fp,p)));d.put("safeToUpdate",call(r,"safeToUpdate",null,fp,p));
    for(String name:Arrays.asList("system.reg","user.reg")){
       Object parsed=call(r,"read",null,new Class<?>[]{Path.class,boolean.class},p.resolve(name),name.equals("system.reg"));
       d.put(name+"Parser",parsed instanceof Map?((Map<?,?>)parsed).size():parsed);
    }
    return d;
 }
}
