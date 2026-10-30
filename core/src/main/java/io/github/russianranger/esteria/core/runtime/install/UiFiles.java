package io.github.russianranger.esteria.core.runtime.install;

import java.io.*;
import java.nio.charset.*;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;

/** Bounded inventory codec shared by immutable UI baselines and mutable-tree assessment. */
final class UiFiles {
    static final int MAX_FILES=8192, MAX_DEPTH=32, MAX_METADATA=4<<20;
    static final long MAX_FILE_BYTES=256L<<20, MAX_BYTES=1L<<30;
    static final class Entry {
        final long bytes;final String sha256;
        Entry(long bytes,String sha256)throws IOException {
            RuntimeFiles.require(bytes>=0&&bytes<=MAX_FILE_BYTES,"Loose UI file exceeds256MiB bound");RuntimeFiles.hashPin(sha256);this.bytes=bytes;this.sha256=sha256;
        }
        public boolean equals(Object other){return other instanceof Entry&&bytes==((Entry)other).bytes&&sha256.equals(((Entry)other).sha256);}
        public int hashCode(){return Objects.hash(bytes,sha256);}
    }
    static String safe(String path)throws IOException {
        RuntimeFiles.require(path!=null&&!path.isEmpty()&&path.length()<=169,"Loose UI path exceeds client Windows bound");
        for(String part:path.split("/",-1)) {
            RuntimeFiles.require(!part.isEmpty()&&!part.equals(".")&&!part.equals("..")&&!part.endsWith(".")&&!part.endsWith(" ")&&part.matches("[A-Za-z0-9_. ()@+-]+"),"Unsupported loose UI filename");
            RuntimeFiles.require(!part.split("\\.",2)[0].toUpperCase(Locale.ROOT).matches("CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]"),"Reserved loose UI filename");
        }
        return path;
    }
    static Path directory(Path path)throws IOException {
        RuntimeFiles.require(path!=null&&path.isAbsolute()&&path.normalize().equals(path)&&Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)&&path.toRealPath().equals(path),"Expected canonical plain UI directory");return path;
    }
    static String encode(Map<String,Entry> files)throws IOException {
        StringBuilder text=new StringBuilder("esteria-ui-inventory-v1\n");long total=0;
        RuntimeFiles.require(files.size()<=MAX_FILES,"Loose UI file-count bound exceeded");
        Set<String> folded=new HashSet<>();
        for(Map.Entry<String,Entry> item:new TreeMap<>(files).entrySet()) {
            String path=safe(item.getKey());Entry value=item.getValue();
            RuntimeFiles.require(folded.add(path.toLowerCase(Locale.ROOT)),"Case-colliding loose UI files");total+=value.bytes;
            RuntimeFiles.require(total<=MAX_BYTES,"Loose UI exceeds1GiB bound");
            text.append(Base64.getEncoder().encodeToString(path.getBytes(StandardCharsets.UTF_8))).append('\t').append(value.bytes).append('\t').append(value.sha256).append('\n');
            RuntimeFiles.require(text.length()<=MAX_METADATA,"Loose UI inventory metadata bound exceeded");
        }
        return text.toString();
    }
    static SortedMap<String,Entry> decode(String text)throws IOException {
        RuntimeFiles.require(text.length()<=MAX_METADATA&&text.startsWith("esteria-ui-inventory-v1\n")&&text.endsWith("\n"),"Invalid UI inventory envelope");
        SortedMap<String,Entry> result=new TreeMap<>();
        try {
            for(String line:text.substring("esteria-ui-inventory-v1\n".length()).split("\n")) {
                if(line.isEmpty())continue;String[] parts=line.split("\t",-1);RuntimeFiles.require(parts.length==3,"Invalid UI inventory record");
                String path=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(java.nio.ByteBuffer.wrap(Base64.getDecoder().decode(parts[0]))).toString();
                RuntimeFiles.require(result.put(safe(path),new Entry(Long.parseLong(parts[1]),parts[2]))==null,"Duplicate UI inventory record");
            }
        } catch(IllegalArgumentException malformed){throw new IOException("Invalid UI inventory number/encoding",malformed);}
        RuntimeFiles.require(encode(result).equals(text),"Noncanonical UI inventory");return result;
    }
    interface Visitor {void file(String relative,Path path,BasicFileAttributes attributes)throws IOException;}
    static void walk(Path root,RuntimeWork.Cancellation cancelled,Visitor visitor)throws IOException {
        directory(root);Set<String> folded=new HashSet<>();final int[] entries={0},files={0};final long[] total={0};
        Files.walkFileTree(root,EnumSet.noneOf(FileVisitOption.class),MAX_DEPTH,new SimpleFileVisitor<Path>() {
            private String checked(Path path,BasicFileAttributes attrs)throws IOException {
                RuntimeWork.check(cancelled);if(path.equals(root))return "";
                RuntimeFiles.require(++entries[0]<=MAX_FILES*2,"Loose UI directory inventory bound exceeded");
                String name=safe(root.relativize(path).toString());RuntimeFiles.require(folded.add(name.toLowerCase(Locale.ROOT)),"Case-colliding loose UI paths");
                RuntimeFiles.require(!attrs.isSymbolicLink()&&(attrs.isDirectory()||attrs.isRegularFile()),"Loose UI contains link/special file; preserved");return name;
            }
            public FileVisitResult preVisitDirectory(Path path,BasicFileAttributes attrs)throws IOException{checked(path,attrs);return FileVisitResult.CONTINUE;}
            public FileVisitResult visitFile(Path path,BasicFileAttributes attrs)throws IOException {
                String relative=checked(path,attrs);RuntimeFiles.require(attrs.isRegularFile(),"Loose UI depth bound exceeded");
                RuntimeFiles.require(++files[0]<=MAX_FILES&&attrs.size()<=MAX_FILE_BYTES,"Loose UI file count/size bound exceeded");total[0]+=attrs.size();
                RuntimeFiles.require(total[0]<=MAX_BYTES,"Loose UI exceeds1GiB bound");visitor.file(relative,path,attrs);return FileVisitResult.CONTINUE;
            }
        });
    }
    static SortedMap<String,Entry> snapshot(Path root,RuntimeWork.Cancellation cancelled)throws IOException {
        SortedMap<String,Entry> result=new TreeMap<>();
        walk(root,cancelled,(name,path,before)->{
            privateFile(path);String hash=RuntimeFiles.hashFile(path,before.size(),cancelled);
            BasicFileAttributes after=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
            RuntimeFiles.require(before.size()==after.size()&&before.lastModifiedTime().equals(after.lastModifiedTime())&&Objects.equals(before.fileKey(),after.fileKey()),"Loose UI changed during assessment");
            result.put(name,new Entry(before.size(),hash));
        });return result;
    }
    static long total(Map<String,Entry> entries){long total=0;for(Entry value:entries.values())total+=value.bytes;return total;}
    static void privateFile(Path file)throws IOException {
        RuntimeFiles.plain(file);
        try{RuntimeFiles.require(((Number)Files.getAttribute(file,"unix:nlink",LinkOption.NOFOLLOW_LINKS)).longValue()==1,"Mutable UI file is hard-linked; preserved");}
        catch(UnsupportedOperationException unsupported){/* No hard links are created by this store. */}
    }
    static Path owned(Path path,String marker)throws IOException {
        Path root=RuntimeFiles.directory(path),owner=root.resolve(".owner");
        if(Files.exists(owner,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.require(RuntimeFiles.smallText(owner,256).equals(marker),"UI ownership differs; preserved");
        else {
            try(DirectoryStream<Path> children=Files.newDirectoryStream(root)){RuntimeFiles.require(!children.iterator().hasNext(),"Unowned UI directory preserved");}
            RuntimeFiles.atomicText(owner,marker,RuntimeFiles.sync(root));
        }
        return root;
    }
    static void syncTree(Path root,boolean enabled)throws IOException {
        if(!enabled)return;Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
            public FileVisitResult postVisitDirectory(Path path,IOException error)throws IOException {
                if(error!=null)throw error;RuntimeFiles.require(RuntimeFiles.sync(path),"UI directory sync failed");return FileVisitResult.CONTINUE;
            }
        });
    }
}
