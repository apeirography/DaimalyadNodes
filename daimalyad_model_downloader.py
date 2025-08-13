# daimalyad_model_downloader.py
# -----------------------------------------------------------------------------
# Model Downloader by DaimAlYad
# a ComfyUI Utility Node for Workflow-Based Model Downloading
# Class/Key: DaimalyadModelDownloader
# Category: utils
#
# Copyright © 2025 Daïm Al-Yad (@daimalyad)
# Licensed under the MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# -----------------------------------------------------------------------------

import os
import re
import ssl
import time
import errno
import shutil
import hashlib
import tempfile
import urllib.request
import urllib.error
from urllib.parse import urlparse
from pathlib import Path

# ComfyUI models directory
try:
    from folder_paths import models_dir as COMFY_MODELS_DIR
except Exception:
    COMFY_MODELS_DIR = str(Path(os.getcwd()) / "models")

# ---- Configuration / constants ----------------------------------------------

LOG_PREFIX = "[DMD]"
USER_AGENT_DEFAULT = "ComfyUI-DaimalyadModelDownloader/1.0"
CHUNK_BYTES = 1024 * 1024       # 1 MiB read size
PROGRESS_MI_B_STEP = 16         # log every ~16 MiB
RETRY_DEFAULT = 3               # default network retries
RETRY_BACKOFF_S = 2.0           # base backoff between retries
REPLACE_RETRY_MAX = 30          # attempts to overcome transient file locks
REPLACE_RETRY_SLEEP_S = 0.25    # sleep between replace attempts

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# ---- Helpers -----------------------------------------------------------------

def _safe_part(part: str) -> str:
    return _SAFE_NAME_RE.sub("_", part).strip("._") or "_"

def _derive_filename_from_url(url: str) -> str:
    base = Path(urlparse(url).path).name or "downloaded_model"
    return _safe_part(base)

def _safe_subpath_and_filename(subfolder: str, filename: str, url: str):
    raw = subfolder.strip().lstrip("/\\")
    parts = [p for p in Path(raw).parts if p not in ("", ".", "..")]
    safe_sub = Path(*(_safe_part(p) for p in parts)) if parts else Path()
    fname = _safe_part((filename or _derive_filename_from_url(url)).strip())
    return safe_sub, fname

def _ensure_within_models_dir(path: Path) -> None:
    root = Path(COMFY_MODELS_DIR).resolve()
    target = path.resolve()
    try:
        if not target.is_relative_to(root):
            raise RuntimeError(f"{LOG_PREFIX} Subfolder resolves outside /models — please check the path.")
    except AttributeError:
        if os.path.commonpath([str(root), str(target)]) != str(root):
            raise RuntimeError(f"{LOG_PREFIX} Subfolder resolves outside /models — please check the path.")

def _sha256_file(path: Path, bufsize: int = CHUNK_BYTES) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(bufsize)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def _human_size(nbytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(nbytes)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.1f} {u}"
        size /= 1024.0

def _looks_like_error_payload(head: bytes) -> str | None:
    s = head.lstrip().lower()
    if s.startswith(b"<!doctype html") or s.startswith(b"<html"):
        return "Server returned HTML (possibly an error or login page)."
    if s.startswith(b"{") and b'"error"' in s[:4096]:
        return "Server returned JSON with an error field."
    return None

