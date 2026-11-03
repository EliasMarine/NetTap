// Build-time check for libnettap_urandom.so, run by Dockerfile.zeek-live.
//
// With the library loaded, std::random_device's CPU sources must read
// /dev/urandom, and an explicit device file must be left alone. Without it,
// "default" and "rdrand" open no file at all, so the check fails.
#include <cstdio>
#include <filesystem>
#include <random>
#include <string>
#include <system_error>

namespace {

bool source_reads(const std::string& token, const std::string& path) {
  std::random_device device(token);
  for (const auto& entry : std::filesystem::directory_iterator("/proc/self/fd")) {
    std::error_code ignored;
    if (std::filesystem::read_symlink(entry.path(), ignored) == path) return true;
  }
  return false;
}

}  // namespace

int main() {
  struct Case {
    const char* token;
    const char* expected_file;
  };
  constexpr Case kCases[] = {
      {"default", "/dev/urandom"},
      {"rdrand", "/dev/urandom"},
      {"rdseed", "/dev/urandom"},
      {"/dev/random", "/dev/random"},
  };
  int failures = 0;
  for (const auto& c : kCases) {
    try {
      if (source_reads(c.token, c.expected_file)) continue;
      std::fprintf(stderr, "FAIL: random_device(\"%s\") does not read %s\n", c.token,
                   c.expected_file);
    } catch (const std::exception& e) {
      std::fprintf(stderr, "FAIL: random_device(\"%s\") threw: %s\n", c.token, e.what());
    }
    ++failures;
  }
  if (failures == 0) std::puts("random_device shim: ok");
  return failures == 0 ? 0 : 1;
}
