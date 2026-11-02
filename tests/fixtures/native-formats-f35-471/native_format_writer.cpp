// Synthetic native serialization/row-reader reference. Exact pinned headers,
// Detour implementation and client readers are included without modification.
// This creates no owner assets and does not qualify a world or camera model.
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include "Define.h"
#include "MapDefines.h"
#include "VMapDefinitions.h"
#include "modelheaders.h"
#include "DBCfmt.h"
#include "DBCFileLoader.h"
#include "DetourNavMeshBuilder.h"
#include "map_file_format.inc"
#include "Engine/Source/BlizzardCore/SFile2-Core.h"
#include "WoW/Source/DB/Rec/gtBarberShopCostBaseRec.h"
#include "WoW/Source/DB/Rec/gtCombatRatingsRec.h"
#include "WoW/Source/DB/Rec/gtChanceToMeleeCritBaseRec.h"
#include "WoW/Source/DB/Rec/gtChanceToMeleeCritRec.h"
#include "WoW/Source/DB/Rec/gtChanceToSpellCritBaseRec.h"
#include "WoW/Source/DB/Rec/gtChanceToSpellCritRec.h"
#include "WoW/Source/DB/Rec/gtNPCManaCostScalerRec.h"
#include "WoW/Source/DB/Rec/gtOCTClassCombatRatingScalarRec.h"
#include "WoW/Source/DB/Rec/gtOCTRegenHPRec.h"
#include "WoW/Source/DB/Rec/gtRegenHPPerSptRec.h"
#include "WoW/Source/DB/Rec/gtRegenMPPerSptRec.h"
#include "WoW/Source/DB/Rec/PowerDisplayRec.h"

namespace fs=std::filesystem;
using Bytes=std::vector<unsigned char>;
template<class T>void append(Bytes& bytes,T const& value) {
    auto at=reinterpret_cast<unsigned char const*>(&value);
    bytes.insert(bytes.end(),at,at+sizeof(value));
}
void raw(Bytes& bytes,char const* value,std::size_t size) {bytes.insert(bytes.end(),value,value+size);}
void write(fs::path const& path,Bytes const& bytes) {
    fs::create_directories(path.parent_path());std::ofstream stream(path,std::ios::binary);
    stream.write(reinterpret_cast<char const*>(bytes.data()),bytes.size());
    if(!stream)throw std::runtime_error("reference output write failed");
}
void require(bool condition,char const* message) {if(!condition)throw std::runtime_error(message);}
struct DbcHeader {char magic[4];uint32 rows,columns,stride,strings;};
static_assert(sizeof(DbcHeader)==20);
static_assert(sizeof(map_fileheader)==44);
static_assert(sizeof(dtNavMeshParams)==28);

template<class Rec>void dbc(fs::path const& root,char const* name,Bytes row,char const* serverFormat) {
    require(row.size()==Rec::s_rowSize,"row bytes differ from actual client reader layout");
    Rec record;SFileImpl input(row);
    require(record.Read(&input,"\0")&&input.position==row.size(),"pinned client reader did not consume its full native row");
    Bytes truncated=row;truncated.pop_back();SFileImpl shortInput(truncated);
    require(!record.Read(&shortInput,"\0"),"pinned client reader accepted a truncated row");
    Bytes bytes;DbcHeader header{{'W','D','B','C'},1,Rec::s_numColumns,Rec::s_rowSize,1};
    append(bytes,header);bytes.insert(bytes.end(),row.begin(),row.end());bytes.push_back(0);
    write(root/"client"/name,bytes);
    // These selected full-width server formats contain only n/d/f/i/x fields.
    require(std::strspn(serverFormat,"ndfix")==std::strlen(serverFormat),"unexpected server field type");
    header.columns=std::strlen(serverFormat);header.stride=4*header.columns;
    bytes.clear();append(bytes,header);
    if(header.columns==2&&std::strcmp(serverFormat,"df")==0) {
        uint32 nativeId=3;float nativeValue=.75f;append(bytes,nativeId);append(bytes,nativeValue);
    }else bytes.resize(sizeof(header)+header.stride,0);
    bytes.push_back(0);
    write(root/"server"/name,bytes);
}

