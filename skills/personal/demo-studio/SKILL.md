---
name: demo-studio
description: Produce a product demo, explainer, promo clip, voiceover, or image set with local and cloud generative models, gated by a claim ledger so nothing on screen overstates what the product does. Use when asked to make a demo, video, trailer, explainer, screencast, narration, voiceover, thumbnail, hero image, or "media" for BitCadence, Via, MOSES, or another project on Beast.
---

# Demo Studio

Generated media is a way to make true things vivid, never a way to make untrue
things look real. Every stage below serves that rule. Real captures prove what
the product does. Generated media sets mood or illustrates a concept, and it is
labeled "illustrative" on screen.

Work in `studio/<slug>/` inside the project's repository (or the Score's
artifact root). Every stage writes a file, so another agent can pick up
mid-stream and a reviewer can check each decision.

```
studio/<slug>/
  brief.md          stage 1
  capabilities.json stage 0
  claims.json       stage 2
  shots.json        stage 3
  assets/           stage 4 outputs
  assets.json       stage 4 ledger (sha256, generator, model, seed, license)
  narration.txt  captions.srt  final.mp4  poster.png   stage 5
  review.json       stage 7
```

`example/` in this skill is a complete, passing stage-3 project to copy.

## Stage 0: Find out what's actually available

Don't assume which models are installed. Probe, then record the results in
`capabilities.json`:

- **ComfyUI** (Beast, default `http://127.0.0.1:8188`): `GET /system_stats` for
  the GPU and VRAM, and `GET /object_info/CheckpointLoaderSimple` (plus the
  UNet/VAE/CLIP loader nodes for newer models) for the installed models.
- **Voice:** Kokoro through MOSES (`moses.voice.tts.KokoroTTS`, kokoro-onnx) is
  the local default. ElevenLabs is available only if its key is configured;
  record the key's *name*, never its value.
- **Tools:** `ffmpeg`, `ffprobe`, `tesseract`, and Playwright with the
  pre-installed Chromium.
- **Cloud image, video and audio APIs:** record only which provider keys exist
  by name. Cloud generation costs money, so it needs a stated per-project cap in
  `brief.md` before any call.

If a needed capability is missing, say so and propose the smallest substitute
(for example, a diagram instead of generated video). Don't install models or
drivers without asking.

## Stage 1: Brief

Write `brief.md`: audience, the single payoff sentence, length, destination
(private link, website, investor, app store), public or private, voice choice,
and the spending cap for cloud generation (default $0, which means local only).

## Stage 2: Claim ledger, before any script

List every factual statement the piece will make in `claims.json`:

```json
{"id": "C1", "text": "...", "status": "verified|configured|illustrative", "evidence": "commit / run ID / job ID / receipt / doc"}
```

- `verified`: an observed result with a receipt (a CI run, job history, benchmark
  output, or a recorded session).
- `configured`: the code or infrastructure is defined that way, but you haven't
  observed it running. The narration must say "is designed to" or "is
  configured to".
- `illustrative`: mood or metaphor; it may appear only over generated or
  diagram shots.

Anything you can't evidence gets cut or reworded. Read the project's evidence
docs first (for BitCadence, `docs/INVESTOR-DEMO-STORYBOARDS.md` sets the
recording rules; for Via, `docs/CURRENT_STATE.md` and `docs/reviews/`). Where
those docs and the code disagree, trust the code and receipts, and note the
drift.

## Stage 3: Script and shot list

Write `shots.json`. Each shot is one of `capture`, `generated_image`,
`generated_video`, `diagram` or `title`, with `duration_s`, `narration`,
`claim_ids`, and a `prompt` (generated) or `source` (capture/diagram).
Generated shots need `"label": "Illustrative …"`. Keep the sum of durations
within 10% of the brief's length.

Run the gate now, before spending GPU time or money:

```bash
python <skill>/scripts/studio_check.py studio/<slug>
```

## Stage 4: Make the assets (local first)

| Shot kind | First choice | Fallback |
|---|---|---|
| `capture` | Playwright recording of the real app with synthetic data (`recordVideo`, a fixed viewport, a scripted path). Never show real tokens: use a throwaway instance or blur the connection panel | Screen recording by Joe |
| `generated_image` | ComfyUI on Beast using a workflow saved in **API format**: `POST /prompt` `{"prompt": <graph>, "client_id": <uuid>}`, poll `GET /history/<prompt_id>`, fetch `GET /view?filename=…&subfolder=…&type=output` | Cloud image API within the cap |
| `generated_video` | ComfyUI video workflow on Beast if one is installed (check stage 0) | A cloud video API within the cap, or a pan-and-zoom over a still |
| `diagram` | Mermaid or hand-written SVG rendered in Chromium | — |
| narration | Kokoro locally, one file per shot, so timing edits stay local | ElevenLabs for a hero cut, if configured |
| music | A licensed library track, with its license recorded | Silence beats an unlicensed track |

Record every file in `assets.json` with its path, sha256, generator, model,
seed, prompt and license/terms. Keep ComfyUI workflow JSON in
`studio/workflows/`, so a render can be reproduced from a seed.

Hard lines:

- No voice or likeness of a real person without their explicit consent.
  Joe's voice or face requires Joe's yes for that specific piece.
- No generated people presented as users, customers, clergy or testimonials.
- No generated UI presented as the product.
- No logos or trademarks of other organizations in generated imagery.

## Stage 5: Assemble

Render each shot to a clip of its exact duration. Concatenate the clips, add
narration, burn in captions, and normalize loudness:

```bash
ffmpeg -f concat -safe 0 -i clips.txt -i narration.wav \
  -vf "subtitles=captions.srt" -af "loudnorm=I=-16:TP=-1.5:LRA=11" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest final.mp4
ffmpeg -ss 00:00:03 -i final.mp4 -frames:v 1 poster.png
```

Always ship `captions.srt` alongside the video as well.

## Stage 6: Quality gate

```bash
python <skill>/scripts/studio_check.py studio/<slug> --video studio/<slug>/final.mp4 --require-media
```

The gate fails on:

- claims without evidence
- generated media carrying a `verified` or `configured` claim
- missing "illustrative" labels
- asset hash drift
- secret-shaped text in narration, captions, prompts or claims
- duration drift beyond 10%
- a missing audio track
- secret-shaped text visible in sampled frames (OCR)

Fix everything the gate reports before review. Never edit the checker to get a
pass.

## Stage 7: Independent review

A different identity from the builder, preferably a different vendor, reviews
the exact `final.mp4` sha256. It watches the video (or reads a contact sheet of
1-per-2s frames plus `narration.txt`), re-checks each claim against its
evidence, and writes `review.json`:

```json
{"verdict": "pass|fail", "video_sha256": "...", "findings": ["..."]}
```

## Stage 8: Publish as a draft

Upload to the private destination named in the brief. Anything public (website,
social, app store, investor send) needs Joe's explicit approval of that exact
file. Under BitCadence, that is a Score human checkpoint.

## Running it as a BitCadence Score

`examples/scores/demo-studio-via.score.json` in BitCadence maps these stages to
Score tasks: claims and script on cloud-capable roles, rendering on a `studio`
role registered on Beast (GPU), and review by a different identity. Under
Score Cloud v2 (`docs/SCORE-CLOUD-V2.md`), render tasks run on the `local`
lane and everything else can run on `cloud-session` or `api` lanes.
