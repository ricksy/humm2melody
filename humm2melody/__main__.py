"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from .sessions import DEFAULT_OUTPUT_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="humm2melody",
        description="Hum a melody into your microphone and get the notes to play.",
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