void serverReaderProjection(fs::path const& root) {
    Bytes packed;DbcHeader header{{'W','D','B','C'},2,6,15,1};append(packed,header);
    for(auto const& values:std::vector<std::vector<uint32>>{{7,3,17,99,201},{19,11,255,222,111}}) {
        append(packed,values[0]);append(packed,values[1]);uint32 offset=0;append(packed,offset);
        packed.insert(packed.end(),{static_cast<unsigned char>(values[2]),static_cast<unsigned char>(values[3]),static_cast<unsigned char>(values[4])});
    }
    packed.push_back(0);fs::path power=root/"server-reader/PowerDisplay-packed.dbc";write(power,packed);
    DBCFileLoader loader;require(loader.Load(power.string().c_str(),PowerDisplayfmt),"actual server loader rejected packed PowerDisplay header");
    require(loader.GetRowSize()==15&&loader.GetCols()==6&&loader.GetNumRows()==2,"actual server row stride differs");
    uint32 records=0;char** index=nullptr;char* table=loader.AutoProduceData(PowerDisplayfmt,records,index);
    require(table&&records==20&&index[7]&&index[19],"actual server PowerDisplay projection failed");
    uint32 first[2],second[2];std::memcpy(first,index[7],8);std::memcpy(second,index[19],8);
    require(first[0]==7&&first[1]==3&&second[0]==19&&second[1]==11,"actual server loader did not advance packed rows by15 or retained wrong fields");
    delete[] index;delete[] table;
    DBCFileLoader single;require(single.Load((root/"client/gtCombatRatings.dbc").string().c_str(),GtCombatRatingsfmt),"actual server GT header load failed");
    records=0;index=nullptr;table=single.AutoProduceData(GtCombatRatingsfmt,records,index);
    require(!table&&!index,"actual server unexpectedly projected one-field GT through df");
    DBCFileLoader indexed;require(indexed.Load((root/"server/gtCombatRatings.dbc").string().c_str(),GtCombatRatingsfmt),"actual server indexed GT load failed");
    records=0;table=indexed.AutoProduceData(GtCombatRatingsfmt,records,index);
    require(table&&records==4&&index[3],"actual server indexed GT projection failed");
    float projected=0;std::memcpy(&projected,index[3],4);require(projected==.75f,"actual server GT projection retained wrong float");
    delete[] index;delete[] table;
}

