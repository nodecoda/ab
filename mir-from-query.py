#!/usr/bin/env python3
"""Turn answerless queries into one minimal, runnable MIR file each.

    mir-from-query.py --target x86 --queries Q.jsonl --out OUT [--json]

The output directory holds ``qNNNNN.mir`` files, each with its own ``# RUN:``
line, plus ``index.jsonl`` mapping file -> query key and bucket.  Replay is
the same command as L1 (``mir-replay.py --layer generated --mir OUT``).

A query that cannot be turned into real MIR is not dropped: it lands in
``unbuildable_shape`` / ``unbuildable_type`` / ``config_unrealizable`` with a
reason, and the three buckets plus ``built`` must add up to the input count.

Nothing here knows the legalizer's answers; the shapes are transcription of
``llvm/include/llvm/Target/GenericOpcodes.td`` operand lists (see
``data/mir-shapes.jsonc``) and the config table cites the feature truth table.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHAPES = ROOT / "data" / "mir-shapes.jsonc"
CONFIGS = ROOT / "data" / "mir-configs.json"

LOADS = {"G_LOAD", "G_SEXTLOAD", "G_ZEXTLOAD", "G_FPEXTLOAD"}
STORES = {"G_STORE", "G_FPTRUNCSTORE"}
VARIADIC = {"G_BUILD_VECTOR", "G_CONCAT_VECTORS", "G_MERGE_VALUES",
            "G_UNMERGE_VALUES"}

VECTOR_RE = re.compile(
    r"^(nxv|v)(\d+)(?:"
    r"s(\d+)"          # v4s32  (core LLT spelling)
    r"|i(\d+)"          # v16i8  (gisel importer spelling for the same thing)
    r"|f(\d+)"          # v2f32
    r"|bf16"             # v2bf16
    r"|p(\d+)(?::(?:\*|\d+))?"   # v2p0:64, vector of pointers
    r")$")
POINTER_RE = re.compile(r"^p(\d+)(?::(?:\*|\d+))?$")
SCALAR_RE = re.compile(r"^s(\d+)$")
INTEGER_RE = re.compile(r"^i(\d+)$")
FLOAT_RE = re.compile(r"^f(\d+)$")

FP_LITERALS = {
    16: "half 0xH0000",
    32: "float 0.0",
    64: "double 0.0",
    80: "x86_fp80 0xK00000000000000000000",
    128: "fp128 0xL00000000000000000000000000000000",
}


# Opcodes the MIR builder deliberately does not spell.  Each reason has to
# say *why*: a silent skip would look like coverage.
SKIP = {
    "G_PHI": "needs a multi-block CFG whose predecessors are successors; "
              "G_PHI has no legalizer rule to ask about",
    "G_BRJT": "needs a %jump-table descriptor and a target block, which a "
              "single-block answerless query does not carry",
    "G_JUMP_TABLE": "needs a %jump-table descriptor in the MIR YAML; the "
                    "query only names its type",
    "G_BLOCK_ADDR": "needs a blockaddress(@f, %bb.0) constant whose function "
                    "body is the one under test; not representable in place",
    "G_PTRAUTH_GLOBAL_VALUE": "needs a ptrauth-signed global and key/disc "
                              "operands; the query only names two types",
}


class Unbuildable(Exception):
    def __init__(self, bucket: str, reason: str):
        super().__init__(reason)
        self.bucket = bucket
        self.reason = reason


def load_jsonc(path: Path) -> dict:
    """Strip // and /* */ comments outside strings, then parse."""
    text = path.read_text()
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        out.append(ch)
        i += 1
    return json.loads("".join(out))


def validate_shapes(doc: dict) -> dict:
    """Contract: schema 1, and every entry cites where it came from."""
    if doc.get("schema") != 1:
        raise SystemExit("mir-from-query: shapes schema %r != 1"
                         % doc.get("schema"))
    opcodes = doc.get("opcodes") or {}
    for name, shape in opcodes.items():
        if not isinstance(shape.get("out"), list) or not isinstance(
                shape.get("in"), list):
            raise SystemExit("mir-from-query: %s has no out/in lists" % name)
        if not shape.get("source"):
            raise SystemExit("mir-from-query: %s has no source" % name)
    return opcodes


