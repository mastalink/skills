#!/usr/bin/env python3
"""Demo Studio quality gate. Standard library only.

Checks a studio project directory (brief.md, claims.json, shots.json,
assets.json, optional final video) and exits non-zero on any finding:

  * every claim has evidence and a status of verified, configured or illustrative
  * every shot references known claims; product claims shown by generated
    media are refused (only real captures may prove a product claim)
  * generated shots carry an on-screen "illustrative" label
  * every asset file exists and matches its recorded sha256
  * no secret-shaped strings in narration, captions, prompts or claims
  * optional: final video duration within tolerance and an audio stream
    exists (ffprobe), and sampled frames contain no secret-shaped text
    (ffmpeg + tesseract), when those tools are installed

Usage: python studio_check.py <project_dir> [--video final.mp4] [--require-media]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CLAIM_STATUSES = {"verified", "configured", "illustrative"}
SHOT_KINDS = {"capture", "generated_image", "generated_video", "diagram", "title"}
GENERATED = {"generated_image", "generated_video"}
SECRET_PATTERNS = [
    re.compile(r"mco_tok_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
]


def _load(path: Path, findings: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        findings.append(f"missing {path.name}")
    except json.JSONDecodeError as exc:
        findings.append(f"{path.name} is not valid JSON: {exc}")
    return None


def secret_hits(text: str) -> list[str]:
    return [p.pattern for p in SECRET_PATTERNS if p.search(text or "")]


def check_claims(claims, findings: list[str]) -> dict:
    by_id = {}
    if not isinstance(claims, list):
        findings.append("claims.json must be a list")
        return by_id
    for claim in claims:
        cid = claim.get("id")
        if not cid or cid in by_id:
            findings.append(f"claim id missing or duplicated: {cid!r}")
            continue
        by_id[cid] = claim
        if claim.get("status") not in CLAIM_STATUSES:
            findings.append(f"claim {cid}: status must be one of {sorted(CLAIM_STATUSES)}")
        if claim.get("status") in {"verified", "configured"} and not claim.get("evidence"):
            findings.append(f"claim {cid}: {claim.get('status')} claims need evidence (commit, run, job or receipt)")
        for hit in secret_hits(json.dumps(claim)):
            findings.append(f"claim {cid}: secret-shaped text ({hit})")
    return by_id


def check_shots(shots, claims: dict, findings: list[str]) -> float:
    total = 0.0
    if not isinstance(shots, list) or not shots:
        findings.append("shots.json must be a non-empty list")
        return total
    seen = set()
    for shot in shots:
        sid = shot.get("id")
        if not sid or sid in seen:
            findings.append(f"shot id missing or duplicated: {sid!r}")
            continue
        seen.add(sid)
        kind = shot.get("kind")
        if kind not in SHOT_KINDS:
            findings.append(f"shot {sid}: kind must be one of {sorted(SHOT_KINDS)}")
        duration = shot.get("duration_s")
        if not isinstance(duration, (int, float)) or duration <= 0:
            findings.append(f"shot {sid}: duration_s must be a positive number")
        else:
            total += float(duration)
        for cid in shot.get("claim_ids", []):
            claim = claims.get(cid)
            if claim is None:
                findings.append(f"shot {sid}: unknown claim {cid}")
            elif kind in GENERATED and claim.get("status") != "illustrative":
                findings.append(f"shot {sid}: generated media cannot carry {claim.get('status')} claim {cid}; use a real capture")
        if kind in GENERATED and "illustrative" not in (shot.get("label") or "").lower():
            findings.append(f"shot {sid}: generated media needs an on-screen label containing 'illustrative'")
        text = " ".join(str(shot.get(k) or "") for k in ("narration", "caption", "prompt", "source"))
        for hit in secret_hits(text):
            findings.append(f"shot {sid}: secret-shaped text ({hit})")
    return total


def check_assets(project: Path, assets, findings: list[str]) -> None:
    if not isinstance(assets, list):
        findings.append("assets.json must be a list")
        return
    for asset in assets:
        rel = asset.get("path")
        if not rel:
            findings.append("asset without path")
            continue
        path = (project / rel).resolve()
        if project.resolve() not in path.parents:
            findings.append(f"asset {rel}: path escapes the project directory")
            continue
        if not path.is_file():
            findings.append(f"asset {rel}: file missing")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if asset.get("sha256") != digest:
            findings.append(f"asset {rel}: sha256 mismatch")
        if asset.get("generator") and not asset.get("license"):
            findings.append(f"asset {rel}: record the model/tool license or terms")


def check_video(video: Path, planned: float, require: bool, findings: list[str], notes: list[str]) -> None:
    if not video.is_file():
        findings.append(f"video {video} missing")
        return
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        (findings if require else notes).append("ffprobe not installed; video checks skipped")
        return
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                            "-of", "json", str(video)], capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        findings.append(f"ffprobe failed: {probe.stderr.strip()[:200]}")
        return
    info = json.loads(probe.stdout or "{}")
    duration = float(info.get("format", {}).get("duration") or 0)
    if planned and abs(duration - planned) > max(2.0, planned * 0.10):
        findings.append(f"video is {duration:.1f}s; shot list plans {planned:.1f}s")
    if "audio" not in {s.get("codec_type") for s in info.get("streams", [])}:
        findings.append("video has no audio stream")
    ffmpeg, tesseract = shutil.which("ffmpeg"), shutil.which("tesseract")
    if not (ffmpeg and tesseract):
        (findings if require else notes).append("ffmpeg/tesseract not installed; frame secret scan skipped")
        return
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([ffmpeg, "-v", "error", "-i", str(video), "-vf", "fps=1/2",
                        str(Path(tmp) / "f%04d.png")], check=False)
        for frame in sorted(Path(tmp).glob("f*.png")):
            ocr = subprocess.run([tesseract, str(frame), "-"], capture_output=True, text=True, check=False)
            for hit in secret_hits(ocr.stdout):
                findings.append(f"frame {frame.name}: secret-shaped text on screen ({hit})")


def run(project: Path, video: Path | None, require_media: bool) -> tuple[list[str], list[str]]:
    findings: list[str] = []
    notes: list[str] = []
    if not (project / "brief.md").is_file():
        findings.append("missing brief.md")
    claims = check_claims(_load(project / "claims.json", findings) or [], findings)
    planned = check_shots(_load(project / "shots.json", findings) or [], claims, findings)
    check_assets(project, _load(project / "assets.json", findings) or [], findings)
    for name in ("captions.srt", "narration.txt"):
        path = project / name
        if path.is_file():
            for hit in secret_hits(path.read_text(encoding="utf-8", errors="replace")):
                findings.append(f"{name}: secret-shaped text ({hit})")
    if video is not None:
        check_video(video, planned, require_media, findings, notes)
    return findings, notes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--require-media", action="store_true",
                        help="treat missing ffprobe/ffmpeg/tesseract as a failure")
    args = parser.parse_args(argv)
    findings, notes = run(args.project, args.video, args.require_media)
    print(json.dumps({"pass": not findings, "findings": findings, "notes": notes}, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
