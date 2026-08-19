"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from .sessions import DEFAULT_OUTPUT_DIR


def analyze_main(argv: list[str]) -> int:
    """`humm2melody analyze <run>` — diagnose a saved recording."""
    parser = argparse.ArgumentParser(
        prog="humm2melody analyze",
        description="Re-run detection over a saved run and report what it saw.",
    )
    parser.add_argument("run", help="a run directory, or a .wav file")
    parser.add_argument(
        "--expect",
        default=None,
        metavar="NOTES",
        help='what you actually hummed, e.g. "C4 D4 E4"',
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="search detection parameters for the best match to --expect",
    )
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--min-rms", type=float, default=0.006)
    parser.add_argument("--min-duration", type=float, default=0.09)
    parser.add_argument("--smoothing", type=int, default=5)
    parser.add_argument("--gap-tolerance", type=float, default=0.07)
    args = parser.parse_args(argv)

    from . import analysis

    audio, sample_rate = analysis.load_run(args.run)
    expected = analysis.parse_expected(args.expect) if args.expect else None

    if args.sweep:
        if not expected:
            parser.error("--sweep needs --expect")
        print(f"sweeping detection parameters against: {' '.join(expected)}\n")
        results = analysis.sweep(audio, sample_rate, expected)
        for distance, params, names in results[:10]:
            settings = "  ".join(f"{k}={v}" for k, v in params.items())
            print(f"  edits={distance}  {' '.join(names) or '(none)':<28}  {settings}")
        best = results[0]
        print(f"\nbest: edits={best[0]} with {best[1]}")
        return 0

    report = analysis.diagnose(
        audio,
        sample_rate,
        min_confidence=args.min_confidence,
        min_rms=args.min_rms,
        min_duration=args.min_duration,
        smoothing=args.smoothing,
        gap_tolerance=args.gap_tolerance,
    )
    print(analysis.format_report(report, expected))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "analyze":
        return analyze_main(argv[1:])

    parser = argparse.ArgumentParser(
        prog="humm2melody",
        description="Hum a melody into your microphone and get the notes to play.",
        epilog="run 'humm2melody analyze <run>' to diagnose a saved recording",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="list available input devices and exit",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="input device index or name (defaults to the system input)",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        metavar="DIR",
        help=f"where to save runs (default: {DEFAULT_OUTPUT_DIR}/)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="do not record runs to disk",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="replay a synthetic hum instead of using the microphone",
    )
    args = parser.parse_args(argv)

    if args.list_devices:
        from .audio import list_input_devices

        for index, name in list_input_devices():
            print(f"{index:>3}  {name}")
        return 0

    device: int | str | None = args.device
    if isinstance(device, str) and device.isdigit():
        device = int(device)

    from .tui import run

    run(
        device=device,
        output_dir=args.output,
        save=not args.no_save,
        demo=args.demo,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