def _atomic_replace_with_retry(tmp_path: Path, dest: Path) -> None:
    """
    Attempt atomic replace; on Windows or AV-scanned files, replace() may
    transiently fail with PermissionError. Retry briefly and then give up.
    """
    attempts = 0
    while True:
        try:
            tmp_path.replace(dest)
            return
        except PermissionError as e:
            attempts += 1
            if attempts >= REPLACE_RETRY_MAX:
                raise RuntimeError(f"{LOG_PREFIX} Could not finalize file due to a lock (e.g., antivirus). "
                                   f"Tried {REPLACE_RETRY_MAX} times. Last error: {e}")
            time.sleep(REPLACE_RETRY_SLEEP_S)
        except OSError as e:
            if e.errno in (errno.EACCES, getattr(errno, "EBUSY", 16)):
                attempts += 1
                if attempts >= REPLACE_RETRY_MAX:
                    raise RuntimeError(f"{LOG_PREFIX} Could not finalize file (resource busy). "
                                       f"Tried {REPLACE_RETRY_MAX} times. Last error: {e}")
                time.sleep(REPLACE_RETRY_SLEEP_S)
            else:
                raise

def _download_once(url: str, dest: Path, timeout: float, user_agent: str) -> int:
    """
    Stream download to a temp file, then atomically move to dest.
    Returns total bytes written. Raises RuntimeError on obvious server error payloads.
    """
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    dest.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        # Free-space sanity (only if server provides content-length)
        cl = r.headers.get("Content-Length")
        if cl is not None:
            try:
                needed = int(cl)
                total, used, free = shutil.disk_usage(dest.parent)
                if free < max(0, needed - dest.stat().st_size if dest.exists() else needed):
                    raise RuntimeError(f"{LOG_PREFIX} Not enough free space. "
                                       f"Need ~{_human_size(needed)}, free {_human_size(free)}.")
            except ValueError:
                pass  # malformed header -> ignore

        ctype = (r.headers.get("Content-Type") or "").lower()

        # Create temp file beside destination
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=dest.parent) as tmp:
            tmp_path = Path(tmp.name)

        total = 0
        next_progress = PROGRESS_MI_B_STEP * 1024 * 1024
        t0 = time.time()
        wrote_any = False

        try:
            with tmp_path.open("wb") as out:
                # first chunk (sniff for common error payloads)
                first = r.read(CHUNK_BYTES)
                if first:
                    wrote_any = True
                    if ("text/html" in ctype or "application/json" in ctype):
                        reason = _looks_like_error_payload(first[:4096])
                        if reason:
                            raise RuntimeError(f"{LOG_PREFIX} {reason}")
                    reason = _looks_like_error_payload(first[:4096])
                    if reason:
                        raise RuntimeError(f"{LOG_PREFIX} {reason}")

                    out.write(first)
                    total += len(first)

                # stream remainder
                while True:
                    block = r.read(CHUNK_BYTES)
                    if not block:
                        break
                    out.write(block)
                    total += len(block)
                    if total >= next_progress:
                        dt = max(1e-6, time.time() - t0)
                        speed = total / dt  # bytes/s
                        print(f"{LOG_PREFIX} {_human_size(total)} downloaded "
                              f"({(_human_size(speed))}/s approx)")
                        next_progress += PROGRESS_MI_B_STEP * 1024 * 1024

            if total == 0 and wrote_any is False:
                raise RuntimeError(f"{LOG_PREFIX} Download resulted in 0 bytes; refusing to create/overwrite the target.")

            _atomic_replace_with_retry(tmp_path, dest)
            return total

        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

def _download_with_retry(url: str, dest: Path, timeout: float, user_agent: str, retries: int = RETRY_DEFAULT) -> int:
    attempt = 0
    while True:
        try:
            if attempt > 0:
                print(f"{LOG_PREFIX} Retry {attempt}/{retries}…")
            return _download_once(url, dest, timeout, user_agent)
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError) as e:
            if attempt >= retries:
                raise
            wait = RETRY_BACKOFF_S * (2 ** (attempt))
            print(f"{LOG_PREFIX} Transient network error: {e}. Backing off {wait:.1f}s before retry.")
            time.sleep(wait)
            attempt += 1

# ---- Node --------------------------------------------------------------------

