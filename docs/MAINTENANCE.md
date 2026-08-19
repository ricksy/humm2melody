# Maintenance runbook

Steps to follow after changing anything, so the code, the captures, the README
and the blog post stay in sync. Written for whoever (or whatever) is making the
change — follow it top to bottom and skip what does not apply.

## 0. Before you start

```bash
cd /Users/ahmedshaban/dev/humm2melody
git status --short          # start clean, or know what is dirty
```

## 1. Code and tests

```bash
uv sync
uv run pytest -q
```

All tests must pass before anything else happens. They need no microphone and
no speaker, so a failure is real.

If you changed detection (`pitch.py`, `segment.py`), also confirm the demo
melody still transcribes exactly — a broken detector would otherwise silently
produce a broken screen capture:

```bash
uv run pytest -q tests/test_demo.py
```

## 2. Regenerate the screen captures

Only needed if you changed the **UI, the demo melody, or the detector**.

```bash
brew install vhs                # once
rm -rf /tmp/h2m-demo /tmp/h2m-sessions
vhs docs/demo.tape              # -> docs/demo.gif      (~20s, ~290 KB)
vhs docs/sessions.tape          # -> docs/sessions.gif  (~30s, ~550 KB)
```

Then **actually look at them** before committing. Extract a few frames rather
than trusting the recording:

```bash
ffmpeg -ss 14 -i docs/demo.gif -frames:v 1 /tmp/check.png -y
```

Check: the live note readout shows a note, the timeline has bars, the detail
table has rows, the sidebar lists runs. Past captures have caught a pegged
level meter and a mid-word text wrap this way.

Keep both GIFs under ~1 MB. If a tape gets longer, drop `Set Framerate` to 10.

### If the timings drift

The tapes hard-code sleeps matched to the demo melody (~4.4s of audio). If you
change `DEMO_MELODY` in `humm2melody/demo.py`, re-check every `Sleep` in both
tapes, especially the 5500ms waits after `Space`.

## 3. README

Update whichever of these the change touches:

- the feature description near the top
- the **key bindings table**
- the **saved runs** file listing
- the **tuning table** of detection parameters
- the test count in the vibe-coded callout (`uv run pytest -q` prints it)

## 4. Push to GitHub

Repo: <https://github.com/ricksy/humm2melody> (public, MIT).

```bash
git add -A
git commit -m "..."
git push
```

> **Note:** the local SSH keys are not authorised on GitHub. This repo is
> configured to push over HTTPS using the `gh` token, via a **repo-local**
> credential helper (`git config --local credential.https://github.com.helper`).
> Do not "fix" this by switching the remote back to SSH.

## 5. Blog post

Live at <https://mufradat.com/posts/humm2melody/>. Hugo + PaperMod, served from
`/var/www/html`, source in `/var/www/mufradat`, git remote is **Codeberg**.

### Update the text

```bash
scp mufradat:/var/www/mufradat/content/posts/humm2melody.md /tmp/post.md
# edit /tmp/post.md
scp /tmp/post.md mufradat:/var/www/mufradat/content/posts/humm2melody.md
```

### Update the images

```bash
scp docs/demo.gif docs/sessions.gif \
    mufradat:/var/www/mufradat/static/images/humm2melody/
```

### Build and publish

```bash
ssh mufradat 'cd /var/www/mufradat && hugo --destination /var/www/html'
```

`--destination /var/www/html` is required. Plain `hugo` writes to `public/`,
which is **not** what is served and will just create noise in git.

### Commit on the server

> **Important:** the server's working tree is usually dirty with unrelated
> in-progress work (other posts, stale `public/` output). **Never run
> `git add -A` there**, despite what `/var/www/mufradat/README.md` says. Stage
> only your own paths:

```bash
ssh mufradat 'cd /var/www/mufradat && \
  git add content/posts/humm2melody.md static/images/humm2melody/ && \
  git commit -m "Update humm2melody post" && git push'
```

### Verify it is actually live

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://mufradat.com/posts/humm2melody/
curl -s -o /dev/null -w "%{http_code}\n" https://mufradat.com/images/humm2melody/demo.gif
```

Both must be `200`. A `200` on the page but `404` on an image means the GIFs
were not copied to `static/images/humm2melody/`.

## 6. Quick full pass

```bash
uv run pytest -q \
  && vhs docs/demo.tape && vhs docs/sessions.tape \
  && git add -A && git commit -m "..." && git push \
  && scp docs/*.gif mufradat:/var/www/mufradat/static/images/humm2melody/ \
  && ssh mufradat 'cd /var/www/mufradat && hugo --destination /var/www/html \
       && git add content/posts/humm2melody.md static/images/humm2melody/ \
       && git commit -m "Update humm2melody images" && git push'
```

## Things that are easy to get wrong

| Trap | What happens |
| --- | --- |
| `git add -A` on the server | commits the user's unrelated in-progress posts |
| plain `hugo` with no `--destination` | writes to `public/`, site does not update |
| forgetting to copy GIFs to the server | post renders, images 404 |
| trusting a capture without viewing frames | ships a GIF of a broken UI |
| switching the GitHub remote to SSH | push fails, keys are not authorised |
| committing `recordings/` | it is gitignored on purpose — real user audio |
