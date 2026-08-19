"""Populate an output directory with sample runs, for the docs capture.

The Recordings sidebar is only interesting when it has something in it, and
recording several runs live would make the capture far too long. This writes a
few complete runs straight to disk instead.

    uv run python docs/seed_demo_runs.py /tmp/h2m-sessions
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from humm2melody.demo import DemoRecorder, synth_hum
from humm2melody.segment import segment_notes
from humm2melody.sessions import SessionStore

SAMPLE_RUNS: list[tuple[str, list[tuple[int, float]]]] = [
    ("Verse hook", [(64, 0.40), (65, 0.40), (67, 0.50), (65, 0.40), (64, 0.60)]),
    ("Bridge idea", [(60, 0.35), (62, 0.35), (64, 0.35), (65, 0.70)]),
    ("", [(67, 0.40), (69, 0.40), (67, 0.40), (65, 0.60)]),
]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    store = SessionStore(Path(argv[1]))
    when = datetime.now() - timedelta(minutes=45)

    for offset, (label, melody) in enumerate(SAMPLE_RUNS):
        audio = synth_hum(melody, seed=11 + offset)
        recorder = DemoRecorder(audio=audio, realtime=False)
        recorder.start()
        recorder._worker.join(timeout=30)
        recorder._running = False

        session = store.save(
            audio=recorder.audio(),
            sample_rate=recorder.sample_rate,
            frames=recorder.frames(),
            notes=segment_notes(recorder.frames()),
            timestamp=when + timedelta(minutes=offset * 7),
        )
        if label:
            store.rename(session, label)
        print(f"seeded {session.path.name}  ({session.summary})")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
