package io.github.russianranger.esteria.runtime;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Current APK binding plus the stable source identity of archived server bytes. */
final class ServerSourceSelection {
    private ServerSourceSelection() { }

    static String verify(byte[] embeddedLock, JSONObject proof) throws IOException, JSONException {
        if (embeddedLock.length == 0 || embeddedLock.length > 65536 ||
                !hash(embeddedLock).equals(proof.getString("appSourceLockSha256")))
            throw new IOException("Current APK source binding differs");
        JSONObject current = new JSONObject(new String(embeddedLock, StandardCharsets.UTF_8));
        if (current.getInt("schema") != 1 ||
                !sameJson(current.getJSONObject("sources").getJSONObject("server"), proof.getJSONObject("serverSource")) ||
                !sameJson(current.getJSONObject("compatibility"), proof.getJSONObject("serverBuildCompatibility")))
            throw new IOException("Current server selection or compatibility differs from the archived server build");
        JSONObject archived = proof.getJSONObject("serverBuildSourceLock");
        String hash = archived.getString("sha256");
        if (archived.getLong("bytes") <= 0 || archived.getLong("bytes") > 65536 || !hash.matches("[0-9a-f]{64}") ||
                !hash.equals(proof.getString("serverBuildSourceLockSha256")))
            throw new IOException("Invalid archived server build source identity");
        byte[] originalBytes = proof.getString("serverBuildSourceLockText").getBytes(StandardCharsets.UTF_8);
        if (originalBytes.length != archived.getLong("bytes") || !hash(originalBytes).equals(hash))
            throw new IOException("Archived server build source bytes differ");
        JSONObject original = new JSONObject(new String(originalBytes, StandardCharsets.UTF_8));
        if (original.getInt("schema") != 1 ||
                !sameJson(original.getJSONObject("sources").getJSONObject("server"), proof.getJSONObject("serverSource")) ||
                !sameJson(original.getJSONObject("compatibility"), proof.getJSONObject("serverBuildCompatibility")))
            throw new IOException("Archived server source or compatibility profile differs");
        return hash;
    }

    static boolean sameJson(Object left, Object right) throws JSONException {
        if (left instanceof JSONObject && right instanceof JSONObject) {
            JSONObject a = (JSONObject) left, b = (JSONObject) right;
            if (a.length() != b.length()) return false;
            var names = a.keys();
            while (names.hasNext()) { String name = names.next(); if (!b.has(name) || !sameJson(a.get(name), b.get(name))) return false; }
            return true;
        }
        if (left instanceof JSONArray && right instanceof JSONArray) {
            JSONArray a = (JSONArray) left, b = (JSONArray) right;
            if (a.length() != b.length()) return false;
            for (int i = 0; i < a.length(); i++) if (!sameJson(a.get(i), b.get(i))) return false;
            return true;
        }
        // JSON integers have no Java wrapper width. Android parses small
        // counts as Integer, while file metadata is supplied as Long.
        if ((left instanceof Integer || left instanceof Long) &&
                (right instanceof Integer || right instanceof Long))
            return ((Number) left).longValue() == ((Number) right).longValue();
        return left.equals(right);
    }

    private static String hash(byte[] bytes) throws IOException {
        try {
            StringBuilder output = new StringBuilder(64);
            for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes))
                output.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return output.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IOException("SHA-256 unavailable", impossible); }
    }
}
