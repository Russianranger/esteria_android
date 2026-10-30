// Qualification glue: all parsing, module selection and reload use the pinned
// ConfigMgr linked from common. This creates only a new disposable directory.
#include "Config.h"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace fs = std::filesystem;

static void require(bool value, char const* message)
{
    if (!value)
        throw std::runtime_error(message);
}

static void write(fs::path const& path, std::string const& text)
{
    fs::create_directories(path.parent_path());
    std::ofstream stream(path);
    stream << text;
    stream.close();
    require(!stream.fail(), "fixture write failed");
}

static void qualify(fs::path const& main, fs::path const& physicalMain, int value)
{
    auto module = physicalMain.parent_path() / "modules/fixture.conf";
    write(physicalMain, "[fixture]\nFixture.Main = 1\n");
    write(module, "[fixture]\nFixture.Module = " + std::to_string(value) + "\n");
    sConfigMgr->Configure(main.generic_string(), {}, "fixture.conf");
    require(sConfigMgr->LoadAppConfigs(), "main config failed");
    require(sConfigMgr->LoadModulesConfigs(false, false), "module config failed");
    require(sConfigMgr->GetOption<int>("Fixture.Main", -1, false) == 1, "main value missing");
    require(sConfigMgr->GetOption<int>("Fixture.Module", -1, false) == value, "wrong module directory");
    write(module, "[fixture]\nFixture.Module = " + std::to_string(value + 1) + "\n");
    require(sConfigMgr->Reload(), "reload failed");
    require(sConfigMgr->GetOption<int>("Fixture.Module", -1, false) == value + 1, "module reload stale");
}

int main(int argc, char** argv)
{
    try
    {
        require(argc == 2, "one new absolute fixture directory required");
        fs::path root(argv[1]);
        require(root.is_absolute() && !fs::exists(root) && fs::create_directory(root), "fixture already exists");
        auto defaultPath = sConfigMgr->GetConfigPath();
        require(!defaultPath.empty(), "default config path missing");
        // This is the apps' existing default-resolution sequence. No source or
        // installed default configuration is written or opened by this test.
        sConfigMgr->Configure(defaultPath + "worldserver.conf", {}, "fixture.conf");
        require((fs::path(sConfigMgr->GetFilename()).parent_path() / "modules").lexically_normal() ==
                fs::path(defaultPath + "modules").lexically_normal(), "default module path changed");
        fs::current_path(root);
        qualify(root / "absolute generation/worldserver.conf", root / "absolute generation/worldserver.conf", 101);
        qualify("relative/worldserver.conf", root / "relative/worldserver.conf", 201);
        qualify("worldserver.conf", root / "worldserver.conf", 301);
        // A CWD module is present now. Selecting another main config with no
        // sibling module must not silently load that CWD configuration.
        auto missing = root / "missing/worldserver.conf";
        write(missing, "[fixture]\nFixture.Main = 1\n");
        sConfigMgr->Configure(missing.generic_string(), {}, "fixture.conf");
        require(sConfigMgr->LoadAppConfigs(), "missing-module main config failed");
        (void)sConfigMgr->LoadModulesConfigs(false, false);
        require(sConfigMgr->GetOption<int>("Fixture.Module", -1, false) == -1, "missing module adopted another directory");
        require(sConfigMgr->GetConfigPath() == defaultPath, "default path API changed");
        std::cout << "ESTERIA_CONFIG_PATH_REFERENCE_PASS absolute relative bare reload default missing\n";
        return 0;
    }
    catch (std::exception const&)
    {
        std::cerr << "ConfigMgr path reference failed\n";
        return 1;
    }
}
