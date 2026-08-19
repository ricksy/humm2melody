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
    # Defaults come from the dials rather than being written out again here.
    # A diagnostic that does not reproduce what the app does is worse than
    # none, and duplicated constants drift apart the moment one is retuned.
    parser.add_argument(
        "--sensitivity",
        type=int,
        default=5,
        metavar="1-9",
        help="pitch dial level to analyse at (default: 5)",
    )
    parser.add_argument(
        "--pause",
        type=int,
        default=5,
        metavar="1-9",
        help="pause dial level to analyse at (default: 5)",
    )
    for flag, kind in (
        ("--min-confidence", float),
        ("--min-rms", float),
        ("--min-duration", float),
        ("--smoothing", int),
        ("--gap-tolerance", float),
        ("--max-glide-rate", float),
    ):
        parser.add_argument(
            flag, type=kind, default=None, help="override the dial-derived value"
        )
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

    from .segment import pause_settings, sensitivity_settings

    settings = {**sensitivity_settings(args.sensitivity), **pause_settings(args.pause)}
    settings.setdefault("min_confidence", 0.55)
    for name in (
        "min_confidence",
        "min_rms",
        "min_duration",
        "smoothing",
        "gap_tolerance",
        "max_glide_rate",
    ):
        override = getattr(args, name)
        if override is not None:
            settings[name] = override or None if name == "max_glide_rate" else override

    report = analysis.diagnose(audio, sample_rate, **settings)
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
        "--profiles",
        default=None,
        metavar="DIR",
        help="where user profiles live (default: profiles/)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        metavar="NAME",
        help="use this profile and skip the startup chooser",
    )
    parser.add_argument(
        "--guest",
        action="store_true",
        help="start as guest and skip the startup chooser",
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

    from .profiles import DEFAULT_PROFILE_DIR, ProfileStore, guest
    from .tui import run

    profile_dir = args.profiles or DEFAULT_PROFILE_DIR
    chosen = None
    if args.guest:
        chosen = guest()
    elif args.profile:
        store = ProfileStore(profile_dir)
        chosen = next(
            (p for p in store.list() if p.name.casefold() == args.profile.casefold()),
            None,
        )
        if chosen is None:
            parser.error(f"no profile called {args.profile!r}")

    run(
        device=device,
        output_dir=args.output,
        save=not args.no_save,
        demo=args.demo,
        profile_dir=profile_dir,
        profile=chosen,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
