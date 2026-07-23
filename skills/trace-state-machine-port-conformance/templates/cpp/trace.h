// Minimal trace instrumentation for the C++ original.
// Copy into the C++ project and adapt namespace/build wiring.
// See ../../reference/trace-contract.md for the format and output contract.
//
// Emits JSON Lines to the file named by the TRACE_OUT env var.
// When TRACE_OUT is unset, tracing is a no-op (zero behavioral impact).
#ifndef PORT_CONFORMANCE_TRACE_H
#define PORT_CONFORMANCE_TRACE_H

#include <initializer_list>
#include <string>
#include <utility>

namespace trace {

// Each value is emitted as a JSON string. Keep params semantic, not internal.
using Param = std::pair<std::string, std::string>;

// Thread-safe; atomically increments the shared `seq`. No-op if TRACE_OUT unset.
void trace_event(const std::string& event,
                 std::initializer_list<Param> params = {});

}  // namespace trace

#endif  // PORT_CONFORMANCE_TRACE_H
