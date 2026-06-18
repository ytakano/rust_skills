// Implementation of the C++ trace helper. Copy into the C++ project.
// See ../../reference/trace-contract.md.
//
// Design notes:
//  - Open TRACE_OUT with truncation once, on first use.
//  - Flush after every event so traces survive crashes / non-zero exits.
//  - A single mutex guards both the seq counter and the write, so concurrent
//    callers cannot interleave a line or reuse a seq.
//  - Do NOT emit pointers, wall-clock time, or internal symbol names.
#include "trace.h"

#include <cstdlib>
#include <fstream>
#include <mutex>

namespace trace {
namespace {

std::mutex g_mutex;
std::ofstream g_out;
bool g_init = false;
bool g_enabled = false;
long g_seq = 0;

void ensure_open() {
  if (g_init) return;
  g_init = true;
  const char* path = std::getenv("TRACE_OUT");
  if (path && *path) {
    g_out.open(path, std::ios::out | std::ios::trunc);
    g_enabled = g_out.is_open();
  }
}

std::string escape(const std::string& s) {
  std::string out;
  for (char c : s) {
    if (c == '"' || c == '\\') out += '\\';
    out += c;
  }
  return out;
}

}  // namespace

void trace_event(const std::string& event,
                 std::initializer_list<Param> params) {
  std::lock_guard<std::mutex> lock(g_mutex);
  ensure_open();
  if (!g_enabled) return;

  const char* run_id = std::getenv("RUN_ID");
  g_out << "{\"version\":1"
        << ",\"run_id\":\"" << escape(run_id ? run_id : "cpp-run") << "\""
        << ",\"seq\":" << ++g_seq
        << ",\"impl\":\"cpp\""
        << ",\"event\":\"" << escape(event) << "\""
        << ",\"params\":{";
  bool first = true;
  for (const auto& p : params) {
    if (!first) g_out << ",";
    first = false;
    g_out << "\"" << escape(p.first) << "\":\"" << escape(p.second) << "\"";
  }
  g_out << "}}\n";
  g_out.flush();
}

}  // namespace trace

// Example call sites (delete — for reference only):
//   trace::trace_event("Start", {{"session", session_id}});
//   trace::trace_event("HeaderParsed", {{"session", session_id}, {"kind", kind}});
//   trace::trace_event("ErrorRaised", {{"code", error_code}});
