// Test-only bounded in-memory replacement for the archive I/O entry point.
// It runs unchanged pinned client row readers. It is not an MPQ reader or engine
// implementation and must never be included by a production target.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <utility>
#include <vector>

class SFileImpl {
public:
    std::vector<unsigned char> bytes;
    std::size_t position=0;
    explicit SFileImpl(std::vector<unsigned char> input):bytes(std::move(input)){}
};

inline int32_t SFileReadFile(SFileImpl* file,void* output,std::size_t count,void*,void*,int) {
    if(!file||count>file->bytes.size()-file->position)return 0;
    std::memcpy(output,file->bytes.data()+file->position,count);
    file->position+=count;
    return static_cast<int32_t>(count);
}
