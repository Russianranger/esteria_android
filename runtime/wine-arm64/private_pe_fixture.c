/* Source-owned PE mapping fixture; no game data or private user inputs. */
#include <windows.h>
#include <stdint.h>

__declspec(dllexport) volatile LONG fixture_private = 0x13579bdf;
__declspec(dllexport) const unsigned char fixture_readonly[64] = "Esteria image mapping fixture";
__declspec(dllexport) unsigned char fixture_zero[8192];
__declspec(dllexport) volatile LONG *fixture_relocated_pointer = &fixture_private;
/* The final objcopy command sets IMAGE_SCN_MEM_SHARED on this real PE section. */
__declspec(dllexport) __attribute__((section(".shared"))) volatile LONG fixture_shared = 0x11223344;
__declspec(dllexport) unsigned long fixture_answer(void) {
    return (unsigned long)fixture_private ^ (unsigned long)fixture_readonly[0] ^ fixture_zero[8191];
}