def llt(text: str) -> dict:
    match = POINTER_RE.match(text)
    if match:
        return {"kind": "pointer", "as": int(match.group(1))}
    match = SCALAR_RE.match(text)
    if match:
        return {"kind": "scalar", "bits": int(match.group(1))}
    match = INTEGER_RE.match(text)
    if match:
        return {"kind": "integer", "bits": int(match.group(1))}
    match = FLOAT_RE.match(text)
    if match:
        return {"kind": "float", "bits": int(match.group(1))}
    if text == "bf16":
        return {"kind": "float", "bits": 16}
    match = VECTOR_RE.match(text)
    if match:
        scalable, lanes = match.group(1) == "nxv", int(match.group(2))
        # One element grammar, three spellings: `s32`, `i32` and `f32` all
        # print as LLTs; `bf16` and `p0` keep their own names.
        if match.group(3):
            elem, elem_bits = "s" + match.group(3), int(match.group(3))
        elif match.group(4):
            elem, elem_bits = "s" + match.group(4), int(match.group(4))
        elif match.group(5):
            elem, elem_bits = "f" + match.group(5), int(match.group(5))
        elif "bf16" in text:
            elem, elem_bits = "bf16", 16
        else:
            elem, elem_bits = "p" + match.group(6), None
        return {"kind": "vector", "scalable": scalable, "lanes": lanes,
                "elem": elem, "elem_bits": elem_bits}
    raise Unbuildable("unbuildable_type", "cannot spell %r in MIR" % text)


def bits(text: str, ptr_bits: int) -> int:
    info = llt(text)
    if info["kind"] == "pointer":
        return ptr_bits
    if info["kind"] == "vector":
        elem = info["elem_bits"]
        return info["lanes"] * (ptr_bits if elem is None else elem)
    return info["bits"]


def mir_type(text: str) -> str:
    """Core LLT spelling -> the MIR spelling LLT::print would produce."""
    info = llt(text)
    if info["kind"] == "pointer":
        return "p%d" % info["as"]
    if info["kind"] == "vector":
        inner = info["elem"]
        if info["scalable"]:
            return "<vscale x %d x %s>" % (info["lanes"], inner)
        return "<%d x %s>" % (info["lanes"], inner)
    if info["kind"] == "integer":
        return "i%d" % info["bits"]
    if info["kind"] == "float":
        return "f%d" % info["bits"]
    return "s%d" % info["bits"]


def slot_indices(shape: dict):
    """(arity, set of pointer slot indices) from the transcribed operands."""
    indices, pointers = [], set()
    for side in ("out", "in"):
        for kind in shape[side]:
            match = re.match(r"^(p)?type(\d+)$", kind)
            if match:
                index = int(match.group(2))
                indices.append(index)
                if match.group(1):
                    pointers.add(index)
    if not indices:
        return 0, pointers
    return max(indices) + 1, pointers


def is_pointer_ty(text: str) -> bool:
    """`p0` and vectors of pointers (`v2p0:64`) both fill a ptypeN slot."""
    info = llt(text)
    return info["kind"] == "pointer" or (
        info["kind"] == "vector" and info["elem"].startswith("p"))


def fill_slot(index: int, pointers, given):
    if index in pointers:
        return "p0"
    return given


