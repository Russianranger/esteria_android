// Compile against the actual pinned/patched hook header without a precompiled
// header. Its event tables must declare their own integer and size types.
#include "Hooks.h"
static_assert(sizeof(EventEntry{}.id) == 1);
static_assert(Hooks::REGTYPE_COUNT > 0);
