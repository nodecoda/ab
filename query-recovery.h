//===- query-recovery.h - keep a batch alive across per-query aborts ------===//
//
// A legalizer query can trip an LLVM assertion (report_fatal_error, or a bare
// assert), which aborts the process.  The obvious recovery -- restart the
// runner after the offending query -- costs a process start (load the shared
// libraries, build every subtarget and legalizer) per abort.  A full AArch64
// domain aborts on a large fraction of its 960,480 points, and restarting
// there drops throughput from ~4,500 queries/s to ~380 queries/s.
//
// The runner is single threaded and builds its legalizers before it answers,
// so an aborted getAction() can only leak memory allocated during that call.
// Catching the abort with siglongjmp keeps the batch going and lets the answer
// file carry exactly one row per query.  run-queries.py still restarts on a
// real crash (SIGSEGV), so a broken legalizer cannot silently produce rows.
//
// The process is also made non-dumpable: on hosts whose core_pattern pipes
// every core to a handler (apport on Ubuntu), a core costs ~80 ms even though
// the runner never reads it.
//===----------------------------------------------------------------------===//

#ifndef AB_QUERY_RECOVERY_H
#define AB_QUERY_RECOVERY_H

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/raw_ostream.h"

#include <csetjmp>
#include <csignal>
#include <cstdlib>

#if defined(__linux__)
#include <sys/prctl.h>
#endif

namespace ab {

inline void disableCoreDumps() {
#if defined(__linux__)
  (void)prctl(PR_SET_DUMPABLE, 0);
#endif
}

namespace detail {
inline sigjmp_buf Jump;
inline volatile sig_atomic_t InQuery = 0;

inline void onAbort(int Sig) {
  if (InQuery) {
    InQuery = 0;
    siglongjmp(Jump, 1);
  }
  // Not inside a query: restore the default disposition and re-raise, so the
  // process still dies with the signal a caller expects.
  std::signal(Sig, SIG_DFL);
  std::raise(Sig);
}

inline void install() {
  static bool Done = false;
  if (Done)
    return;
  Done = true;
  std::signal(SIGABRT, onAbort);
}
} // namespace detail

/// Run one query under the recovery point.  Returns false when it aborted;
/// the caller then writes the unanswerable row itself.
///
/// The sigsetjmp frame must stay alive while the query runs, which is why the
/// query is a callback rather than a separate enter/leave pair: a setjmp in a
/// helper that has already returned would jump into a dead frame.
template <typename Fn>
inline bool runQuery(Fn &&Query) {
  detail::install();
  detail::InQuery = 1;
  if (sigsetjmp(detail::Jump, 1) == 0) {
    Query();
    detail::InQuery = 0;
    return true;
  }
  detail::InQuery = 0;
  return false;
}

inline void leaveQuery() { detail::InQuery = 0; }

/// One answer row for a query that died: the query itself, plus the same
/// status/reason fields run-queries.py writes when it recovers from a crash.
inline void writeUnanswerable(llvm::StringRef Line, llvm::raw_ostream &Out) {
  size_t End = Line.rfind('}');
  if (End == llvm::StringRef::npos) {
    Out << "{\"status\":\"unanswerable\",\"reason\":\"asserted\"}\n";
    return;
  }
  Out << Line.substr(0, End)
      << ",\"status\":\"unanswerable\",\"reason\":\"asserted\"}\n";
}

} // namespace ab

#endif
