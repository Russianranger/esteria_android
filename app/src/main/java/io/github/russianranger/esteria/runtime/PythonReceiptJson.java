package io.github.russianranger.esteria.runtime;

import java.io.IOException;
import java.util.Comparator;
import java.util.TreeSet;
import org.json.JSONException;
import org.json.JSONObject;

/** Byte contract of shader_generation.encoded: Python's sorted compact JSON
 * with ensure_ascii=True. Android JSONObject.quote additionally escapes '/',
 * so it must not choose a Python receipt's content-addressed generation. */
final class PythonReceiptJson {
    private PythonReceiptJson() { }
    private static final char[] HEX="0123456789abcdef".toCharArray();
    private static final Comparator<String> CODE_POINTS=(left,right)->{
        int a=0,b=0;
        while(a<left.length()&&b<right.length()) {
            int x=left.codePointAt(a),y=right.codePointAt(b);
            if(x!=y)return Integer.compare(x,y);
            a+=Character.charCount(x);b+=Character.charCount(y);
        }
        return Integer.compare(left.length()-a,right.length()-b);
    };
    static String canonical(JSONObject value)throws JSONException,IOException {return canonical(value,true);}
    static String canonical(JSONObject value,boolean booleans)throws JSONException,IOException {
        TreeSet<String> names=new TreeSet<>(CODE_POINTS);value.keys().forEachRemaining(names::add);
        StringBuilder out=new StringBuilder("{");
        for(String name:names) {
            if(out.length()>1)out.append(',');quote(out,name);out.append(':');Object item=value.get(name);
            if(item instanceof JSONObject)out.append(canonical((JSONObject)item,booleans));
            else if(item instanceof String)quote(out,(String)item);
            else if(item instanceof Integer||item instanceof Long||(booleans&&item instanceof Boolean))out.append(item);
            else throw new IOException("Unsupported canonical Python receipt value");
        }
        return out.append('}').toString();
    }
    private static void quote(StringBuilder out,String value) {
        out.append('"');
        for(int index=0;index<value.length();index++) {
            char c=value.charAt(index);
            switch(c) {
                case '"':case '\\':out.append('\\').append(c);break;
                case '\b':out.append("\\b");break;
                case '\f':out.append("\\f");break;
                case '\n':out.append("\\n");break;
                case '\r':out.append("\\r");break;
                case '\t':out.append("\\t");break;
                default:
                    if(c<32||c>126)out.append("\\u").append(HEX[(c>>>12)&15]).append(HEX[(c>>>8)&15]).append(HEX[(c>>>4)&15]).append(HEX[c&15]);
                    else out.append(c);
            }
        }
        out.append('"');
    }
}
