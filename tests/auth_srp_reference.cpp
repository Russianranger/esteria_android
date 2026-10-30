// Fixed test-only credentials; actual pinned server SRP6 challenge/proof methods.
#include "SRP6.h"
#include "Util.h"
#include <algorithm>
#include <cctype>
#include <iostream>
#include <string>

template <class Bytes> void PrintHex(Bytes const& bytes)
{
    char const hex[] = "0123456789abcdef";
    for (auto value : bytes)
        std::cout << hex[value >> 4] << hex[value & 15];
    std::cout << '\n';
}

int main()
{
    using Acore::Crypto::SRP6;
    SRP6::Salt salt{};
    for (std::size_t i = 0; i < salt.size(); ++i)
        salt[i] = static_cast<uint8>(i);
    auto verifier = HexStrToByteArray<32>("8d228fd2f89a39f80b6c27cf32bbcc9218e7026868bb5162fe6916785cb5450b");
    SRP6 server("ADMIN", salt, verifier);
    PrintHex(server.B);
    std::cout.flush();
    std::string publicHex, proofHex;
    if (!std::getline(std::cin, publicHex) || !std::getline(std::cin, proofHex) ||
        publicHex.size() != 64 || proofHex.size() != 40 ||
        !std::all_of(publicHex.begin(), publicHex.end(), [](unsigned char c) { return std::isxdigit(c); }) ||
        !std::all_of(proofHex.begin(), proofHex.end(), [](unsigned char c) { return std::isxdigit(c); }))
        return 2;
    auto publicA = HexStrToByteArray<32>(publicHex);
    auto proof = HexStrToByteArray<20>(proofHex);
    auto key = server.VerifyChallengeResponse(publicA, proof);
    if (!key)
    {
        std::cout << "rejected\n";
        return 3;
    }
    PrintHex(SRP6::GetSessionVerifier(publicA, proof, *key));
    PrintHex(*key);
    return 0;
}
