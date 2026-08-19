# Training tab capture: hear a note, sing it, watch the bar.
#
# Regenerate with:  vhs docs/training.tape
#
# Uses --demo, so the "singing" is the same synthetic hum the other captures
# use: C4, C4, G4, G4, A4... The first exercise asks for C4, so a short attempt
# lands on the note and a long one runs off the top of the scale when the hum
# reaches G4. Both are worth showing -- the second is what the red zone is for.

Output docs/training.gif

Require uv
Require vhs

Set Shell "bash"
Set FontSize 13
Set Width 1200
Set Height 760
Set Padding 14
Set Framerate 12
Set TypingSpeed 45ms

Type "uv run humm2melody --demo --output /tmp/h2m-train --profiles /tmp/h2m-profiles"
Sleep 500ms
Enter
Sleep 2200ms

# Continue as guest.
Type "g"
Sleep 1200ms

# Move to the Training tab: the tab bar takes focus, then two steps right.
Tab
Sleep 300ms
Right
Sleep 400ms
Right
Sleep 1500ms

# Hear the target note.
Type "l"
Sleep 1800ms

# Sing it. The tip tracks the voice against the green band.
Space
Sleep 1600ms
Space
Sleep 2800ms

# Again, holding on past the end of the note: the voice climbs to G4, the tip
# pins to the top of the scale with the real figure beside it.
Space
Sleep 3600ms
Space
Sleep 2800ms

# On to the ladder exercise.
Type "x"
Sleep 1000ms
Type "x"
Sleep 2000ms

Type "q"
Sleep 600ms
