/* Synthetic MPQ fixture writer plus the actual adapted reader. No game assets. */
#include "EsteriaArchiveOrder.h"
#include <fstream>
#include <iterator>

struct Entry { std::string name,data; uint32_t flags=0x81000000u; uint16_t locale=0; };
static std::string Unhex(const std::string& value) {
    if(value=="-")return {};
    EsteriaOrder::Need(value.size()%2==0,"fixture hex");std::string out;
    for(size_t i=0;i<value.size();i+=2)out.push_back(char(std::stoul(value.substr(i,2),nullptr,16)));
    return out;
}
static void Create(const char* path,const char* inputPath) {
    std::ifstream input(inputPath);std::string line;std::vector<Entry> entries;std::string list;
    std::vector<uint32_t> unpacked;
    while(std::getline(input,line)) {auto f=EsteriaOrder::Fields(line);EsteriaOrder::Need(f.size()==4 || f.size()==5,"fixture fields");
        Entry e;e.name=f[0];e.flags=uint32_t(std::stoull(f[1]));e.locale=uint16_t(std::stoul(f[2]));e.data=Unhex(f[3]);
        list+=e.name+"\r\n";unpacked.push_back(f.size()==5?uint32_t(std::stoul(f[4])):uint32_t(e.data.size()));entries.push_back(e);}
    entries.push_back({"(listfile)",list,0x81000000u,0});uint32_t slots=2;while(slots<entries.size()*2)slots*=2;
    unpacked.push_back(list.size());
    std::vector<mpq_hash_s> hashes(slots);std::memset(hashes.data(),255,hashes.size()*sizeof(mpq_hash_s));
    std::vector<mpq_block_s> blocks;std::string data;
    for(uint32_t i=0;i<entries.size();i++) {auto& e=entries[i];std::replace(e.name.begin(),e.name.end(),'/','\\');
        uint32_t index=libmpq__hash_string(e.name.c_str(),0)&(slots-1);while(hashes[index].block_table_index!=0xffffffffu)index=(index+1)&(slots-1);
        hashes[index]={libmpq__hash_string(e.name.c_str(),0x100),libmpq__hash_string(e.name.c_str(),0x200),e.locale,0,i};
        blocks.push_back({uint32_t(32+data.size()),uint32_t(e.data.size()),unpacked[i],e.flags});data+=e.data;}
    uint32_t hashOffset=uint32_t(32+data.size()),blockOffset=hashOffset+uint32_t(hashes.size()*16);
    std::array<uint32_t,8> header={0x1a51504d,32,blockOffset+uint32_t(blocks.size()*16),3u<<16,hashOffset,blockOffset,slots,uint32_t(blocks.size())};
    std::vector<uint32_t> hashWords(hashes.size()*4),blockWords(blocks.size()*4);
    std::memcpy(hashWords.data(),hashes.data(),hashes.size()*16);std::memcpy(blockWords.data(),blocks.data(),blocks.size()*16);
    EsteriaOrder::Need(libmpq__encrypt_block(hashWords.data(),hashWords.size()*4,libmpq__hash_string("(hash table)",0x300))==0,"fixture hash encryption");
    EsteriaOrder::Need(libmpq__encrypt_block(blockWords.data(),blockWords.size()*4,libmpq__hash_string("(block table)",0x300))==0,"fixture block encryption");
    std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(header.data()),32);out.write(data.data(),data.size());
    out.write(reinterpret_cast<const char*>(hashWords.data()),hashWords.size()*4);out.write(reinterpret_cast<const char*>(blockWords.data()),blockWords.size()*4);
    EsteriaOrder::Need(bool(out),"fixture write");
}
int main(int argc,char** argv) {
    try {
        if(argc==4 && std::string(argv[1])=="--create-fixture") {Create(argv[2],argv[3]);return 0;}
        bool mapArguments=argc>1 && std::string(argv[1])=="--check-map-conversion-argv";
        bool vmapArguments=argc>1 && std::string(argv[1])=="--check-vmap-conversion-argv";
        if(mapArguments || vmapArguments) {
            // Fixture-only dispatch. The production Bootstrap parses the exact
            // conversion arguments, but no extractor main or asset conversion runs.
            for(int i=1;i<argc;i++){argv[i]=argv[i+1];}
            --argc;
            int result=EsteriaOrder::Bootstrap(argc,argv);
            EsteriaOrder::Need(result==-1 && EsteriaOrder::Active(),"actual ordered conversion argument parsing failed");
            if(mapArguments)EsteriaOrder::Need(argc==5 && std::string(argv[1])=="-o" && std::string(argv[2])=="owned-output" &&
                std::string(argv[3])=="-e" && std::string(argv[4])=="7","map conversion arguments changed");
            else EsteriaOrder::Need(argc==1,"vmap conversion arguments changed");
            std::puts("{\"scope\":\"actual-ordered-bootstrap-only\",\"conversionExecuted\":false}");return 0;
        }
        int status=EsteriaOrder::Bootstrap(argc,argv);if(status>=0)return status;
        if(!EsteriaOrder::MemberProbe().empty()) {std::vector<char> bytes;bool found=EsteriaOrder::Read(EsteriaOrder::MemberProbe(),bytes);
            return EsteriaOrder::EmitProbe(bytes.data(),bytes.size(),found);}
        if(EsteriaOrder::Active() && argc==2 && std::string(argv[1])=="--list") {
            for(auto& name:EsteriaOrder::FileList())std::puts(name.c_str());
            return 0;}
        throw std::runtime_error("reference requires an explicit ordered lookup or list");
    } catch(std::exception const& error) {std::fprintf(stderr,"ordered fixture refused: %s\n",error.what());return 2;}
}