int main(int argc,char** argv)try {
    require(argc==2,"output directory required");fs::path root(argv[1]);
    uint32 endian=1;require(*reinterpret_cast<unsigned char*>(&endian)==1,"reference requires little-endian host");
    Bytes map;map_fileheader header{};
    std::memcpy(&header.mapMagic,MAP_MAGIC,4);header.versionMagic=MAP_VERSION_MAGIC;header.buildMagic=12340;
    map_areaHeader area{};std::memcpy(&area.fourcc,MAP_AREA_MAGIC,4);area.flags=MAP_AREA_NO_AREA;
    map_heightHeader height{};std::memcpy(&height.fourcc,MAP_HEIGHT_MAGIC,4);height.flags=MAP_HEIGHT_NO_HEIGHT;
    header.areaMapOffset=sizeof(header);header.areaMapSize=sizeof(area);
    header.heightMapOffset=sizeof(header)+sizeof(area);header.heightMapSize=sizeof(height);
    append(map,header);append(map,area);append(map,height);write(root/"world/maps/0000000.map",map);

    // VMAP prefixes only: body decoding and model closure stay loader gates.
    Bytes vmap;raw(vmap,VMAP::VMAP_MAGIC,8);write(root/"world/vmaps/000.vmtree",vmap);
    uint32 count=0;append(vmap,count);write(root/"world/vmaps/000_00_00.vmtile",vmap);
    vmap.resize(8);raw(vmap,"WMOD",4);uint32 chunkSize=8,rootWmo=0;append(vmap,chunkSize);append(vmap,rootWmo);
    write(root/"world/vmaps/reference.vmo",vmap);
    vmap.resize(8);write(root/"world/vmaps"/VMAP::GAMEOBJECT_MODELS,vmap);

    dtNavMeshParams params{};params.tileWidth=1.f;params.tileHeight=1.f;params.maxTiles=1;params.maxPolys=1;
    Bytes index;append(index,params);write(root/"world/mmaps/000.mmap",index);
    unsigned short verts[]={0,0,0,1,0,0,0,0,1};
    unsigned short polys[]={0,1,2,0xffff,0xffff,0xffff};unsigned short flags[]={1};unsigned char areas[]={0};
    dtNavMeshCreateParams create{};create.verts=verts;create.vertCount=3;create.polys=polys;
    create.polyFlags=flags;create.polyAreas=areas;create.polyCount=1;create.nvp=3;
    create.walkableHeight=2.f;create.walkableRadius=.5f;create.walkableClimb=.5f;
    create.bmax[0]=create.bmax[1]=create.bmax[2]=1.f;create.cs=1.f;create.ch=1.f;
    unsigned char* nativeData=nullptr;int nativeSize=0;
    require(dtCreateNavMeshData(&create,&nativeData,&nativeSize),"exact pinned Detour failed to build synthetic triangle");
    MmapTileHeader tile{};tile.size=nativeSize;tile.usesLiquids=1;
    tile.recastConfig={50.f,1,1,1,0,2,2,1,1.f,1.f,1.f,1.f};
    Bytes tileBytes;append(tileBytes,tile);tileBytes.insert(tileBytes.end(),nativeData,nativeData+nativeSize);
    write(root/"world/mmaps/0000000.mmtile",tileBytes);
    dtNavMesh mesh;require(dtStatusSucceed(mesh.init(&params)),"exact pinned Detour index init failed");
    require(dtStatusSucceed(mesh.addTile(nativeData,nativeSize,DT_TILE_FREE_DATA,0,nullptr)),"exact pinned Detour failed to load its synthetic tile");

    ModelHeader camera{};std::memcpy(camera.id,"MD20",4);uint32 version=264;std::memcpy(camera.version,&version,4);
    Bytes cameraBytes;append(cameraBytes,camera);write(root/"world/Cameras/reference.m2",cameraBytes);
    Bytes oneFloat;float value=.25f;append(oneFloat,value);
#define SINGLE(Rec,Format,Name) dbc<Rec>(root,Name,oneFloat,Format)
    SINGLE(gtBarberShopCostBaseRec,GtBarberShopCostBasefmt,"gtBarberShopCostBase.dbc");
    SINGLE(gtCombatRatingsRec,GtCombatRatingsfmt,"gtCombatRatings.dbc");
    SINGLE(gtChanceToMeleeCritBaseRec,GtChanceToMeleeCritBasefmt,"gtChanceToMeleeCritBase.dbc");
    SINGLE(gtChanceToMeleeCritRec,GtChanceToMeleeCritfmt,"gtChanceToMeleeCrit.dbc");
    SINGLE(gtChanceToSpellCritBaseRec,GtChanceToSpellCritBasefmt,"gtChanceToSpellCritBase.dbc");
    SINGLE(gtChanceToSpellCritRec,GtChanceToSpellCritfmt,"gtChanceToSpellCrit.dbc");
    SINGLE(gtNPCManaCostScalerRec,GtNPCManaCostScalerfmt,"gtNPCManaCostScaler.dbc");
    SINGLE(gtOCTRegenHPRec,GtOCTRegenHPfmt,"gtOCTRegenHP.dbc");
    SINGLE(gtRegenHPPerSptRec,GtRegenHPPerSptfmt,"gtRegenHPPerSpt.dbc");
    SINGLE(gtRegenMPPerSptRec,GtRegenMPPerSptfmt,"gtRegenMPPerSpt.dbc");
    Bytes scalar;uint32 id=1;append(scalar,id);append(scalar,value);
    dbc<gtOCTClassCombatRatingScalarRec>(root,"gtOCTClassCombatRatingScalar.dbc",scalar,GtOCTClassCombatRatingScalarfmt);
    Bytes power;uint32 actualType=0,stringOffset=0;append(power,id);append(power,actualType);append(power,stringOffset);
    power.insert(power.end(),{255,128,0});
    dbc<PowerDisplayRec>(root,"PowerDisplay.dbc",power,PowerDisplayfmt);
    serverReaderProjection(root);
    std::cout<<"{\"mapHeaderBytes\":"<<sizeof(map_fileheader)<<",\"mmapHeaderBytes\":"<<sizeof(MmapTileHeader)
        <<",\"mmapIndexBytes\":"<<sizeof(dtNavMeshParams)<<",\"detourHeaderBytes\":"<<sizeof(dtMeshHeader)
        <<",\"cameraHeaderBytes\":"<<sizeof(ModelHeader)<<",\"clientReadersExecuted\":12"
        <<",\"clientTruncationsRejected\":12,\"actualDetourTriangleBuiltAndLoaded\":true"
        <<",\"serverPowerDisplayTwoPackedRowsLoaded\":true,\"serverGtSingleFloatProjectionRejected\":true"
        <<",\"serverGtIndexedProjectionLoaded\":true,\"gameplayQualified\":false}\n";
    return 0;
}catch(std::exception const& failure){std::cerr<<failure.what()<<'\n';return 1;}
