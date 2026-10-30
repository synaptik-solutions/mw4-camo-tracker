# MW4 Camo Tracker

Windows screen-based tracker. It reads visible unlock cards; it does not read game memory or automate gameplay.

## Reliability tools

Open **Reliability** in the installed app:

- **Recording replay:** choose a complete gameplay video. Real OCR, banner policies, the bounded capture queue and retry logic run at playback speed. Replay never changes saved progress. Add expected weapon/camo/time windows to score misses and false detections; without expectations those metrics are explicitly unscored. Open the saved report for frame times, read durations, retries and dropped snapshots. The ten most recent replay folders are retained.
- **Failed-read snapshots:** incomplete popup reads save a cropped card and a JSON text/confidence record locally. Open the diagnostic folder from the app. Collection can be disabled. Live diagnostics are limited to 60 entries, 50 MB, and seven days, pruned on startup and saves. No full desktop capture is saved for failed reads and no diagnostics are uploaded. Replay diagnostic crops have the same per-run limits.
- **Targeted retries:** an uncertain read can use up to two clearer buffered frames within 2.5 seconds of the first capture. Every frame is parsed independently; weapon names and camo numbers are never assembled across different banners. Clear reads and explicit non-camo banners skip further retries.
- **Capture health:** producer heartbeats continue during OCR. The app warns about missing heartbeats, sustained blank frames, low measured capture rate and OCR backlog. An unchanged image is labelled as possibly static or stale, not proof of a frozen backend. Read time, overall delay, retry recoveries and dropped snapshot counts are visible.
- **Camo-menu recovery:** choose the weapon shown in-game, start the scan, then keep its camo menu visible. Review the captured image and OCR suggestions. Nothing is selected or written automatically. Only selected, supported camos from that scan can be applied. Explicit unlocked/locked text is recognized; lock icons, unclear text and unsupported layouts require visual verification or the normal Weapons checklist. This is a review-assisted recovery tool, not automatic icon recognition.

Watching pauses during replay/menu analysis and resumes afterward unless you stopped it. Cancel, close and update terminate analysis subprocesses as well as the detector. OCR platform telemetry is disabled before model sessions are created. Offline replay uses only locally cached references and does not refresh them over the network.

## Developer checks

```sh
node scripts/export-camo-catalog.cjs --check
python -m unittest discover -s worker/tests -v
node tests/unlockPolicy.test.js
node tests/reliability.test.js
node tests/reliabilityUi.test.cjs
npm run build:renderer
python worker/detector_launcher.py --self-test-ocr
```

`worker/camo_catalog.py` is generated from the UI catalog with `node scripts/export-camo-catalog.cjs`.

## Replay CLI

```sh
python worker/detector_launcher.py --replay clip.mp4 --report replay-output/run/report.json --mode timed --expected expected.json --assert-expected
```

Expected events use seconds in the video, for example:

```json
[{"weapon":".50 GS","camo":"Military Camo 1","start":84,"end":86}]
```

`--mode timed` measures capture and processing against the video clock. `--mode exhaustive` checks every sampled frame without real-time deadlines; its delays are processing measurements, not live-performance claims. `--resize 1920x1080` tests an upscaled recording, not native 1080p footage. `--no-snapshots` disables failed-read images for a replay.

## Validation limits

The supplied 96.97-second recording has one annotated camo unlock. Both native 720p exhaustive and clocked replays matched it with zero annotated misses and zero false unlocks. The clocked run exercised a successful retry; the first notification was produced about 2.46 seconds after its captured frame. One queued snapshot was dropped, distinct from a missed unlock. An upscaled 1080p exhaustive replay also matched the unlock without false events.

Those results describe one recording on the test runtime. They do not guarantee all HUD styles, HDR settings, menu layouts, native resolutions or Windows capture configurations. Menu parsing and application scope have deterministic tests; an actual camo-menu recording was not supplied. In-game latency and menu suggestions must be checked on the user's setup.

### Center completion banners

The cyan **CHALLENGE COMPLETED** banner has its own visual trigger in the center capture zone. OCR must confirm the completion wording. Banners that omit the weapon/camo are saved locally in a bounded review list (20 entries), with a cropped screenshot, and shown across tracker tabs. They do not change progress until you explicitly choose a supported weapon and camo and click **Assign camo**. Use **Dismiss** for non-camo challenges. The normal overlay says **Banner captured — Needs review** when enabled. The review list survives restarts. This supports the center style observed in the supplied recording; other unseen game layouts still need validation.

Reliability now reports actual scan FPS and last-cycle capture, banner-check, total, and target-budget milliseconds, to separate source latency from visual matching cost. A 6 FPS target allows 166.7 ms per scan across all zones; it does not guarantee six OCR reads per second.

### Larger banner review images

New completion reviews retain a wider capture area above and around the detection zone, including center banner icons that sit above the OCR box. The detector still receives the original region, extracted from the same captured frame. No additional screenshot call is made. Review images preserve their aspect ratio, use the card width, and offer **View larger image**, **Actual size**, and **Fit image** controls. Close the viewer with **Close image** or Escape. Images remain local and bounded; previously saved tightly cropped images cannot recover pixels that were never captured.
