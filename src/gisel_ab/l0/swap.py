#!/usr/bin/env python3
"""Point a legalizer constructor at a gisel-generated .inc.

    swap-source-ctor.py apply   --target x86 --tree TREE --inc INC
    swap-source-ctor.py restore --target x86 --tree TREE

All three targets spell the rules inline in the constructor: upstream has no
``X86LegalizerInfo.inc`` (checked at ``462829fdac83``), so copying a file into
the build tree changes nothing and the build system never sees a dependency.
``apply`` therefore always edits the source: it replaces the constructor body
with an ``#include`` of the generated fragment and leaves the rest of the
translation unit (custom legalization, helpers) untouched.

The original is kept under ``TREE/.gisel-swap`` so ``restore`` is byte exact.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_DERIVED = {
    "x86": {
        "ctor": "X86LegalizerInfo::X86LegalizerInfo(",
        "subtarget": "X86Subtarget",
        "body": """\
{
  (void)TM;
#include "__INC__"
  verify(*STI.getInstrInfo());
}
""",
    },
    "aarch64": {
        "ctor": ("AArch64LegalizerInfo::AArch64LegalizerInfo("
                 "const AArch64Subtarget &ST)"),
        "subtarget": "AArch64Subtarget",
    },
    "riscv": {
        "ctor": ("RISCVLegalizerInfo::RISCVLegalizerInfo("
                 "const RISCVSubtarget &ST)"),
        "subtarget": "RISCVSubtarget",
    },
    "arm": {
        "ctor": "ARMLegalizerInfo::ARMLegalizerInfo(const ARMSubtarget &ST)",
        "subtarget": "ARMSubtarget",
        # Thumb1 is not supported, and upstream says so by returning before
        # any rule is installed.  That is structure, not a rule: keep it so
        # the A/B compares rule tables rather than "empty vs populated".
        "body": """\
{
  using namespace TargetOpcode;
  if (ST.isThumb1Only()) {
    verify(*ST.getInstrInfo());
    return;
  }
  // The FCmp libcall tables are data for legalizeCustom, not rules.  The
  // importer lists them as skipped, so the swap has to keep the call.
  if (ST.useSoftFloat() || !ST.hasVFP2Base()) {
    if (AEABI(ST))
      setFCmpLibcallsAEABI();
    else
      setFCmpLibcallsGNU();
  }
#include "__INC__"
  verify(*ST.getInstrInfo());
}
""",
    },
    "ppc": {
        "ctor": "PPCLegalizerInfo::PPCLegalizerInfo(const PPCSubtarget &ST)",
        "subtarget": "PPCSubtarget",
        # Upstream does not call verify() here, and the rules take no
        # subtarget input at all.
        "body": """\
{
  using namespace TargetOpcode;
#include "__INC__"
}
""",
    },
    "mips": {
        "ctor": "MipsLegalizerInfo::MipsLegalizerInfo(const MipsSubtarget &ST)",
        "subtarget": "MipsSubtarget",
        "body": """\
{
  using namespace TargetOpcode;
#include "__INC__"
  verify(*ST.getInstrInfo());
}
""",
    },
    "m68k": {
        "ctor": "M68kLegalizerInfo::M68kLegalizerInfo(const M68kSubtarget &ST)",
        "subtarget": "M68kSubtarget",
        # Upstream's constructor is only the rule table: no subtarget
        # conditions, no libcall data, no trailing structure.
        "body": """\
{
  using namespace TargetOpcode;
#include "__INC__"
}
""",
    },
    "spirv": {
        "ctor": "SPIRVLegalizerInfo::SPIRVLegalizerInfo(const SPIRVSubtarget &ST)",
        "subtarget": "SPIRVSubtarget",
        # Two constructor statements are plumbing, not rules: legalizeCustom
        # reads the subtarget and the global registry through these members.
        # The importer lists both as ignored; dropping them leaves ST/GR null.
        "body": """\
{
  using namespace TargetOpcode;
  this->ST = &ST;
  GR = ST.getSPIRVGlobalRegistry();
#include "__INC__"
  verify(*ST.getInstrInfo());
}
""",
    },
    "wasm": {
        "ctor": ("WebAssemblyLegalizerInfo::WebAssemblyLegalizerInfo(\n"
                 "    const WebAssemblySubtarget &ST)"),
        "subtarget": "WebAssemblySubtarget",
        # The rules read ST.hasAddr64()/hasSignExt(); the generated
        # fragment names the parameter ST, so keep it as written.
        "body": """\
{
  using namespace TargetOpcode;
#include "__INC__"
}
""",
    },
}


from gisel_ab import targets as target_registry  # noqa: E402

# source/inc come from targets/*.json; ctor/subtarget/body are specific to
# this rewrite tool and stay here.
TARGETS = {}
for _name, _entry in _DERIVED.items():
    _doc = target_registry.load(_name)
    TARGETS[_name] = dict(_entry, source=_doc["touch_source"],
                          inc=_doc["inc_name"])

BODY = """\
{
  using namespace TargetOpcode;
  const __SUBTARGET__ &SubtargetRef = ST;
  (void)SubtargetRef;
  const TargetMachine &TM = ST.getTargetLowering()->getTargetMachine();
#include "__INC__"
  verify(*ST.getInstrInfo());
}
"""


def _body(subtarget, inc):
    return BODY.replace("__SUBTARGET__", subtarget).replace("__INC__", inc)


def _matching_brace(text, start):
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise SystemExit("unbalanced braces after constructor")


def _is_patched(text, inc):
    """True when the constructor body still points at a generated fragment."""
    return ('#include "%s"' % inc) in text


def _tuple_target(name):
    if name not in TARGETS:
        raise SystemExit("unknown target %r (known: %s)"
                         % (name, ", ".join(sorted(TARGETS))))
    return TARGETS[name]


def cmd_apply(args):
    spec = _tuple_target(args.target)
    tree = Path(args.tree).resolve()
    source = tree / spec["source"]
    text = source.read_text()
    start = text.find(spec["ctor"])
    if start < 0:
        raise SystemExit("constructor not found in %s" % source)
    brace = text.index("{", start)
    end = _matching_brace(text, brace)

    backup = tree / ".gisel-swap" / spec["source"]
    backup.parent.mkdir(parents=True, exist_ok=True)
    # A backup only means anything while the file it came from is patched.
    # A worktree that was patched in an earlier session and then committed
    # (or repaired by hand) would otherwise be restored to that old text and
    # silently lose the edits made since.
    if not (backup.exists() and _is_patched(text, spec["inc"])):
        shutil.copyfile(source, backup)
    inc_path = source.parent / spec["inc"]
    shutil.copyfile(args.inc, inc_path)
    template = spec.get("body")
    body = (template.replace("__INC__", spec["inc"]) if template
            else _body(spec["subtarget"], spec["inc"]))
    source.write_text(text[:brace] + body + text[end + 1:])
    print("%s: %s patched, %s written (original in %s)"
          % (args.target, source, inc_path, backup))
    return 0


def cmd_restore(args):
    spec = _tuple_target(args.target)
    tree = Path(args.tree).resolve()
    source = tree / spec["source"]
    backup = tree / ".gisel-swap" / spec["source"]
    if not _is_patched(source.read_text(), spec["inc"]):
        print("%s: %s is not patched, nothing to restore"
              % (args.target, source))
        return 0
    if not backup.exists():
        raise SystemExit("no backup at %s" % backup)
    shutil.copyfile(backup, source)
    inc_path = source.parent / spec["inc"]
    if inc_path.exists():
        inc_path.unlink()
    print("%s: restored %s" % (args.target, source))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="swap-source-ctor")
    parser.add_argument("mode", choices=("apply", "restore"))
    parser.add_argument("--target", required=True,
                        choices=sorted(TARGETS))
    parser.add_argument("--tree")
    parser.add_argument("--inc")
    args = parser.parse_args(argv)
    if args.mode == "apply" and not args.inc:
        parser.error("apply needs --inc")
    if not args.tree:
        # There is no build-tree .inc for any target; a build-only swap used
        # to be accepted for x86 and silently did nothing.
        parser.error("%s needs --tree" % args.target)
    return cmd_apply(args) if args.mode == "apply" else cmd_restore(args)


if __name__ == "__main__":
    sys.exit(main())
