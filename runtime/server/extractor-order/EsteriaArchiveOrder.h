/* Esteria extractor-only provider adaptation. GPL-2.0-or-later, matching the
 * selected AzerothCore tools/libmpq sources. The desktop default is unchanged.
 * Explicit ordered mode never falls back to the stock archive enumeration. */
#ifndef ESTERIA_ARCHIVE_ORDER_H
#define ESTERIA_ARCHIVE_ORDER_H
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <openssl/evp.h>
extern "C" {
#include "libmpq/mpq.h"
#include "libmpq/mpq-internal.h"
#include "libmpq/common.h"
}

namespace EsteriaOrder {
constexpr uint64_t MaxMember = uint64_t(1) << 30;
constexpr uint64_t MaxArchive = uint64_t(16) << 30;
inline void Need(bool yes, const char* reason) { if (!yes) throw std::runtime_error(reason); }
inline std::string Lower(std::string name) {
    for (char& ch : name) { if (ch == '\\') ch = '/'; if (ch >= 'A' && ch <= 'Z') ch += 'a' - 'A'; }
    return name;
}
inline std::string Relative(std::string name) {
    for (char& ch : name) if (ch == '\\') ch = '/';
    Need(!name.empty() && name.size() < 260 && name.front() != '/', "unsupported ordered member path");
    std::istringstream parts(name); std::string part;
    while (std::getline(parts, part, '/')) {
        Need(!part.empty() && part != "." && part != "..", "unsafe ordered member path");
        for (unsigned char ch : part) Need(ch >= 32 && ch < 127 && ch != ':' && ch != '\t', "non-ASCII ordered path refused");
    }
    Need(name.back() != '/', "ordered file path has trailing separator");
    return name;
}
inline uint64_t Number(const std::string& text, uint64_t maximum) {
    Need(!text.empty() && text.size() <= 20, "invalid ordered integer"); uint64_t result = 0;
    for (char ch : text) { Need(ch >= '0' && ch <= '9', "invalid ordered integer");
        Need(result <= (maximum - uint64_t(ch - '0')) / 10, "ordered integer bound"); result = result * 10 + ch - '0'; }
    return result;
}
inline void HashPin(const std::string& pin) {
    Need(pin.size() == 64 && pin.find_first_not_of("0123456789abcdef") == std::string::npos, "invalid ordered SHA256");
}
inline std::string Digest(const unsigned char* bytes, size_t size) {
    std::array<unsigned char,32> digest{}; unsigned length = 0;
    Need(EVP_Digest(bytes,size,digest.data(),&length,EVP_sha256(),nullptr) == 1 && length == 32, "ordered digest failed");
    std::string out; const char* digits = "0123456789abcdef";
    for (unsigned char ch : digest) { out += digits[ch >> 4]; out += digits[ch & 15]; } return out;
}
inline std::filesystem::path CheckedPath(const std::filesystem::path& root, const std::string& relative) {
    std::filesystem::path value = root;
    for (const auto& part : std::filesystem::path(Relative(relative))) {
        value /= part;
        auto status = std::filesystem::symlink_status(value);
        Need(!std::filesystem::is_symlink(status) && (std::filesystem::is_directory(status) || std::filesystem::is_regular_file(status)),
             "missing, linked or special ordered input");
    }
    return value;
}
inline std::string HashFile(const std::filesystem::path& file, uint64_t expected) {
    Need(std::filesystem::is_regular_file(std::filesystem::symlink_status(file)) && std::filesystem::file_size(file) == expected,
         "ordered input size differs");
    std::ifstream input(file,std::ios::binary); Need(bool(input),"ordered input open failed");
    std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)> digest(EVP_MD_CTX_new(),EVP_MD_CTX_free);
    Need(digest && EVP_DigestInit_ex(digest.get(),EVP_sha256(),nullptr)==1,"ordered digest setup failed");
    std::array<char,131072> buffer{}; uint64_t count=0;
    while (input) { input.read(buffer.data(),buffer.size()); auto n=input.gcount(); count+=uint64_t(n);
        Need(count<=expected && EVP_DigestUpdate(digest.get(),buffer.data(),size_t(n))==1,"ordered input changed"); }
    Need(input.eof() && count==expected,"ordered input short read"); std::array<unsigned char,32> raw{};unsigned n=0;
    Need(EVP_DigestFinal_ex(digest.get(),raw.data(),&n)==1 && n==32,"ordered digest finish failed");
    std::string out;const char* digits="0123456789abcdef";for(auto ch:raw){out+=digits[ch>>4];out+=digits[ch&15];}return out;
}
struct File { std::string path,sha256; uint64_t bytes=0; };
struct Provider {
    std::string kind,path,prefix;
    File archive;
    std::map<std::string,File> files;
    std::shared_ptr<mpq_archive_s> handle;
    std::shared_ptr<std::vector<uint32_t>> blockFiles;
};
struct State {
    bool active=false;
    std::string locale;
    std::string memberProbe;
    std::filesystem::path root;
    std::vector<Provider> providers;
};
inline State& Current() { static State state; return state; }
inline bool Active() { return Current().active; }
inline const std::string& Locale() { return Current().locale; }
inline const std::string& MemberProbe() { return Current().memberProbe; }
inline int EmitProbe(const char* bytes,size_t size,bool found) {
    if(found)std::printf("{\"scope\":\"ordered-adapted-mpqfile-lookup-only\",\"found\":true,\"bytes\":%zu,\"sha256\":\"%s\"}\n",
        size,Digest(reinterpret_cast<const unsigned char*>(bytes),size).c_str());
    else std::puts("{\"scope\":\"ordered-adapted-mpqfile-lookup-only\",\"found\":false}");
    return found?0:3;
}
inline std::vector<std::string> Fields(const std::string& line) {
    std::vector<std::string> out;std::istringstream source(line);std::string field;
    while(std::getline(source,field,'\t'))out.push_back(field);
    Need(!line.empty() && line.back()!='\t',"invalid ordered record");return out;
}
inline void Load(const std::string& manifest,const std::string& root,const std::string& expected) {
    Need(!Active(),"ordered mode already configured");HashPin(expected);
    std::filesystem::path inputRoot=std::filesystem::absolute(root);
    Need(inputRoot==std::filesystem::canonical(inputRoot) && std::filesystem::is_directory(inputRoot),"canonical ordered input root required");
    auto manifestPath=std::filesystem::absolute(manifest);
    Need(!std::filesystem::is_symlink(std::filesystem::symlink_status(manifestPath)),"linked ordered manifest refused");
    uint64_t manifestSize=std::filesystem::file_size(manifestPath);Need(manifestSize>0 && manifestSize<=(16u<<20),"ordered manifest byte bound");
    Need(HashFile(manifestPath,manifestSize)==expected,"ordered manifest SHA256 differs");
    std::ifstream input(manifestPath,std::ios::binary);std::string line;Need(bool(std::getline(input,line)),"ordered header missing");
    auto header=Fields(line);Need(header.size()==3 && header[0]=="ESTERIA-ORDER-1","ordered manifest version");
    std::set<std::string> locales={"deDE","enGB","enUS","esES","frFR","koKR","zhCN","zhTW","enCN","enTW","esMX","ruRU"};
    Need(locales.count(header[1])==1,"ordered effective locale invalid");size_t expectedCount=size_t(Number(header[2],4096));
    Need(expectedCount>0,"ordered provider list empty");State stage;stage.locale=header[1];stage.root=inputRoot;
    size_t fileCount=0;std::set<std::string> providerKeys;
    while(std::getline(input,line)) {
        Need(line.size()<=4096,"ordered record bound");auto f=Fields(line);
        if(f[0]=="P") {
            Need(f.size()==6 && (f[1]=="mpq" || f[1]=="directory"),"unsupported ordered provider type");
            Provider p;p.kind=f[1];p.path=Relative(f[2]);p.prefix=f[3]=="-"?"":Relative(f[3]);
            Need(p.prefix.empty() || p.prefix=="alternate","unsupported ordered prefix view");
            Need(providerKeys.insert(Lower(p.kind+":"+p.path+":"+p.prefix)).second,"duplicate ordered provider");
            p.archive={p.path,f[5],Number(f[4],MaxArchive)};
            if(p.kind=="mpq") { HashPin(f[5]);Need(p.archive.bytes>0,"empty ordered MPQ"); }
            else Need(p.prefix.empty() && f[4]=="0" && f[5]=="-","invalid ordered directory metadata");
            stage.providers.push_back(std::move(p));Need(stage.providers.size()<=expectedCount,"too many ordered providers");
        } else if(f[0]=="F") {
            Need(f.size()==4 && !stage.providers.empty() && stage.providers.back().kind=="directory","orphan ordered loose file");
            File file{Relative(f[1]),f[3],Number(f[2],MaxMember)};HashPin(file.sha256);
            Need(stage.providers.back().files.emplace(Lower(file.path),file).second,"case-colliding ordered loose file");
            Need(++fileCount<=100000,"ordered loose file count bound");
        } else Need(false,"unknown ordered record");
    }
    Need(input.eof() && stage.providers.size()==expectedCount,"incomplete ordered manifest");
    std::map<std::string,Provider> opened;
    for(auto& p:stage.providers) {
        auto physical=CheckedPath(inputRoot,p.path);
        if(p.kind=="directory") {
            Need(std::filesystem::is_directory(physical),"ordered folder provider changed type");
            size_t actualFiles=0;
            for(const auto& entry:std::filesystem::recursive_directory_iterator(physical)) {
                auto status=entry.symlink_status();
                Need(std::filesystem::is_directory(status) || std::filesystem::is_regular_file(status),
                     "linked or special ordered folder entry");
                if(std::filesystem::is_regular_file(status)) {
                    auto name=Relative(entry.path().lexically_relative(physical).generic_string());
                    auto listed=p.files.find(Lower(name));
                    Need(listed!=p.files.end() && listed->second.path==name,"ordered folder inventory changed");
                    Need(++actualFiles<=100000,"ordered folder inventory bound");
                }
            }
            Need(actualFiles==p.files.size(),"ordered folder inventory incomplete");
            for(auto& [_,file]:p.files) {auto value=CheckedPath(physical,file.path);
                Need(std::filesystem::is_regular_file(value) && std::filesystem::file_size(value)==file.bytes,"ordered loose file changed");}
        } else {
            Need(std::filesystem::is_regular_file(physical),"ordered archive provider changed type");
            auto cached=opened.find(p.path);
            if(cached!=opened.end()) {
                Need(p.archive.bytes==cached->second.archive.bytes && p.archive.sha256==cached->second.archive.sha256,
                     "conflicting identity for ordered archive views");
                p.handle=cached->second.handle;p.blockFiles=cached->second.blockFiles;continue;
            }
            Need(HashFile(physical,p.archive.bytes)==p.archive.sha256,"ordered archive SHA256 differs");
            mpq_archive_s* handle=nullptr;Need(libmpq__archive_open(&handle,physical.string().c_str(),-1)==0 && handle,"ordered MPQ open failed; no fallback");
            p.handle=std::shared_ptr<mpq_archive_s>(handle,[](mpq_archive_s* h){libmpq__archive_close(h);});
            Need(handle->mpq_header.version<=1,"unsupported ordered MPQ dialect");
            auto count=handle->mpq_header.hash_table_count;
            Need(count>0 && count<=(1u<<24) && (count&(count-1))==0,"ordered MPQ hash table bound");
            for(uint32_t i=0;i<handle->mpq_header.block_table_count;i++)
                Need(!(handle->mpq_block[i].flags&0x00100000u),"MPQ delta-patch members unsupported; no fallback");
            p.blockFiles=std::make_shared<std::vector<uint32_t>>(uint32_t(handle->mpq_header.block_table_count),0xffffffffu);
            for(uint32_t i=0;i<handle->files;i++) {
                auto block=handle->mpq_map[i].block_table_indices;
                Need(block<p.blockFiles->size(),"ordered MPQ block map bound");(*p.blockFiles)[block]=i;
            }
            opened.emplace(p.path,p);
        }
    }
    stage.active=true;Current()=std::move(stage);
}
// Client normal archive handles use locale/platform zero. A locale directory
// chooses the archive; non-neutral hash records are not silently selected.
inline int Locate(Provider& provider,const std::string& name,uint32_t& file) {
    auto* a=provider.handle.get();
    auto count=a->mpq_header.hash_table_count;uint32_t start=libmpq__hash_string(name.c_str(),0)&(count-1),i=start;
    auto hashA=libmpq__hash_string(name.c_str(),0x100),hashB=libmpq__hash_string(name.c_str(),0x200);
    do {const auto& h=a->mpq_hash[i];if(h.block_table_index==0xffffffffu)return 0;
        if(h.block_table_index!=0xfffffffeu && h.hash_a==hashA && h.hash_b==hashB && h.locale==0 && (h.platform&255)==0) {
            Need(h.block_table_index<a->mpq_header.block_table_count,"ordered MPQ block index invalid");
            if(a->mpq_block[h.block_table_index].flags&0x02000000u)return -1;
            Need(a->mpq_block[h.block_table_index].flags&0x80000000u,"ordered MPQ absent block entry");
            file=(*provider.blockFiles)[h.block_table_index];Need(file<a->files,"ordered MPQ block map invalid");return 1;
        }
        i=(i+1)&(count-1);
    } while(i!=start);return 0;
}
inline bool ReadArchive(Provider& p,const std::string& name,std::vector<char>& out,bool& deleted,uint64_t maximum=MaxMember) {
    uint32_t file=0;int found=Locate(p,name,file);deleted=found<0;if(found<=0)return false;
    auto* archive=p.handle.get();auto block=archive->mpq_map[file].block_table_indices;
    Need(!(archive->mpq_block[block].flags&0x00010000u),"encrypted ordered MPQ members unsupported; no fallback");
    libmpq__off_t size=0,transferred=0;Need(libmpq__file_unpacked_size(p.handle.get(),file,&size)==0 && size>=0,
        "ordered member size bound");
    Need(uint64_t(size)<=maximum,name=="(listfile)"?"ordered listfile byte bound":"ordered member size bound");out.resize(size_t(size));
    if(size)Need(libmpq__file_read(p.handle.get(),file,reinterpret_cast<uint8_t*>(out.data()),size,&transferred)==0 && transferred==size,
        "ordered member decode failed; no fallback");return true;
}
inline bool Read(const std::string& requested,std::vector<char>& out) {
    Need(Active(),"ordered mode is not configured");out.clear();std::string name=Relative(requested);
    for(auto& p:Current().providers) {
        if(p.kind=="directory") {
            auto found=p.files.find(Lower(name));if(found==p.files.end())continue;const auto& file=found->second;
            auto physical=CheckedPath(CheckedPath(Current().root,p.path),file.path);
            Need(HashFile(physical,file.bytes)==file.sha256,"ordered loose file SHA256 differs");
            out.resize(size_t(file.bytes));std::ifstream source(physical,std::ios::binary);
            if(file.bytes)source.read(out.data(),out.size());
            Need(bool(source),"ordered loose file read failed");return true;
        }
        std::string path=p.prefix.empty()?name:p.prefix+"/"+name;path=Relative(path);
        std::replace(path.begin(),path.end(),'/','\\');bool deleted=false;
        if(ReadArchive(p,path,out,deleted))return true;
        if(deleted)return false;
    }
    return false;
}
inline bool Exists(const std::string& requested) {
    std::string name=Relative(requested);
    for(auto& p:Current().providers) {
        if(p.kind=="directory") {if(p.files.count(Lower(name)))return true;continue;}
        std::string path=Relative(p.prefix.empty()?name:p.prefix+"/"+name);std::replace(path.begin(),path.end(),'/','\\');
        uint32_t file=0;int found=Locate(p,path,file);if(found)return found>0;
    }
    return false;
}
// Enumerate only the names the caller consumes. A complete client can contain
// far more than 100000 distinct names across its provider stack; unrelated
// textures/sounds must not fill the DBC extraction inventory. Input listfiles
// still have the original per-provider byte/count bounds, and every data path
// is validated before selection. No per-provider name vector or full text copy
// is retained alongside the one bounded decoded listfile.
inline std::vector<std::string> FileList(const std::string& prefix={},const std::string& suffix={}) {
    Need(Active(),"ordered mode is not configured");std::map<std::string,std::string> unique;
    const auto wantedPrefix=Lower(prefix),wantedSuffix=Lower(suffix);
    auto select=[&](std::string name) {
        name=Relative(name);const auto key=Lower(name);
        if(key.rfind(wantedPrefix,0)!=0 || key.size()<wantedSuffix.size() ||
           key.compare(key.size()-wantedSuffix.size(),wantedSuffix.size(),wantedSuffix)!=0)return;
        if(unique.find(key)!=unique.end())return;
        Need(unique.size()<100000,"ordered effective file count bound");
        std::replace(name.begin(),name.end(),'/','\\');unique.emplace(key,std::move(name));
    };
    for(auto& p:Current().providers) {
        if(p.kind=="directory") {for(auto& [_,file]:p.files)select(file.path);continue;}
        std::vector<char> raw;bool deleted=false;
        // Enforce the listfile limit before allocating or decoding the member.
        Need(ReadArchive(p,"(listfile)",raw,deleted,16u<<20) && !deleted,"ordered archive requires a readable listfile");
        size_t scanned=0,start=0;
        while(start<raw.size()) {
            size_t end=start;while(end<raw.size() && raw[end]!='\n')++end;
            size_t length=end-start;
            if(length && raw[start+length-1]=='\r')--length;
            if(length && raw[start+length-1]=='\0')--length;
            if(length && raw[start]!='(') {
                Need(++scanned<=100000,"ordered listfile count bound");
                Need(length<260,"unsupported ordered member path");
                auto name=Relative(std::string(raw.data()+start,length));
                if(p.prefix.empty())select(std::move(name));
                else {const auto view=Lower(p.prefix)+"/";
                    if(Lower(name).rfind(view,0)==0)select(name.substr(view.size()));}
            }
            start=end+1;
        }
    }
    std::vector<std::string> result;for(auto& [_,name]:unique)if(Exists(name))result.push_back(name);return result;
}
inline int Bootstrap(int& argc,char** argv) {
    if(argc==2 && std::string(argv[1])=="--esteria-order-capabilities") {
        std::puts("esteria-classical-ordered-providers-v1; archive/folder/prefix; no conversion qualification");return 0;
    }
    std::string manifest,root,sha,probe,memberProbe;std::vector<char*> remaining{argv[0]};bool any=false,list=false;
    for(int i=1;i<argc;i++) {std::string arg=argv[i];std::string* target=nullptr;
        if(arg=="--esteria-order-list") {Need(!list,"duplicate ordered list option");list=true;any=true;continue;}
        if(arg=="--esteria-order")target=&manifest;else if(arg=="--esteria-input-root")target=&root;
        else if(arg=="--esteria-order-sha256")target=&sha;else if(arg=="--esteria-order-probe")target=&probe;
        else if(arg=="--esteria-order-member-probe")target=&memberProbe;
        if(target) {any=true;Need(target->empty() && i+1<argc,"duplicate or incomplete ordered option");*target=argv[++i];}
        else {Need(arg.rfind("--esteria-",0)!=0,"unknown ordered option; no fallback");remaining.push_back(argv[i]);}
    }
    if(!any)return -1;
    for(size_t i=1;i<remaining.size();i++)Need(std::string(remaining[i])!="-i" && std::string(remaining[i])!="-d",
        "legacy input selection is forbidden in explicit ordered mode");
    Need(!manifest.empty() && !root.empty() && !sha.empty(),"explicit ordered manifest/root/SHA256 are required");Load(manifest,root,sha);
    argc=int(remaining.size());for(int i=0;i<argc;i++)argv[i]=remaining[i];argv[argc]=nullptr;
    Need(unsigned(list)+unsigned(!probe.empty())+unsigned(!memberProbe.empty())<=1,"conflicting ordered diagnostics");
    if(!memberProbe.empty()) {Need(argc==1,"ordered member probe takes no conversion arguments");Current().memberProbe=Relative(memberProbe);return -1;}
    if(list) {Need(argc==1,"ordered list takes no conversion arguments");for(auto& name:FileList())std::puts(name.c_str());return 0;}
    if(probe.empty())return -1;
    Need(argc==1,"ordered lookup probe takes no conversion arguments");std::vector<char> bytes;bool found=Read(probe,bytes);
    if(found)std::printf("{\"scope\":\"ordered-provider-lookup-only\",\"found\":true,\"bytes\":%zu,\"sha256\":\"%s\"}\n",bytes.size(),Digest(reinterpret_cast<const unsigned char*>(bytes.data()),bytes.size()).c_str());
    else std::puts("{\"scope\":\"ordered-provider-lookup-only\",\"found\":false}");
    return found?0:3;
}
}
#endif
