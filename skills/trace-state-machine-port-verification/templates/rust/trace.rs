//! Minimal trace instrumentation for the Rust port.
//! Copy into the Rust project (e.g. `src/trace.rs`) and adapt.
//! See ../../reference/trace-contract.md for the format and output contract.
//!
//! Emits JSON Lines to the file named by the `TRACE_OUT` env var. When
//! `TRACE_OUT` is unset, tracing is a no-op (zero behavioral impact).
//!
//! Use the SAME abstract event names and param shapes as the C++ side. Keep
//! events semantic — never emit pointers, wall-clock time, or internal symbols.
//!
//! If a resource-release event is emitted from `Drop`, make sure an explicit
//! `close`/`release` path does not ALSO emit it — avoid double-counting.

use std::fs::File;
use std::io::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};

struct Sink {
    file: Mutex<File>,
    run_id: String,
}

static SINK: OnceLock<Option<Sink>> = OnceLock::new();
static SEQ: AtomicU64 = AtomicU64::new(0);

fn sink() -> Option<&'static Sink> {
    SINK.get_or_init(|| {
        let path = std::env::var("TRACE_OUT").ok().filter(|p| !p.is_empty())?;
        let file = File::create(path).ok()?; // create() truncates
        let run_id = std::env::var("RUN_ID").unwrap_or_else(|_| "rust-run".into());
        Some(Sink { file: Mutex::new(file), run_id })
    })
    .as_ref()
}

fn escape(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"")
}

/// Emit one event. `params` is a slice of (key, value) string pairs.
/// Thread-safe; flushes after every event so traces survive panics/early exits.
pub fn trace_event(event: &str, params: &[(&str, &str)]) {
    let Some(sink) = sink() else { return };
    let seq = SEQ.fetch_add(1, Ordering::SeqCst) + 1;

    let mut line = format!(
        "{{\"version\":1,\"run_id\":\"{}\",\"seq\":{},\"impl\":\"rust\",\"event\":\"{}\",\"params\":{{",
        escape(&sink.run_id),
        seq,
        escape(event),
    );
    for (i, (k, v)) in params.iter().enumerate() {
        if i > 0 {
            line.push(',');
        }
        line.push_str(&format!("\"{}\":\"{}\"", escape(k), escape(v)));
    }
    line.push_str("}}\n");

    let mut f = sink.file.lock().unwrap();
    let _ = f.write_all(line.as_bytes());
    let _ = f.flush();
}

// Example call sites (delete — for reference only):
//   trace_event("Start", &[("session", &session_id)]);
//   trace_event("HeaderParsed", &[("session", &session_id), ("kind", kind)]);
//   trace_event("ErrorRaised", &[("code", &error_code)]);
