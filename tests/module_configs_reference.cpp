// Qualification glue linked to the actual pinned ConfigMgr/common target.
// Every write is inside a newly created sibling fixture, never its input tree.
#include "Config.h"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
static std::string const prefix = "EsteriaQualification.Module.";
static void require(bool value)
{
    if (!value) throw std::runtime_error("module configuration reference rejected");
}
static std::string read(fs::path const& path)
{
    require(fs::is_regular_file(fs::symlink_status(path)) &&
            fs::canonical(path.parent_path()) == path.parent_path().lexically_normal());
    auto size = fs::file_size(path);
    require(size <= 4 * 1024 * 1024);
    std::ifstream input(path, std::ios::binary);
    std::string value(size, '\0');
    input.read(value.data(), size);
    require(input.good() && input.peek() == std::char_traits<char>::eof());
    return value;
}
static void write(fs::path const& path, std::string const& value)
{
    std::ofstream output(path, std::ios::binary);
    output << value;
    output.close();
    require(!output.fail());
}
int main(int argc, char** argv)
{
    try
    {
        require(argc == 3 && std::string(argv[1]) == "--config");
        fs::path plan(argv[2]);
        require(plan.is_absolute());
        std::istringstream lines(read(plan));
        std::string sourceName, list, extra;
        require(bool(std::getline(lines, sourceName)) && bool(std::getline(lines, list)) &&
                !std::getline(lines, extra));
        fs::path source(sourceName);
        require(source.is_absolute() && fs::canonical(source) == source.lexically_normal());
        std::vector<std::string> names;
        std::set<std::string> seen;
        std::istringstream choices(list);
        for (std::string name; std::getline(choices, name, ',');)
        {
            require(!name.empty() && name.size() <= 128 && name.ends_with(".conf") &&
                    name.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-") == std::string::npos &&
                    name != "." && name != ".." && seen.insert(name).second);
            names.push_back(name);
            require(names.size() <= 256);
        }
        require(!names.empty() && list.back() != ',');
        auto root = plan.parent_path() / "module-fixture";
        require(!fs::exists(root) && fs::create_directory(root));
        require(fs::create_directory(root / "modules"));
        auto main = read(source / "worldserver.conf");
        require(main.find(prefix) == std::string::npos);
        write(root / "worldserver.conf", main);
        std::vector<std::string> originals;
        for (std::size_t index = 0; index < names.size(); ++index)
        {
            auto original = read(source / "modules" / names[index]);
            require(original.find(prefix) == std::string::npos);
            originals.push_back(original);
            write(root / "modules" / names[index], original + "\n" + prefix + std::to_string(index) + " = 101\n");
        }
        sConfigMgr->Configure((root / "worldserver.conf").generic_string(), {}, list);
        require(sConfigMgr->LoadAppConfigs());
        (void)sConfigMgr->LoadModulesConfigs(false, false);
        require(sConfigMgr->GetKeysByString(prefix).size() == names.size());
        for (std::size_t index = 0; index < names.size(); ++index)
        {
            require(sConfigMgr->GetOption<int>(prefix + std::to_string(index), -1, false) == 101);
            write(root / "modules" / names[index], originals[index] + "\n" + prefix + std::to_string(index) + " = 202\n");
        }
        // These are actual parsed launcher policy values, not fixture defaults.
        require(sConfigMgr->GetOption<int>("Eluna.Enabled", -1, false) == 0 &&
                sConfigMgr->GetOption<int>("AiPlayerbot.CommandServerPort", -1, false) == 0 &&
                sConfigMgr->GetOption<int>("AiPlayerbot.RandomBotAutologin", -1, false) == 0 &&
                sConfigMgr->GetOption<int>("AiPlayerbot.MaxAddedBots", -1, false) == 4);
        require(sConfigMgr->Reload() && sConfigMgr->GetKeysByString(prefix).size() == names.size());
        for (std::size_t index = 0; index < names.size(); ++index)
        {
            require(sConfigMgr->GetOption<int>(prefix + std::to_string(index), -1, false) == 202);
            require(read(source / "modules" / names[index]) == originals[index]);
        }
        require(read(source / "worldserver.conf") == main);
        std::cout << "ESTERIA_MODULE_CONFIG_REFERENCE_PASS files=" << names.size() << " reload=1 sourcePreserved=1\n";
        return 0;
    }
    catch (std::exception const&)
    {
        std::cerr << "Module configuration reference failed\n";
        return 1;
    }
}
