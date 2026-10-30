// Calls the pinned server's real crypto and AccountMgr normalization functions.
// This is an isolated qualification binary; no game account secrets are inputs.
#include "SRP6.h"
#include "Util.h"
#include <algorithm>
#include <cstdio>
#include <string>

int main()
{
    using Acore::Crypto::SRP6;
    SRP6::Salt salt{};
    for (std::size_t i = 0; i < salt.size(); ++i)
        salt[i] = static_cast<uint8>(i);
    auto expected = HexStrToByteArray<32>("8d228fd2f89a39f80b6c27cf32bbcc9218e7026868bb5162fe6916785cb5450b");
    std::string user = "Admin", password = "pAsSwOrD";
    Utf8ToUpperOnlyLatin(user);
    Utf8ToUpperOnlyLatin(password);
    if (user != "ADMIN" || password != "PASSWORD" || !SRP6::CheckLogin(user, password, salt, expected))
        return 1;
    if (SRP6::CheckLogin(user, "PASSW0RD", salt, expected))
        return 2;
    auto reversed = expected;
    std::reverse(reversed.begin(), reversed.end());
    if (SRP6::CheckLogin(user, password, salt, reversed))
        return 3;
    salt[0] ^= 1;
    if (SRP6::CheckLogin(user, password, salt, expected))
        return 4;
    std::puts("{\"formatVersion\":1,\"scope\":\"actual-server-common-SRP6-fixed-vector\","
              "\"asciiNormalizationVerified\":true,\"sourceVectorVerified\":true,"
              "\"wrongPasswordRejected\":true,\"wrongByteOrderRejected\":true,"
              "\"wrongSaltRejected\":true,\"networkAuthProtocolQualified\":false}");
    return 0;
}