def build(query: dict, shapes: dict, cfg: dict, ptr_bits: int):
    opcode = query["name"]
    if opcode in SKIP:
        raise Unbuildable("unbuildable_shape", SKIP[opcode])
    shape = shapes.get(opcode)
    if shape is None:
        raise Unbuildable("unbuildable_shape", "no shape for %s" % opcode)
    if opcode == "G_INTRINSIC":
        raise Unbuildable("unbuildable_shape",
                          "the query does not name the intrinsic")

    arity, pointers = slot_indices(shape)
    given = list(query.get("types") or [])
    if len(given) > arity:
        raise Unbuildable(
            "unbuildable_shape",
            "query has %d type slots, %s has %d" % (len(given), opcode, arity))
    slots = list(given)
    for index in range(len(given), arity):
        slots.append(fill_slot(index, pointers, "s64"))
    for index in sorted(pointers):
        if index < len(given) and not is_pointer_ty(slots[index]):
            raise Unbuildable(
                "unbuildable_shape",
                "slot %d of %s is a pointer, query says %s"
                % (index, opcode, slots[index]))

    pre, extra_sections, module = [], [], []
    counter = [0]

    def fresh(ty):
        name = "%%%d" % counter[0]
        counter[0] += 1
        pre.append("    %s:_(%s) = G_IMPLICIT_DEF" % (name, mir_type(ty)))
        return "%s:_(%s)" % (name, mir_type(ty))

    def define(ty):
        name = "%%%d" % counter[0]
        counter[0] += 1
        return name, "%s:_(%s)" % (name, mir_type(ty))

    kind_of = {}
    for side in ("out", "in"):
        for position, kind in enumerate(shape[side]):
            kind_of[(side, position)] = kind

    unknown_literals = {}

    def literal_for(index, ty):
        if opcode == "G_CONSTANT":
            if llt(ty)["kind"] == "vector":
                raise Unbuildable("unbuildable_type",
                                  "G_CONSTANT with vector type %s" % ty)
            return "i%d 0" % bits(ty, ptr_bits)
        if opcode == "G_FCONSTANT":
            size = bits(ty, ptr_bits)
            if size not in FP_LITERALS:
                raise Unbuildable("unbuildable_type",
                                  "no fp literal for %d bits" % size)
            return FP_LITERALS[size]
        if opcode == "G_BR":
            return "%bb.1"
        if opcode == "G_BRCOND":
            return "%bb.1"
        if opcode == "G_GLOBAL_VALUE":
            module.append("  @g = external global i8")
            return "@g"
        if opcode == "G_FRAME_INDEX":
            module.append("    %stack.0 = alloca i8, align 8")
            extra_sections.append("  - { id: 0, name: stack.0, size: 8, "
                                  "alignment: 8 }")
            return "%stack.0"
        if opcode == "G_CONSTANT_POOL":
            extra_sections.append("  - id: 0\n    value: 'double 1.0'\n"
                                  "    alignment: 8\n    isTargetSpecific: false")
            return "%const.0"
        if opcode == "G_ICMP":
            return "intpred(eq)"
        if opcode == "G_FCMP":
            return "floatpred(oeq)"
        if opcode == "G_IS_FPCLASS":
            return "1"
        if opcode in ("G_EXTRACT", "G_INSERT", "G_EXTRACT_SUBVECTOR",
                      "G_INSERT_SUBVECTOR", "G_INDEXED_STORE"):
            return "0"
        if opcode == "G_VAARG":
            return "4"
        if opcode == "G_VSCALE":
            return "i%d 1" % bits(ty, ptr_bits)
        if opcode == "G_SHUFFLE_VECTOR":
            info = llt(ty)
            if info["kind"] != "vector":
                raise Unbuildable("unbuildable_shape",
                                  "G_SHUFFLE_VECTOR result %s is not a vector"
                                  % ty)
            return "shufflemask(%s)" % ", ".join(
                str(i) for i in range(info["lanes"]))
        if opcode == "G_SEXT_INREG":
            width = bits(ty, ptr_bits)
            return str(max(1, min(8, width - 1)))
        if opcode == "G_MEMCPY":
            return "i64 0"
        raise Unbuildable("unbuildable_shape",
                          "no literal rule for %s" % opcode)

    # memory operands
    mem_text = ""
    if opcode in LOADS or opcode in STORES:
        mem = query.get("mem")
        if not mem or len(mem) < 2:
            raise Unbuildable("unbuildable_shape",
                              "%s without a memory operand" % opcode)
        if len(mem) >= 4 and (mem[2] != "NotAtomic"
                              or mem[3] != "NotAtomic"):
            raise Unbuildable("unbuildable_shape", "atomic memory operand")
        mty, align = mem[0], int(mem[1])
        prefix = "load" if opcode in LOADS else "store"
        mem_text = " :: (%s (%s), align %d)" % (
            prefix, mir_type(mty), align)
    elif opcode in ("G_MEMCPY", "G_MEMCPY_INLINE"):
        mem_text = (" :: (store (s8), align 1), (load (s8), align 1)")
    elif opcode == "G_VASTART":
        # RISCVLegalizerInfo::legalizeVAStart asserts on a missing mem operand.
        # The query names the list pointer only; the store size is the
        # ABI's own business, so the smallest faithful marker is a byte store.
        mem_text = " :: (store (s8))"
    elif opcode == "G_VAARG":
        mem_text = " :: (load (s8))"
    elif opcode == "G_INDEXED_STORE":
        mem_text = " :: (store (%s))" % mir_type(slots[1])
    elif opcode == "G_ATOMIC_CMPXCHG_WITH_SUCCESS":
        mem_text = (" :: (load store monotonic monotonic (%s))"
                    % mir_type(slots[0]))
    elif opcode.startswith("G_ATOMICRMW_") or opcode == "G_ATOMIC_CMPXCHG":
        # The queries carry no memory operand for atomics; the ordering is
        # implied by the opcode, so a plain monotonic mem operand is the
        # smallest faithful one.
        mem_text = " :: (load store monotonic (%s))" % mir_type(slots[0])

    # variadic expansion: (position kind, type text, count)
    variable = []
    if opcode in VARIADIC:
        if opcode == "G_UNMERGE_VALUES":
            out_ty, in_ty = slots[0], slots[-1]
            if bits(in_ty, ptr_bits) % bits(out_ty, ptr_bits):
                raise Unbuildable("unbuildable_shape",
                                  "%s/%s is not a whole number of pieces"
                                  % (in_ty, out_ty))
            pieces = bits(in_ty, ptr_bits) // bits(out_ty, ptr_bits)
            # `type0` already names the first def; variable_ops adds the rest.
            variable = [("out", out_ty, pieces - 1)]
        elif opcode == "G_MERGE_VALUES":
            out_ty, in_ty = slots[0], slots[-1]
            if bits(out_ty, ptr_bits) % bits(in_ty, ptr_bits):
                raise Unbuildable("unbuildable_shape",
                                  "%s/%s is not a whole number of pieces"
                                  % (out_ty, in_ty))
            pieces = bits(out_ty, ptr_bits) // bits(in_ty, ptr_bits)
            variable = [("in", in_ty, pieces - 1)]
        else:  # BUILD_VECTOR / CONCAT_VECTORS
            out_ty, in_ty = slots[0], slots[-1]
            out_info, in_info = llt(out_ty), llt(in_ty)
            if out_info["kind"] != "vector" or in_info["kind"] != "vector":
                if opcode == "G_BUILD_VECTOR" and out_info["kind"] == "vector":
                    count = out_info["lanes"]
                else:
                    raise Unbuildable("unbuildable_shape",
                                      "%s needs vector types, got %s / %s"
                                      % (opcode, out_ty, in_ty))
            else:
                if out_info["lanes"] % in_info["lanes"]:
                    raise Unbuildable(
                        "unbuildable_shape",
                        "%s lanes %d / %d is not whole"
                        % (opcode, out_info["lanes"], in_info["lanes"]))
                count = out_info["lanes"] // in_info["lanes"]
                if opcode == "G_BUILD_VECTOR":
                    count = out_info["lanes"]
            count -= 1  # `type1` already names the first operand
            if count <= 0 or count > 64:
                raise Unbuildable("unbuildable_shape",
                                  "%s needs %d operands" % (opcode, count))
            variable = [("in", in_ty, count)]

    def expand(side):
        """One (kind, type) pair per operand on this side.

        A `variable_ops` slot expands to ``("var", ty)`` entries, because the
        count comes from the type sizes rather than from the transcription.
        """
        items = []
        for kind in shape[side]:
            if kind == "variable_ops":
                for v_side, v_ty, count in variable:
                    if v_side == side:
                        items.extend([("var", v_ty)] * count)
                continue
            items.append((kind, None))
        return items

    def is_type_kind(kind):
        return re.match(r"^(p)?type\d+$", kind) is not None

    def slot_of(kind):
        return int(re.search(r"(\d+)$", kind).group(1))

    def operand(kind, position, ty=None):
        if kind == "var":
            return fresh(ty)
        if is_type_kind(kind):
            return fresh(slots[slot_of(kind)])
        if kind == "i32imm":
            return "8"
        if kind == "untyped_imm":
            imms = query.get("imms") or []
            return str(imms[position]) if position < len(imms) else "0"
        if kind == "unknown":
            return literal_for(position, slots[0] if slots else "s32")
        raise Unbuildable("unbuildable_shape", "unknown operand kind %r" % kind)

    defs, def_texts = [], []
    for kind, ty in expand("out"):
        if kind == "var":
            name, text = define(ty)
            defs.append((name, mir_type(ty)))
            def_texts.append(text)
        elif is_type_kind(kind):
            name, text = define(slots[slot_of(kind)])
            defs.append((name, mir_type(slots[slot_of(kind)])))
            def_texts.append(text)
        else:
            def_texts.append(operand(kind, len(def_texts)))

    ins = [operand(kind, index, ty)
           for index, (kind, ty) in enumerate(expand("in"))]
    args = ", ".join(ins)
    if def_texts:
        instruction = "%s = %s%s%s" % (
            ", ".join(def_texts), opcode, " " if args else "", args)
    else:
        instruction = "%s%s%s" % (opcode, " " if args else "", args)
    instruction += mem_text

    # The legalizer erases trivially dead instructions before it looks at
    # them (`isTriviallyDead` in Legalizer.cpp).  A tested instruction whose
    # defs nobody reads would therefore vanish from the output and every
    # mutation of its rule would look identical.  COPY is not a pre-isel
    # generic opcode, so the legalizer neither legalizes nor erases it: one
    # sink per def is enough to keep the real instruction alive.
    sinks = []
    for name, ty in defs:
        sink = "%%%d" % counter[0]
        counter[0] += 1
        sinks.append("    %s:_(%s) = COPY %s" % (sink, ty, name))

    body = list(pre)
    body.append("    " + instruction)
    body.extend(sinks)
    if opcode in ("G_BR", "G_BRCOND"):
        body.append("  bb.1:")

    if module and "alloca" in " ".join(module):
        module_text = ("  define void @f() {\n" + "\n".join(module) +
                       "\n    ret void\n  }")
    else:
        module_text = ("  define void @f() { ret void }")
        if module:
            module_text = "\n".join(module + ["  define void @f() { ret void }"])

    yaml_extra = ""
    if opcode == "G_FRAME_INDEX":
        yaml_extra = "stack:\n" + extra_sections[0] + "\n"
    elif opcode == "G_CONSTANT_POOL":
        yaml_extra = "constants:\n" + extra_sections[0] + "\n"

    # `-global-isel-abort=1` (Enable) makes "no rule matched" observable: with
    # abort=0 an Unsupported instruction stays in the output exactly like a
    # Legal one, so a rule that lost its legal case would diff as nothing.
    extra = " ".join(cfg.get("args") or [])
    run = ("# RUN: llc -O0 -mtriple=%s -mattr=%s %s-global-isel-abort=1 "
           "-run-pass=legalizer %%s -o -\n"
           % (cfg["triple"], ",".join(cfg["mattr"]),
              extra + " " if extra else ""))
    text = run + "--- |\n" + module_text + "\n...\n---\n" \
        "name:            f\ntracksRegLiveness: true\n" + yaml_extra + \
        "body:             |\n  bb.0:\n" + "\n".join(body) + "\n...\n"
    return text


