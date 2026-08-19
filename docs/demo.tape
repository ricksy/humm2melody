# Main screen capture: hum, transcribe, play it back.
#
# Regenerate with:  vhs docs/demo.tape
#
# Uses --demo so the capture is reproducible without a microphone, and a
# throwaway --output so it never writes into the real recordings/ directory.

Output docs/demo.gif

Require uv
Require vhs

Set Shell "bash"
Set FontSize 13
Set Width 940
Set Height 700
Set Padding 14
Set Framerate 12
Set TypingSpeed 45ms

Type "uv run humm2melody --demo --output /tmp/h2m-demo"
Sleep 700ms
Enter
Sleep 3s

# Start humming. The melody is ~4.4s long.
Space
Sleep 5500ms

# Stop: the timeline, the note sequence and the detail table appear.
Space
Sleep 3s

# Hear the transcription played back, with the playhead sweeping across.
Type "p"
Sleep 5500ms

Sleep 1500ms
Type "q"
Sleep 800ms
