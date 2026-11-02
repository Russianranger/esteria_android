// Test-only assertion bridge for the unchanged DBCFileLoader source. This
// substitutes no file-loader, field-offset or record-production behavior.
#pragma once
#include <cstdio>
#include <stdexcept>
#define ASSERT(condition, ...) do {if(!(condition))throw std::runtime_error("native loader assertion: " #condition);} while(false)
