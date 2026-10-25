"""Privacy-first, on-demand VTM camera access for the robot."""

from __future__ import annotations

import base64
import json
import subprocess
import time
from typing import Any
from urllib.parse import urlparse

from pyezvizapi.exceptions import PyEzvizError

from .vtm_stream import (
    VtmChannel,
    VtmStreamClient,
    build_vtm_url,
    decrypt_hikvision_ps_video,
)


def _session_sign(session_id: Any) -> str:
    if not session_id:
        raise PyEzvizError("No active EZVIZ session")
    parts = str(session_id).split(".")
    if len(parts) < 2:
        raise PyEzvizError("EZVIZ session is not a JWT token")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    sign = claims.get("s") if isinstance(claims, dict) else None
    if not isinstance(sign, str) or not sign:
        raise PyEzvizError("EZVIZ session does not contain a VTDU signature")
    return sign


def _auth_base_url(token: dict[str, Any]) -> str:
    service_urls = token.get("service_urls")
    auth_addr = (
        str(service_urls.get("authAddr", "")).strip()
        if isinstance(service_urls, dict)
        else ""
    )
    parsed_auth = urlparse(
        auth_addr
        if auth_addr.startswith(("http://", "https://"))
        else f"https://{auth_addr}"
    )
    if (parsed_auth.hostname or "").casefold() not in {"", "none", "null"}:
        return f"https://{parsed_auth.hostname}"

    api_url = str(token.get("api_url", "")).strip()
    parsed_api = urlparse(api_url if "://" in api_url else f"https://{api_url}")
    host = parsed_api.hostname or ""
    if host.startswith("apii") and host.endswith(".ezvizlife.com"):
        region = host[4 : -len(".ezvizlife.com")]
        if region:
            return f"https://{region}auth.ezvizlife.com"
    raise PyEzvizError("Could not determine the VTDU authorization server")


def _find_resource(
    pagelist: dict[str, Any], serial: str, channel: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    resources = pagelist.get("resourceInfos") or []
    resource = next(
        (
            item
            for item in resources
            if isinstance(item, dict)
            and str(item.get("deviceSerial", "")).upper() == serial.upper()
            and str(item.get("localIndex", "")) == str(channel)
            and str(item.get("resourceCategory", "")).casefold() == "video"
        ),
        None,
    )
    if not isinstance(resource, dict):
        raise PyEzvizError("No robot video resource")
    vtms = pagelist.get("VTM") or {}
    vtm = vtms.get(resource.get("resourceId")) if isinstance(vtms, dict) else None
    if not isinstance(vtm, dict):
        raise PyEzvizError("No VTM streaming server for the robot")
    return resource, vtm


def _vtdu_token(client: Any) -> str:
    token = getattr(client, "_token", None)
    session = getattr(client, "_session", None)
    if not isinstance(token, dict) or session is None:
        raise PyEzvizError("Active EZVIZ session is unavailable")
    session_id = token.get("session_id")
    response = session.get(
        f"{_auth_base_url(token)}/vtdutoken2",
        params={"ssid": session_id, "sign": _session_sign(session_id)},
        timeout=getattr(client, "_timeout", 25),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("retcode") not in (0, "0"):
        raise PyEzvizError(f"VTDU server rejected the token: {payload.get('retcode')}")
    tokens = payload.get("tokens")
    if not isinstance(tokens, list) or not tokens or not isinstance(tokens[0], str):
        raise PyEzvizError("VTDU server did not return a streaming token")
    return tokens[0]


def build_cloud_stream(
    client: Any, serial: str, channel: int = 1
) -> tuple[VtmStreamClient, dict[str, Any]]:
    """Build an unopened cloud stream and safe metadata."""
    pagelist = client._api_get_pagelist(page_filter="VTM", limit=50)
    if not isinstance(pagelist, dict):
        raise PyEzvizError("EZVIZ did not return VTM metadata")
    resource, vtm = _find_resource(pagelist, serial, channel)
    host = vtm.get("externalIp") or vtm.get("domain") or vtm.get("internalIp")
    port = int(vtm.get("port") or 0)
    if not host or not 1 <= port <= 65535:
        raise PyEzvizError("Invalid VTM server address")
    stream_url = build_vtm_url(
        str(host),
        port,
        serial,
        str(resource.get("streamBizUrl") or ""),
        _vtdu_token(client),
        channel=channel,
    )
    return VtmStreamClient(stream_url, timeout=10), {
        "host": str(host),
        "port": port,
        "channel": channel,
        "resource_type": resource.get("resourceType"),
        "video_level": resource.get("videoLevel"),
    }


def trace_cloud_stream(client: Any, serial: str) -> dict[str, Any]:
    """Open a short stream trace and return metadata only, never media bytes."""
    stream, metadata = build_cloud_stream(client, serial)
    with stream:
        events = stream.trace_packets(max_packets=12)
        info = stream.stream_info
    return {
        **metadata,
        "events": [event.as_dict() for event in events],
        "stream_result": info.result if info else None,
        "has_stream_session": bool(info and info.streamssn),
    }


def capture_cloud_snapshot(
    client: Any,
    serial: str,
    ffmpeg_path: str,
    *,
    duration_seconds: float = 3.5,
) -> bytes:
    """Capture one JPEG; the cloud video connection exists only during this call."""
    stream, _metadata = build_cloud_stream(client, serial)
    payloads: list[bytes] = []
    deadline = time.monotonic() + duration_seconds
    with stream:
        stream.start()
        for packet in stream.iter_packets(max_packets=500):
            if packet.channel == VtmChannel.ENCRYPTED_STREAM:
                raise PyEzvizError("VTM stream uses an unsupported channel encryption")
            payloads.append(packet.body)
            if time.monotonic() >= deadline:
                break
    raw = b"".join(payloads)
    if not raw:
        raise PyEzvizError("Robot camera did not return an image")

    candidates = [raw]
    get_cam_key = getattr(client, "get_cam_key", None)
    if callable(get_cam_key):
        try:
            media_key = get_cam_key(serial)
            if media_key:
                candidates.append(
                    decrypt_hikvision_ps_video(raw, media_key, nalu_header_size=None)
                )
        except Exception:
            pass

    last_error = ""
    for candidate in candidates:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-frames:v",
                "1",
                "-f",
                "image2",
                "pipe:1",
            ],
            input=candidate,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0 and result.stdout.startswith(b"\xff\xd8"):
            return result.stdout
        last_error = result.stderr.decode(errors="replace")[-500:]
    raise PyEzvizError(f"Could not read a video frame: {last_error}")
