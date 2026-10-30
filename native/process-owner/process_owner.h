// Adapted from Russianranger/fta-launcher 7a9ce45988f295824d20c9ff7436a77a0baa4f07.
// Copyright (c) 2026 Russianranger; MIT license in FTA-MIT-LICENSE.txt.
#pragma once
#include <cstdint>
#include <array>
#include <limits>
#include <string>
#include <vector>

namespace esteria {
constexpr int running = std::numeric_limits<int>::min();
struct StartOptions {
    std::string executable;
    std::vector<std::string> arguments;
    std::vector<std::string> environment;
    std::string cwd, input, output, error;
};
// Handles are owned by this parent process. They are never caller-selected PIDs.
std::int64_t start(const StartOptions& options);
int wait_for(std::int64_t handle, std::int64_t timeout_ms);
int stop(std::int64_t handle, std::int64_t grace_ms);
// Observation only. Fails if the owned leader has already exited; never accepts a PID.
int process_id(std::int64_t handle);
// stdout read/stored, stderr read/stored, IO failures; no log content or secrets.
// Read once after wait_for completes to permit bounded completed-handle eviction.
std::array<std::int64_t,5> diagnostics(std::int64_t handle);
}
