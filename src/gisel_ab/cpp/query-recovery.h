//===- query-recovery.h - keep a batch alive across per-query aborts ------===//
//
// A legalizer query can trip an LLVM assertion (report_fatal_error, or a bare
// assert), which aborts the process.  The obvious recovery -- restart the
// runner after the offending query -- costs a process start (load the shared
// libraries, build every subtarget and legalizer) per abort.  The AArch64
// domain aborts on ~4% of its 936,960 points per config, and restarting there
// drops throughput from ~4,500 queries/s to ~380 queries/s.
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
#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/raw_ostream.h"

#include <cctype>
#include <csetjmp>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>

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
// Where the last aborted query died.  `writeUnanswerable` puts this in the
// answer row, so "both sides assert" becomes "both sides assert at the same
// place" -- otherwise two different upstream bugs look like one class.
inline char Site[256] = {0};

inline const char *baseName(const char *Path) {
  const char *Slash = std::strrchr(Path, '/');
  return Slash ? Slash + 1 : Path;
}

inline void recordSite(const char *File, unsigned Line) {
  if (!InQuery || !File)
    return;
  std::snprintf(Site, sizeof(Site), "%s:%u", baseName(File), Line);
}

// `llvm_unreachable` / `report_fatal_error` reach us as
// "UNREACHABLE executed at /path/LowLevelType.h:151!" (or "LLVM ERROR: ...").
// Keep the trailing file:line candidate.
inline void recordFatal(const char *Reason) {
  Site[0] = 0;
  if (!InQuery || !Reason)
    return;
  size_t Len = std::strlen(Reason);
  for (size_t P = Len; P-- > 2;) {
    if (Reason[P] != ':' || !std::isdigit((unsigned char)Reason[P + 1]))
      continue;
    size_t B = P;
    while (B > 0 && P - B < 64 && Reason[B - 1] != '/' && Reason[B - 1] != ' ' &&
           Reason[B - 1] != '(' && Reason[B - 1] != '\'' )
      --B;
    size_t E = P + 1;
    while (E < Len && std::isdigit((unsigned char)Reason[E]))
      ++E;
    if (E > P + 1) {
      std::snprintf(Site, sizeof(Site), "%.*s", (int)(E - B), Reason + B);
      return;
    }
  }
  // `report_fatal_error("...")` carries no location.  Keep a short, stable
  // prefix of the message instead, so two different calls stay distinguishable
  // and the answer row never loses the class of failure.
  char Text[64] = {0};
  size_t N = 0;
  for (const char *P = Reason; *P && N + 1 < sizeof(Text); ++P) {
    unsigned char C = (unsigned char)*P;
    if (std::isalnum(C) || C == ' ' || C == '_' || C == '-')
      Text[N++] = (char)C;
    else if (N && Text[N - 1] != ' ')
      Text[N++] = ' ';
  }
  while (N && Text[N - 1] == ' ')
    --N;
  Text[N] = 0;
  std::snprintf(Site, sizeof(Site), "fatal:%s", Text);
}

inline void onFatalError(void *, const char *Reason, bool) {
  const char *Text = Reason ? Reason : "fatal error";
  if (InQuery)
    recordFatal(Text);
  // Installing a handler supersedes LLVM's default printer, so print the same
  // shape ourselves: one "LLVM ERROR: ..." line on stderr.
  std::fprintf(stderr, "LLVM ERROR: %s%s", Text,
               (Text[0] && Text[std::strlen(Text) - 1] == '\n') ? "" : "\n");
  std::fflush(stderr);
}

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
  llvm::install_fatal_error_handler(onFatalError);
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
  detail::Site[0] = 0;
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

inline void writeJsonString(llvm::raw_ostream &Out, const char *Text) {
  Out << '"';
  for (const char *P = Text; *P; ++P) {
    if (*P == '"' || *P == '\\')
      Out << '\\';
    Out << *P;
  }
  Out << '"';
}

/// One answer row for a query that died: the query itself, plus the same
/// status/reason fields run-queries.py writes, plus where it died when the
/// abort carried a file:line.
inline void writeUnanswerable(llvm::StringRef Line, llvm::raw_ostream &Out) {
  size_t End = Line.rfind('}');
  if (End == llvm::StringRef::npos) {
    Out << "{\"status\":\"unanswerable\",\"reason\":\"asserted\"";
  } else {
    Out << Line.substr(0, End)
        << ",\"status\":\"unanswerable\",\"reason\":\"asserted\"";
  }
  if (detail::Site[0]) {
    Out << ",\"assert_site\":";
    writeJsonString(Out, detail::Site);
  }
  Out << "}\n";
}

// Overriding `__assert_fail` is what turns a bare `assert()` into a site we
// can report.  The runner is linked with -rdynamic so this definition
// interposes calls made from the LLVM shared libraries.
} // namespace ab

// `llvm_unreachable` does not go through the fatal-error handler: it prints
// "UNREACHABLE executed at file:line!" and calls abort() itself.  Taking the
// symbol over is the only way to keep that location; same -rdynamic rule.
namespace llvm {
[[noreturn]] void llvm_unreachable_internal(const char *Msg, const char *File,
                                            unsigned Line) {
  ab::detail::recordSite(File, Line);
  if (Msg)
    std::fprintf(stderr, "%s\n", Msg);
  if (File)
    std::fprintf(stderr, "UNREACHABLE executed at %s:%u!\n", File, Line);
  else
    std::fprintf(stderr, "UNREACHABLE executed!\n");
  std::fflush(stderr);
  std::abort();
}
} // namespace llvm

extern "C" void __assert_fail(const char *Assertion, const char *File,
                              unsigned Line, const char *Function)
    __attribute__((noreturn, visibility("default")));

extern "C" void __assert_fail(const char *Assertion, const char *File,
                              unsigned Line, const char *Function) {
  ab::detail::recordSite(File, Line);
  using Fn = void (*)(const char *, const char *, unsigned, const char *);
  static Fn Real = reinterpret_cast<Fn>(dlsym(RTLD_NEXT, "__assert_fail"));
  if (Real)
    Real(Assertion, File, Line, Function);
  std::fprintf(stderr, "%s:%u: Assertion `%s' failed.\n",
               File ? File : "?", Line, Assertion ? Assertion : "?");
  std::abort();
}

#endif