def preflight_one(path: Path, llc: Path, lib_dir):
    text = path.read_text()
    run = next(line.split("# RUN:", 1)[1].strip()
               for line in text.splitlines() if line.startswith("# RUN:"))
    argv = shlex.split(run.replace("%s", str(path.resolve())))[1:]
    # Preflight answers "is this a well-formed question", not "what does the
    # legalizer say".  `-run-pass=none` still parses the MIR and runs the
    # machine verifier, but it cannot hit a legalizer assertion: a query that
    # crashes the legalizer is an unanswerable input (both sides abort), not a
    # malformed file.
    argv = ["-run-pass=none" if arg == "-run-pass=legalizer" else arg
            for arg in argv]
    env = dict(os.environ)
    if lib_dir:
        prefix = str(lib_dir)
        if env.get("LD_LIBRARY_PATH"):
            prefix += os.pathsep + env["LD_LIBRARY_PATH"]
        env["LD_LIBRARY_PATH"] = prefix
    proc = subprocess.run([str(llc), *argv], capture_output=True, text=True,
                          env=env)
    if proc.returncode == 0:
        return path, None
    # Only parse/verifier rejections make the query unbuildable.  A legalizer
    # "unable to legalize" is an answer, not a malformed question: both sides
    # hit it, so it belongs in the replay's both_abort bucket.
    for line in (proc.stderr or "").splitlines():
        line = line.strip()
        if line.startswith("*** Bad machine code:") or line.startswith("error:"):
            return path, line
    if proc.returncode == 0:
        return path, None
    if "unable to legalize" in (proc.stderr or ""):
        return path, None
    return path, "llc rc=%d" % proc.returncode


