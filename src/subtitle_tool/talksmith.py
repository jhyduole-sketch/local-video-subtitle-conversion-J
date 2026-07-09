from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import SubtitleToolError


TALKSMITH_SHARE_HOST = "service.talk-smith.com"
TALKSMITH_API_BASE = "https://api.service.talk-smith.com"


@dataclass(frozen=True)
class TalkSmithVideo:
    scenario_id: str
    video_url: str


def is_talksmith_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.netloc == TALKSMITH_SHARE_HOST


def is_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def extract_scenario_id(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.netloc != TALKSMITH_SHARE_HOST or parsed.path != "/s":
        raise SubtitleToolError(
            "Unsupported URL. v1 only supports TalkSmith share URLs like "
            "https://service.talk-smith.com/s?id=..."
        )

    query = urllib.parse.parse_qs(parsed.query)
    scenario_ids = query.get("id", [])
    scenario_id = scenario_ids[0].strip() if scenario_ids else ""
    if not scenario_id:
        raise SubtitleToolError("Invalid TalkSmith share URL: missing id query parameter.")
    return scenario_id


def find_available_video(payload: dict[str, Any], scenario_id: str) -> TalkSmithVideo:
    slides = payload.get("publishedSlides")
    if not isinstance(slides, list):
        raise SubtitleToolError("TalkSmith API response does not contain publishedSlides.")

    for slide in slides:
        if not isinstance(slide, dict) or slide.get("type") != "VIDEO":
            continue
        content = slide.get("publishedVideoSlideContent")
        if not isinstance(content, dict):
            continue
        video = content.get("video")
        if not isinstance(video, dict) or video.get("status") != "AVAILABLE":
            continue
        video_url = video.get("url")
        if isinstance(video_url, str) and video_url:
            return TalkSmithVideo(scenario_id=scenario_id, video_url=video_url)

    raise SubtitleToolError("TalkSmith scenario has no available VIDEO slide.")


def fetch_talksmith_video(url: str) -> TalkSmithVideo:
    scenario_id = extract_scenario_id(url)
    api_url = (
        f"{TALKSMITH_API_BASE}/public/published-scenarios/latest?"
        f"{urllib.parse.urlencode({'scenarioId': scenario_id})}"
    )
    try:
        with urllib.request.urlopen(api_url, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SubtitleToolError(f"TalkSmith scenario not found: {scenario_id}") from exc
        raise SubtitleToolError(f"TalkSmith API request failed with HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise SubtitleToolError(f"TalkSmith API request failed: {exc.reason}") from exc

    if "application/json" not in content_type:
        raise SubtitleToolError("TalkSmith API returned a non-JSON response.")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise SubtitleToolError("TalkSmith API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise SubtitleToolError("TalkSmith API returned an unexpected response shape.")
    return find_available_video(payload, scenario_id)


def download_video(video: TalkSmithVideo, out_dir: Path, force: bool = False) -> Path:
    downloads_dir = out_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    output_path = downloads_dir / f"{video.scenario_id}.mp4"

    if output_path.exists() and output_path.stat().st_size > 0 and not force:
        return output_path

    temp_path = output_path.with_suffix(".mp4.part")
    request = urllib.request.Request(video.video_url, headers={"User-Agent": "subtitle-tool/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            with temp_path.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        raise SubtitleToolError(
            f"Video download failed with HTTP {exc.code}. The signed URL may have expired; retry with --force-download."
        ) from exc
    except urllib.error.URLError as exc:
        raise SubtitleToolError(f"Video download failed: {exc.reason}") from exc
    except OSError as exc:
        raise SubtitleToolError(f"Could not write downloaded video: {exc}") from exc

    if not temp_path.exists() or temp_path.stat().st_size == 0:
        raise SubtitleToolError("Video download produced an empty file.")

    temp_path.replace(output_path)
    return output_path


def resolve_talksmith_input(input_value: str, out_dir: Path, force: bool = False) -> Path:
    return download_video(fetch_talksmith_video(input_value), out_dir, force)

