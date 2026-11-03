// Route std::random_device's hardware sources to the kernel RNG.
//
// Some AMD CPUs (seen on the GMKtec G11, Ryzen Embedded R2514) return the
// same RDRAND/RDSEED value on every call; the kernel logs "RDRAND is not
// reliable on this platform; disabling." but programs can still execute the
// instruction. libstdc++'s std::random_device("default") uses it whenever
// CPUID advertises it, so Broker gave every Zeek process the same endpoint ID
// and the Zeek cluster never peered: no logs, empty dashboard (Chain 23).
//
// Loaded through /etc/ld.so.preload in the zeek-live image. LD_PRELOAD would
// be ignored: zeek has file capabilities, which puts ld.so in secure mode.
#include <dlfcn.h>

#include <cstdio>
#include <cstdlib>
#include <string>

namespace {

using InitFn = void (*)(void*, const std::string&);

constexpr const char kInitSymbol[] =
    "_ZNSt13random_device7_M_initERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE";

bool is_hardware_token(const std::string& token) {
  return token == "default" || token == "rdseed" || token == "rdrand" ||
         token == "rdrnd";
}

}  // namespace

// Same symbol as libstdc++'s std::random_device::_M_init(const std::string&),
// so this definition wins for every caller in the process.
void nettap_random_device_init(void* self, const std::string& token) __asm__(
    "_ZNSt13random_device7_M_initERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE");

void nettap_random_device_init(void* self, const std::string& token) {
  static const auto real = reinterpret_cast<InitFn>(dlsym(RTLD_NEXT, kInitSymbol));
  if (real == nullptr) {
    std::fputs("nettap: libstdc++ random_device::_M_init not found\n", stderr);
    std::abort();
  }
  static const std::string urandom = "/dev/urandom";
  real(self, is_hardware_token(token) ? urandom : token);
}
