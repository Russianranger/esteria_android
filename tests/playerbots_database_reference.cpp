// Qualification glue only. The loader, pool, updater and prepared statements are
// linked from the exact pinned server's database/common targets without copies.
#include "Config.h"
#include "DBUpdater.h"
#include "DatabaseEnv.h"
#include "DatabaseLoader.h"
#include "Log.h"
#include "MySQLThreading.h"
#include "OpenSSLCrypto.h"
#include <filesystem>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#ifndef MOD_PLAYERBOTS
#error "The actual database target must be compiled with playerbots enabled"
#endif

static_assert(DatabaseLoader::DATABASE_PLAYERBOTS == 8);

int main(int argc, char** argv)
{
    if (argc == 2 && std::string(argv[1]) == "--help")
    {
        std::cout << "Disposable playerbots database reference: --config <absolute private fixture config>\n";
        return 0;
    }
    if (argc != 3 || std::string(argv[1]) != "--config" || !std::filesystem::path(argv[2]).is_absolute())
        return 2;

    sConfigMgr->Configure(argv[2], std::vector<std::string>(argv, argv + argc), "playerbots.conf");
    if (!sConfigMgr->LoadAppConfigs() || !sConfigMgr->LoadModulesConfigs(false, false))
        return 1;
    (void)sConfigMgr->OverrideWithEnvVariablesIfAny();
    sLog->Initialize();

    OpenSSLCrypto::threadsSetup();
    std::shared_ptr<void> sslCleanup(nullptr, [](void*) { OpenSSLCrypto::threadsCleanup(); });
    MySQL::Library_Init();
    std::shared_ptr<void> mysqlCleanup(nullptr, [](void*) { MySQL::Library_End(); });

    // Exact loader sequence from mod-playerbots/src/Script/Playerbots.cpp:
    // PlayerbotsDatabaseScript::OnDatabasesLoading. Its module list is empty;
    // DBUpdater<PlayerbotsDatabaseConnection> selects the module's own source
    // directory and updates_include. No game scripts or playerbot AI are run.
    DatabaseLoader playerbotLoader("server.playerbots");
    playerbotLoader.SetUpdateFlags(sConfigMgr->GetOption<bool>("Playerbots.Updates.EnableDatabases", true)
                                      ? DatabaseLoader::DATABASE_PLAYERBOTS
                                      : 0);
    playerbotLoader.AddDatabase(PlayerbotsDatabase, "Playerbots");
    if (!playerbotLoader.Load())
        return 1; // DatabaseLoader closes every pool it opened on failure.
    PlayerbotsDatabase.Close();
    if (DBUpdaterUtil::GetFailedUpdateCount())
        return 1;

    std::cout << "ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE statements="
              << MAX_PLAYERBOTS_STATEMENTS << " mysqlClientLibrary=" << MySQL::GetLibraryVersion() << '\n';
    return 0;
}
