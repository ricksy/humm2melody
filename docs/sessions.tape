# Second capture: the Recordings sidebar — rename, load, delete.
#
# Regenerate with:  vhs docs/sessions.tape

Output docs/sessions.gif

Require uv
Require vhs

Set Shell "bash"
Set FontSize 13
Set Width 940
Set Height 700
Set Padding 14
Set Framerate 12
Set TypingSpeed 45ms

# Seed a few past runs off-camera so the sidebar has something in it.
Hide
Type "rm -rf /tmp/h2m-sessions"
Enter
Type "uv run python docs/seed_demo_runs.py /tmp/h2m-sessions > /dev/null"
Enter
Sleep 10s
Type "clear"
Enter
Sleep 500ms
Show

Type "uv run humm2melody --demo --output /tmp/h2m-sessions --profiles /tmp/h2m-profiles"
Sleep 700ms
Enter
Sleep 2500ms

# The startup screen asks who is humming; continue as guest.
Type "g"
Sleep 1500ms

# Record a new run. It is saved automatically and lands at the top.
Space
Sleep 5500ms
Space
Sleep 3s

# Give it a name.
Type "r"
Sleep 1200ms
Type "Chorus idea"
Sleep 1200ms
Enter
Sleep 2500ms

# Walk down to an older run and load it back onto the timeline.
Down
Sleep 800ms
Down
Sleep 800ms
Enter
Sleep 3s

# Delete it, confirming from the keyboard.
Type "d"
Sleep 2s
Type "y"
Sleep 3s

Type "q"
Sleep 800ms