class DaimalyadModelDownloader:
    """
    Download a file from HTTP(S) into ComfyUI/models/<subfolder>/filename

    Inputs:
      - url: http(s) URL to the file
      - subfolder: /models relative subfolder (can be nested, e.g. "controlnet/myset")
      - filename: optional; if blank, derived from URL basename
      - overwrite: if True and file exists, re-download (default: True)
      - sha256: optional 64-hex digest; if provided, verify after download
      - timeout_s: network timeout (seconds)
      - retries: number of retries for transient network errors (default 3)
      - user_agent: HTTP User-Agent header string

    Output:
      - path: absolute path to the downloaded (or existing) file
    """

    CATEGORY = "utils"
    FUNCTION = "download"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("path",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "url": ("STRING", {"multiline": False, "default": ""}),
                "subfolder": ("STRING", {
                    "multiline": False,
                    "default": "checkpoints",
                    "tooltip": "Relative path under /models (nested OK). Examples: "
                               "checkpoints, loras, vae, controlnet/myset, clip, unet, upscale_models"
                }),
            },
            "optional": {
                "filename": ("STRING", {"multiline": False, "default": ""}),
                "overwrite": ("BOOLEAN", {"default": True}),
                "sha256": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "label": "SHA-256 (optional)",
                    "tooltip": "(Optional) 64-hex SHA-256 for integrity check"
                }),
                "timeout_s": ("INT", {"default": 120, "min": 5, "max": 86400, "step": 5}),
                "retries": ("INT", {"default": RETRY_DEFAULT, "min": 0, "max": 10, "step": 1}),
                "user_agent": ("STRING", {"multiline": False, "default": USER_AGENT_DEFAULT}),
            },
        }

    def download(
        self,
        url: str,
        subfolder: str,
        filename: str = "",
        overwrite: bool = True,
        sha256: str = "",
        timeout_s: int = 120,
        retries: int = RETRY_DEFAULT,
        user_agent: str = USER_AGENT_DEFAULT,
    ):
        # --- URL validation
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            raise RuntimeError(f"{LOG_PREFIX} URL must start with http:// or https://")
        if not parsed.netloc:
            raise RuntimeError(f"{LOG_PREFIX} URL appears to be missing a hostname.")

        url_basename = Path(parsed.path).name or "(no name)"

        # --- Sanitize target path parts
        safe_subfolder, safe_filename = _safe_subpath_and_filename(subfolder, filename, url)
        models_root = Path(COMFY_MODELS_DIR)
        target_path = models_root / safe_subfolder / safe_filename
        _ensure_within_models_dir(target_path)

        # Logging: start line
        print(f"{LOG_PREFIX} Fetching '{url_basename}'")
        print(f"{LOG_PREFIX} → Subfolder: '{safe_subfolder.as_posix() or '.'}', File: '{safe_filename}'")

        # --- Download (or skip if exists and overwrite disabled)
        if target_path.exists() and not overwrite:
            print(f"{LOG_PREFIX} File exists, skipping download: {target_path}")
        else:
            print(f"{LOG_PREFIX} Downloading to: {target_path}")
            total = _download_with_retry(url, target_path, float(timeout_s), user_agent, retries=max(0, int(retries)))
            print(f"{LOG_PREFIX} Download complete. Size: {_human_size(total)}")

        # --- Optional checksum verification
        digest = sha256.strip().lower()
        if digest:
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise RuntimeError(f"{LOG_PREFIX} SHA-256 must be a 64-character hex string.")
            print(f"{LOG_PREFIX} Verifying SHA-256…")
            got = _sha256_file(target_path)
            if got != digest:
                try:
                    target_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise RuntimeError(f"{LOG_PREFIX} SHA-256 mismatch.\nExpected: {digest}\nGot:      {got}")
            print(f"{LOG_PREFIX} SHA-256 OK.")

        return (str(target_path),)

# ---- Registration ------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "DaimalyadModelDownloader": DaimalyadModelDownloader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DaimalyadModelDownloader": "Model Downloader by DaimAlYad",
}
