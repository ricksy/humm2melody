# Maintenance runbook

Steps to follow after changing anything, so the code, the captures, the README
and the blog post stay in sync. Written for whoever (or whatever) is making the
change — follow it top to bottom and skip what does not apply.

## 0. Before you start

```bash
cd "$(git rev-parse --show-toplevel)"
git status --short          # start clean, or know what is dirty
```

If another agent or editor is working in this repo at the same time, stage your
own paths explicitly instead of `git add -A`, or you will commit their
half-finished work along with yours.

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
brew install vhs                     # once
./scripts/refresh-gifs.sh            # all three, or: refresh-gifs.sh demo
```

The script runs the tests first (a broken app records a broken GIF), clears the
temporary run and profile directories so each capture starts from the same
state, regenerates the GIFs, and builds a **contact sheet** for each — six
frames tiled into one image, skipping the opening while the command is still
being typed.

Then **actually look at the contact sheets.** A capture can record a perfectly
broken UI at a perfectly normal file size. Doing this has caught a level meter
pegged at full, a caption clipped by the sidebar, and a mid-word text wrap.

Check: a note in the live readout, bars in the timeline, rows in the detail
table, three dials aligned, runs in the sidebar, nothing clipped. On the
training capture, check the pitch bar fills the pane and the green band is
several rows tall — it is sized from the widget, so it is the first thing a
layout change breaks.

Keep each GIF under ~1 MB. If a tape gets longer, drop `Set Framerate` to 10.

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

The post lives on a Hugo site. **The deployment details — host, paths, remote —
are deliberately not in this repository**, because it is public and that is
infrastructure. They live in `scripts/blog.env`, which is gitignored; copy
`scripts/blog.env.example` and fill it in once.

```bash
cp scripts/blog.env.example scripts/blog.env   # first time only
./scripts/publish-blog.sh --dry-run            # show what would happen
./scripts/publish-blog.sh --images             # push the GIFs only
./scripts/publish-blog.sh                      # push post text and GIFs
```

The script encodes two traps that are easy to get wrong by hand:

- **It never runs `git add -A` on the server.** That working tree is usually
  dirty with unrelated in-progress posts, and `-A` would commit somebody else's
  work. Only the post and its image directory are ever staged.
- **It always builds with `--destination`.** Plain `hugo` writes to `public/`,
  which is not what is served, so the site would silently not update.

Afterwards it checks the post and both images return `200`, and fails loudly if
not. A `200` on the page with a `404` on an image means the GIFs did not reach
the static directory.

To edit the post text, fetch it into `docs/blog/` (also gitignored), edit, and
publish:

```bash
scp "$BLOG_HOST:$BLOG_SITE/content/posts/$BLOG_SLUG.md" docs/blog/
```

## 6. Quick full pass

```bash
./scripts/refresh-gifs.sh                  # tests + all GIFs + contact sheets
# ...look at the contact sheets before going further...
git add -A && git commit -m "..." && git push
./scripts/publish-blog.sh --images         # GIFs to the blog, rebuild, verify
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
