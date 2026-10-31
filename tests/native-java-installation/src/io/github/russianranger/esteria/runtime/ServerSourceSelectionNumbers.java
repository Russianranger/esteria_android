package io.github.russianranger.esteria.runtime;

import org.json.JSONArray;
import org.json.JSONObject;

/** Real JSON parser regression. It grants no runtime, provider or SQL proof. */
public final class ServerSourceSelectionNumbers {
    private static void check(boolean value,String name) {
        if(!value)throw new AssertionError("Source-selection JSON regression: "+name);
    }
    private static void compare(String name,Object first,Object second,boolean expected)throws Exception {
        check(ServerSourceSelection.sameJson(first,second)==expected,name);
        check(ServerSourceSelection.sameJson(second,first)==expected,name+" reversed");
    }
    public static void verify()throws Exception {
        JSONObject stored=new JSONObject().put("bytes",32521L).put("sha256","a".repeat(64));
        JSONObject parsed=new JSONObject(stored.toString());
        check(stored.get("bytes") instanceof Long,"programmatic byte count is Long");
        check(parsed.get("bytes") instanceof Integer,"real parser chooses Integer for small byte count");
        compare("same parsed source identity",stored,parsed,true);
        compare("nested arrays",new JSONObject().put("rows",new JSONArray().put(32521L).put(2147483648L)),
            new JSONObject("{\"rows\":[32521,2147483648]}"),true);
        for(long value:new long[]{Integer.MIN_VALUE,Integer.MAX_VALUE,2147483648L,Long.MIN_VALUE,Long.MAX_VALUE})
            compare("integral boundary",new JSONObject().put("bytes",value),new JSONObject("{\"bytes\":"+value+"}"),true);
        compare("changed byte count",stored,new JSONObject(parsed.toString()).put("bytes",32522),false);
        compare("changed digest",stored,new JSONObject(parsed.toString()).put("sha256","b".repeat(64)),false);
        compare("string byte count",stored,new JSONObject(parsed.toString()).put("bytes","32521"),false);
        compare("floating byte count",stored,new JSONObject(parsed.toString()).put("bytes",32521.0),false);
        compare("boolean byte count",stored,new JSONObject(parsed.toString()).put("bytes",true),false);
        compare("no truncated overflow",Integer.valueOf(-1),Long.valueOf(4294967295L),false);
        compare("no double rounding",Long.valueOf(9007199254740993L),Double.valueOf(9007199254740992.0),false);
        compare("extra key",stored,new JSONObject(parsed.toString()).put("extra",true),false);
        compare("array order",new JSONArray().put(1L).put(2L),new JSONArray("[2,1]"),false);
    }
    public static void main(String[] arguments)throws Exception {
        verify();System.out.println("Real-parser source-selection integer regression passed");
    }
}