def reclassify(index, out, buckets, per_opcode, reasons, llc, lib_dir, jobs):
    """Move MIR the parser/machine verifier rejects to unbuildable_shape.

    The legalizer never sees these files: `llc` verifies the input function
    while parsing it.  Counting them as agreement would overstate coverage,
    so they are dropped with the verifier's reason and re-bucketed.
    """
    paths = [out / row["file"] for row in index if row["bucket"] == "built"]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [pool.submit(preflight_one, path, llc, lib_dir)
                   for path in paths]
        for future in futures:
            path, reason = future.result()
            results[path.name] = reason
    for row in index:
        if row["bucket"] != "built":
            continue
        reason = results.get(row["file"])
        if reason is None:
            continue
        (out / row["file"]).unlink()
        row["bucket"] = "unbuildable_shape"
        row["reason"] = reason
        row["file"] = None
        buckets["built"] -= 1
        buckets["unbuildable_shape"] += 1
        reasons[reason] += 1
        per_opcode[(row["query"]["name"], "built")] -= 1
        per_opcode[(row["query"]["name"], "unbuildable_shape")] += 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="mir-from-query", description="Build one MIR per answerless query")
    parser.add_argument("--target", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--shapes", default=str(SHAPES))
    parser.add_argument("--configs", default=str(CONFIGS))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--preflight-llc",
                        help="llc to parse-check every generated .mir")
    parser.add_argument("--preflight-lib",
                        help="CodeGen library directory for the preflight run")
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    shapes = validate_shapes(load_jsonc(Path(args.shapes)))
    config_doc = json.loads(Path(args.configs).read_text())
    try:
        target_configs = config_doc["targets"][args.target]
    except KeyError:
        print("mir-from-query: no configs for %r" % args.target,
              file=sys.stderr)
        return 2

    queries = []
    with open(args.queries) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))
            if args.limit and len(queries) >= args.limit:
                break

    out = Path(args.out) / args.target
    out.mkdir(parents=True, exist_ok=True)

    buckets = Counter()
    per_opcode = Counter()
    reasons = Counter()
    index = []
    for number, query in enumerate(queries):
        config_name = query.get("config")
        cfg = target_configs.get(config_name)
        if cfg is None or "mattr" not in cfg:
            reason = ("no triple/mattr for %s" % config_name if cfg is None
                      else cfg.get("source", config_name))
            buckets["config_unrealizable"] += 1
            reasons[reason] += 1
            index.append({"file": None, "query": query,
                          "bucket": "config_unrealizable",
                          "reason": reason})
            continue
        width = cfg.get("pointer_width")
        if width is None:
            width = 64 if "64" in cfg["triple"] else 32
        try:
            text = build(query, shapes, cfg, width)
        except Unbuildable as exc:
            buckets[exc.bucket] += 1
            reasons[exc.reason] += 1
            per_opcode[(query["name"], exc.bucket)] += 1
            index.append({"file": None, "query": query, "bucket": exc.bucket,
                          "reason": exc.reason})
            continue
        name = "q%05d.mir" % number
        (out / name).write_text(text)
        buckets["built"] += 1
        per_opcode[(query["name"], "built")] += 1
        index.append({"file": name, "query": query, "bucket": "built"})

    if args.preflight_llc:
        reclassify(index, out, buckets, per_opcode, reasons,
                   Path(args.preflight_llc),
                   Path(args.preflight_lib) if args.preflight_lib else None,
                   args.jobs)

    with open(out / "index.jsonl", "w") as handle:
        for row in index:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    total = sum(buckets.values())
    identity = (buckets["built"] + buckets["unbuildable_shape"]
                + buckets["unbuildable_type"]
                + buckets["config_unrealizable"]) == total
    summary = {
        "target": args.target,
        "queries": total,
        "built": buckets["built"],
        "unbuildable_shape": buckets["unbuildable_shape"],
        "unbuildable_type": buckets["unbuildable_type"],
        "config_unrealizable": buckets["config_unrealizable"],
        "identity": identity,
        "reasons": dict(reasons.most_common(20)),
        "per_opcode": {"%s/%s" % key: count
                       for key, count in sorted(per_opcode.items())},
        "out": str(out),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("%s: %d queries -> %d MIR (%d shape, %d type, %d config)"
              % (args.target, total, buckets["built"],
                 buckets["unbuildable_shape"], buckets["unbuildable_type"],
                 buckets["config_unrealizable"]))
        for reason, count in reasons.most_common(10):
            print("  %5d  %s" % (count, reason))
    return 0 if identity else 1


if __name__ == "__main__":
    sys.exit(main())
