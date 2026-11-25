from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

if __package__:
    from . import linker, translator
    from .cpu import CPU
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from main import linker, translator
    from main.cpu import CPU

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it with: python -m pip install pyyaml"
    ) from exc


class GoldenTestError(Exception):
    """Invalid test description or unsupported golden-test data."""


def _input_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, list):
        try:
            return bytes(value)
        except (TypeError, ValueError) as exc:
            raise GoldenTestError(f"invalid byte array: {value!r}") from exc
    if not isinstance(value, str):
        raise GoldenTestError(
            f"input data must be a string or byte array, got {type(value).__name__}"
        )
    if value.upper() == "NUL":
        return b"\0"
    if value.startswith("hex:"):
        try:
            return bytes.fromhex(value[4:])
        except ValueError as exc:
            raise GoldenTestError(f"invalid hex input {value!r}: {exc}") from exc
    return value.encode("utf-8")


def parse_input_schedule(value: Any) -> list[tuple[int, bytes]]:
    if value is None:
        return []

    events: list[tuple[int, bytes]] = []
    if isinstance(value, dict):
        for raw_cycle, raw_data in value.items():
            cycle = int(raw_cycle)
            events.append((cycle, _input_bytes(raw_data)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, dict) or "cycle" not in item:
                raise GoldenTestError(
                    f"input schedule item #{index + 1} must be a mapping "
                    "with a cycle field"
                )
            events.append((int(item["cycle"]), _input_bytes(item.get("data", ""))))
    elif isinstance(value, str):
        for part in value.split(";"):
            part = part.strip()
            if not part:
                continue
            match = re.fullmatch(r"cycle\s+(\d+)\s*:\s*(.*)", part, re.IGNORECASE)
            if not match:
                raise GoldenTestError(f"invalid input schedule entry: {part!r}")
            events.append((int(match.group(1)), _input_bytes(match.group(2).strip())))
    else:
        raise GoldenTestError(
            "in_input_schedule must be a list, mapping, or schedule string"
        )

    for cycle, payload in events:
        if cycle < 1:
            raise GoldenTestError(f"input event cycle must be >= 1, got {cycle}")
        if not payload:
            raise GoldenTestError(f"input event at cycle {cycle} has an empty payload")
    return sorted(events, key=lambda event: event[0])


def render_trace(trace: list[Any], *, limit: int | None = None) -> str:
    entries = trace if limit is None else trace[:limit]

    columns = (7, 12, 12, 20)
    header = (
        f"{'CYCLE':<{columns[0]}}"
        f"{'PC':<{columns[1]}}"
        f"{'STAGE':<{columns[2]}}"
        f"{'INSTRUCTION':<{columns[3]}}"
        "REGISTER CHANGES"
    )
    separator = "-" * len(header)
    lines = [header, separator]

    previous: tuple[int, ...] | None = None
    for entry in entries:
        current = tuple(entry.registers)
        changes: list[str] = []
        if previous is not None:
            for index, (old, value) in enumerate(zip(previous, current, strict=True)):
                if old != value:
                    changes.append(f"R{index}=0x{value & 0xFFFFFFFF:08X}")

        instruction = getattr(entry, "instruction", "") or "-"
        change_text = ", ".join(changes) if changes else "-"
        lines.append(
            f"{entry.cycle:<{columns[0]}}"
            f"0x{entry.instruction_pc:08X}   "
            f"{entry.stage:<{columns[2]}}"
            f"{instruction:<{columns[3]}}"
            f"{change_text}"
        )
        previous = current

    if limit is not None and len(trace) > limit:
        lines.append(f"... {len(trace) - limit} cycles omitted ...")

    if trace:
        lines.append(separator)
        lines.append(f"Trace entries: {len(trace)} | Cycles: {trace[-1].cycle}")

    return "\n".join(lines) + "\n"


def _binary_expected(doc: dict[str, Any]) -> bytes | None:
    value = doc.get("out_binary_hex", doc.get("out_code_hex"))
    if value is not None:
        try:
            return bytes.fromhex(str(value))
        except ValueError as exc:
            raise GoldenTestError(
                f"invalid out_binary_hex/out_code_hex: {exc}"
            ) from exc

    legacy = doc.get("out_code")
    if legacy is None:
        return None
    if isinstance(legacy, str):
        return legacy.encode("latin1")
    return bytes(legacy)


def _program_sections(program: Any) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for section, fragments in program.sections.items():
        result[section] = [
            {"address": address, "hex": bytes(data).hex(" ")}
            for address, data in fragments
        ]
    return result


def _register_snapshot(cpu: CPU) -> dict[str, str]:
    return {
        f"R{i}": f"0x{value & 0xFFFFFFFF:08X}" for i, value in enumerate(cpu.registers)
    }


def _cache_snapshot(cpu: CPU) -> dict[str, int] | None:
    cache = getattr(cpu, "cache", None)
    stats = getattr(cache, "stats", None)
    if stats is None:
        return None
    return {
        "hits": int(stats.hits),
        "misses": int(stats.misses),
        "writebacks": int(stats.writebacks),
    }


def _compare_mapping(expected: Any, actual: dict[str, Any], label: str) -> list[str]:
    if not isinstance(expected, dict):
        return [f"{label} must be a YAML mapping"]
    failures: list[str] = []
    for key, expected_value in expected.items():
        if key not in actual:
            failures.append(f"{label}: unknown key {key!r}")
        elif actual[key] != expected_value:
            failures.append(
                f"{label}.{key}: expected {expected_value!r}, got {actual[key]!r}"
            )
    return failures


def run_test(
    path: Path,
    *,
    update: bool = False,
    max_cycles: int = 100_000,
    trace_limit: int | None = None,
    show_trace: bool = False,
) -> list[str]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GoldenTestError(f"invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise GoldenTestError("golden YAML root must be a mapping")
    source_names = doc.get("source_files")
    if source_names is None:
        source_name = doc.get("source_file", f"../test/{path.stem}.s")
        source_names = [source_name]
    if not isinstance(source_names, list) or not source_names:
        raise GoldenTestError("source_files must be a non-empty list of relative paths")
    modules = []
    for source_name in source_names:
        if not isinstance(source_name, str) or not source_name.strip():
            raise GoldenTestError("each source file must be a non-empty relative path")
        source_path = (path.parent / source_name).resolve()
        if not source_path.is_file():
            raise GoldenTestError(f"assembly source not found: {source_path}")
        source = source_path.read_text(encoding="utf-8")
        if not source.strip():
            raise GoldenTestError(f"assembly source is empty: {source_path}")
        modules.append(translator.translate(source, name=source_path.name))

    program = linker.link(modules)
    binary = linker.to_binary(program)

    cpu = CPU()
    cpu.load_binary(binary)

    schedule = parse_input_schedule(doc.get("in_input_schedule"))
    stdin = _input_bytes(doc.get("in_stdin"))
    if stdin and not schedule:
        raise GoldenTestError(
            "in_stdin is set but in_input_schedule is missing; specify the cycle(s) "
            "when input bytes arrive"
        )
    for cycle, payload in schedule:
        cpu.schedule_input(cycle, payload)

    cpu.run(max_cycles=max_cycles)

    stdout = getattr(cpu, "output_text", None)
    if stdout is None:
        output = getattr(cpu.memory, "output", b"")
        stdout = bytes(output).decode("utf-8", errors="replace")
    trace_text = render_trace(cpu.trace)
    if show_trace:
        print(f"TRACE {path}")
        print(render_trace(cpu.trace, limit=trace_limit), end="")
    sections = _program_sections(program)
    cache_stats = _cache_snapshot(cpu)

    actual: dict[str, Any] = {
        "binary_hex": binary.hex(" "),
        "stdout": stdout,
        "sections": sections,
        "registers": _register_snapshot(cpu),
        "cycles": int(cpu.cycle),
    }
    if cache_stats is not None:
        actual["cache"] = cache_stats

    if update:
        doc["out_binary_hex"] = actual["binary_hex"]
        doc["out_code_hex"] = actual["binary_hex"]
        doc["out_sections"] = sections
        doc["out_stdout"] = stdout
        doc["out_trace"] = trace_text
        doc.pop("out_log", None)
        doc["out_registers"] = actual["registers"]
        doc["out_cycles"] = actual["cycles"]
        if cache_stats is not None:
            doc["out_cache"] = cache_stats
        path.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )
        return []

    expected_fields = (
        "out_binary_hex",
        "out_code_hex",
        "out_code",
        "out_sections",
        "out_stdout",
        "out_registers",
        "out_cycles",
        "out_cache",
    )
    if not any(field in doc for field in expected_fields):
        return [
            "no expected golden outputs found; run once with --update, "
            "inspect, then commit the YAML"
        ]

    failures: list[str] = []
    expected_binary = _binary_expected(doc)
    if expected_binary is not None and binary != expected_binary:
        failures.append(
            "executable binary differs: "
            f"expected {len(expected_binary)} bytes, got {len(binary)} bytes"
        )

    if "out_sections" in doc and doc["out_sections"] != sections:
        failures.append("linked sections (machine code/data) differ")

    expected_stdout = doc.get("out_stdout")
    if expected_stdout is not None and stdout.rstrip("\n") != str(
        expected_stdout
    ).rstrip("\n"):
        failures.append(f"stdout differs: expected {expected_stdout!r}, got {stdout!r}")

    if "out_registers" in doc:
        failures.extend(
            _compare_mapping(doc["out_registers"], actual["registers"], "registers")
        )
    if "out_cache" in doc:
        if cache_stats is None:
            failures.append(
                "out_cache is specified, but this CPU implementation has no cache"
            )
        else:
            failures.extend(_compare_mapping(doc["out_cache"], cache_stats, "cache"))
    if "out_cycles" in doc and int(doc["out_cycles"]) != cpu.cycle:
        failures.append(
            f"cycle count differs: expected {doc['out_cycles']}, got {cpu.cycle}"
        )

    return failures


def collect_test_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in paths:
        if item.is_dir():
            files.extend(item.glob("*.yml"))
            files.extend(item.glob("*.yaml"))
        elif item.is_file():
            files.append(item)
        else:
            raise GoldenTestError(f"test path does not exist: {item}")
    return sorted(set(files))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CSA4 golden tests: assemble -> link -> simulate -> compare"
    )
    parser.add_argument(
        "tests",
        nargs="*",
        type=Path,
        help="YAML test files or directories (default: golden/yaml)",
    )
    parser.add_argument(
        "--update", action="store_true", help="generate/replace expected outputs"
    )
    parser.add_argument("--max-cycles", type=int, default=100_000)
    parser.add_argument(
        "--trace",
        action="store_true",
        help="print the processor trace for debugging (not saved in golden YAML)",
    )
    parser.add_argument(
        "--trace-limit",
        type=int,
        default=200,
        help="maximum number of cycles to print with --trace (default: 200)",
    )
    args = parser.parse_args(argv)
    if not args.tests:
        project_root = Path(__file__).resolve().parents[2]
        args.tests = [project_root / "golden" / "yaml"]

    if args.max_cycles < 1:
        parser.error("--max-cycles must be positive")
    if args.trace_limit < 1:
        parser.error("--trace-limit must be positive")

    try:
        files = collect_test_files(args.tests)
    except GoldenTestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not files:
        parser.error("no YAML tests found")

    failed = 0
    for path in files:
        try:
            errors = run_test(
                path,
                update=args.update,
                max_cycles=args.max_cycles,
                trace_limit=args.trace_limit,
                show_trace=args.trace,
            )
            if errors:
                failed += 1
                print(f"FAIL {path}")
                for error in errors:
                    print(f"  - {error}")
            else:
                print(f"{'UPDATED' if args.update else 'PASS'} {path}")
        except Exception as exc:
            failed += 1
            print(f"ERROR {path}: {type(exc).__name__}: {exc}")

    passed = len(files) - failed
    print(
        f"\n{passed}/{len(files)} golden tests {'updated' if args.update else 'passed'}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
