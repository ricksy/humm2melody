"""Monophonic pitch detection (YIN) and musical note conversion.

Humming is monophonic and lives roughly in the 65-1000 Hz range, so YIN is a
good fit: it is cheap enough to run in real time and it is far more robust
against octave errors than plain autocorrelation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

A4_HZ = 440.0
A4_MIDI = 69


@dataclass(frozen=True)
class PitchFrame:
    """One analysis frame of the incoming audio."""

    time: float  # seconds since recording started
    freq: float  # fundamental in Hz, 0.0 when unvoiced
    confidence: float  # 0..1, YIN periodicity confidence
    rms: float  # linear amplitude of the frame

    @property
    def voiced(self) -> bool:
        return self.freq > 0.0


def hz_to_midi(freq: float) -> float:
    """Fractional MIDI note number. 440 Hz -> 69.0."""
    return A4_MIDI + 12.0 * math.log2(freq / A4_HZ)


def midi_to_hz(midi: float) -> float:
    return A4_HZ * (2.0 ** ((midi - A4_MIDI) / 12.0))


def midi_to_name(midi: int) -> str:
    """MIDI number -> scientific pitch name, e.g. 60 -> 'C4'."""
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def hz_to_note(freq: float) -> tuple[int, str, float]:
    """Return (midi, name, cents_off) for a frequency in Hz."""
    exact = hz_to_midi(freq)
    midi = int(round(exact))
    cents = (exact - midi) * 100.0
    return midi, midi_to_name(midi), cents


def _difference_function(x: np.ndarray, tau_max: int) -> np.ndarray:
    """YIN step 1: the squared-difference function d(tau), computed via FFT.

    d(tau) = sum_j (x[j] - x[j+tau])^2, expanded into two running power terms
    minus twice the autocorrelation so the whole curve costs one FFT pair.
    """
    w = x.size
    tau_max = min(tau_max, w)

    power = np.concatenate(([0.0], np.cumsum(x * x)))
    # Zero-pad to the next power of two so the circular convolution below is
    # a genuine linear one.
    size = 1 << (w + tau_max - 1).bit_length()
    spectrum = np.fft.rfft(x, size)
    acf = np.fft.irfft(spectrum * spectrum.conjugate(), size)[:tau_max]

    return power[w : w - tau_max : -1] + power[w] - power[:tau_max] - 2 * acf


def _cumulative_mean_normalized(diff: np.ndarray) -> np.ndarray:
    """YIN step 2: normalise d(tau) so it starts at 1 and dips at the period."""
    cmnd = np.empty_like(diff)
    cmnd[0] = 1.0
    running = np.cumsum(diff[1:])
    taus = np.arange(1, diff.size)
    cmnd[1:] = diff[1:] * taus / np.maximum(running, 1e-12)
    return cmnd


def _parabolic_refine(cmnd: np.ndarray, tau: int) -> float:
    """Sub-sample the dip so we get cent-level accuracy, not just integer lags."""
    if tau <= 0 or tau >= cmnd.size - 1:
        return float(tau)
    a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
    denom = a + c - 2 * b
    if abs(denom) < 1e-12:
        return float(tau)
    return tau + 0.5 * (a - c) / denom


def detect_pitch(
    frame: np.ndarray,
    sample_rate: int,
    *,
    fmin: float = 65.0,
    fmax: float = 1200.0,
    threshold: float = 0.15,
) -> tuple[float, float]:
    """Estimate the fundamental of one frame.

    Returns ``(freq_hz, confidence)``; ``freq_hz`` is 0.0 when no periodicity
    was found. ``threshold`` is YIN's absolute threshold: the first dip below
    it wins, which is what keeps the detector from jumping an octave up.
    """
    frame = np.asarray(frame, dtype=np.float64)
    if frame.size < 2:
        return 0.0, 0.0

    frame = frame - frame.mean()

    tau_min = max(2, int(sample_rate / fmax))
    tau_max = min(frame.size // 2, int(sample_rate / fmin) + 1)
    if tau_max <= tau_min:
        return 0.0, 0.0

    cmnd = _cumulative_mean_normalized(_difference_function(frame, tau_max))

    tau = -1
    search = cmnd[tau_min:tau_max]
    below = np.flatnonzero(search < threshold)
    if below.size:
        # Walk to the bottom of the first dip that crosses the threshold.
        start = tau_min + int(below[0])
        tau = start
        while tau + 1 < tau_max and cmnd[tau + 1] < cmnd[tau]:
            tau += 1
    else:
        # Nothing crossed the threshold: fall back to the best dip we have and
        # let the confidence value tell the caller how weak it is.
        tau = tau_min + int(np.argmin(search))

    confidence = float(1.0 - min(max(cmnd[tau], 0.0), 1.0))
    refined = _parabolic_refine(cmnd, tau)
    if refined <= 0:
        return 0.0, confidence

    freq = sample_rate / refined
    if not (fmin <= freq <= fmax):
        return 0.0, confidence
    return float(freq), confidence


def rms(frame: np.ndarray) -> float:
    if frame.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))


def center_rms(frame: np.ndarray, span: int) -> float:
    """RMS of the middle ``span`` samples of the frame.

    The long analysis window is needed to *measure* pitch, but using it to
    decide voicing smears note boundaries by its own length — a gap shorter
    than the window never looks fully silent, so repeated notes weld together.
    Measuring energy over a short slice at the window's centre keeps silence
    detection sharp and aligned with the frame's timestamp.
    """
    if span <= 0 or span >= frame.size:
        return rms(frame)
    start = (frame.size - span) // 2
    return rms(frame[start : start + span])


def analyse_signal(
    audio: np.ndarray,
    sample_rate: int,
    *,
    frame_size: int = 2048,
    hop_size: int = 512,
    fmin: float = 65.0,
    fmax: float = 1200.0,
) -> list[PitchFrame]:
    """Run the sliding-window analysis over a whole recording.

    The same windowing the live recorder uses, so offline analysis of a saved
    `hum.wav` sees exactly what the microphone path saw.
    """
    frames: list[PitchFrame] = []
    for end in range(frame_size, len(audio) + 1, hop_size):
        window = audio[end - frame_size : end]
        time = (end - frame_size / 2) / sample_rate
        frames.append(
            analyse_frame(
                window, sample_rate, time, energy_span=hop_size,
                fmin=fmin, fmax=fmax,
            )
        )
    return frames


def analyse_frame(
    frame: np.ndarray,
    sample_rate: int,
    time: float,
    *,
    energy_span: int = 512,
    fmin: float = 65.0,
    fmax: float = 1200.0,
) -> PitchFrame:
    """Full analysis of one window: pitch, confidence and energy."""
    freq, confidence = detect_pitch(frame, sample_rate, fmin=fmin, fmax=fmax)
    return PitchFrame(
        time=time,
        freq=freq,
        confidence=confidence,
        rms=center_rms(frame, energy_span),
    )
