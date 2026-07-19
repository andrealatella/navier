"""Windows system TTS: Italian text to a PCM WAV via the default SAPI voice."""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

from ..config import Settings

logger = logging.getLogger("navier.tts.system")

_WAV_HEADER_BYTES = 44

_PS_SCRIPT = r"""param([string]$OutFile, [string]$VoiceName, [int]$Rate)
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  if ($VoiceName) {
    $synth.SelectVoice($VoiceName)
  } else {
    $it = $synth.GetInstalledVoices() |
      Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'it*' } |
      Select-Object -First 1
    if ($it) { $synth.SelectVoice($it.VoiceInfo.Name) }
  }
} catch { }
$synth.Rate = $Rate
$synth.SetOutputToWaveFile($OutFile)
$synth.Speak([Console]::In.ReadToEnd())
$synth.Dispose()
"""


class SystemSynth:
    """Wraps the Windows system voice plus a small disk cache. One shared instance."""

    def __init__(self, settings: Settings) -> None:
        self._voice = settings.tts_voice
        self._rate = settings.tts_rate
        self._cache = settings.tts_cache_path
        self._cache.mkdir(parents=True, exist_ok=True)
        self._script = self._cache / "_speak.ps1"
        self._script.write_text(_PS_SCRIPT, encoding="utf-8")
        self._persist_keys: set[str] = set()
        self._live = self._cache / "_live.wav"

    def available(self) -> bool:
        """True when PowerShell is on PATH (Windows) so System.Speech can be driven."""
        return shutil.which("powershell") is not None

    def _key(self, text: str) -> str:
        raw = f"{self._voice}|{self._rate}|{text}".encode()
        return hashlib.sha1(raw).hexdigest()[:16]

    def register_persistent(self, texts) -> None:
        """Mark phrases whose WAV may live on disk (the warmed static safety lines)."""
        for t in texts:
            self._persist_keys.add(self._key((t or "").strip()))

    def prune(self) -> None:
        """Delete every cached WAV that is not a registered persistent phrase."""
        keep = {f"{k}.wav" for k in self._persist_keys}
        for f in self._cache.glob("*.wav"):
            if f.name not in keep:
                _unlink(f)

    def synth(self, text: str) -> Path | None:
        """Return a WAV path for `text`. Blocking."""
        text = (text or "").strip()
        if not text:
            return None
        persistent = self._key(text) in self._persist_keys
        out = (self._cache / f"{self._key(text)}.wav") if persistent else self._live
        if persistent and out.exists() and out.stat().st_size > _WAV_HEADER_BYTES:
            return out
        if not self.available():
            logger.warning("system TTS unavailable: powershell not found on PATH")
            return None

        tmp = out.with_suffix(".tmp.wav")
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self._script),
            "-OutFile",
            str(tmp),
            "-VoiceName",
            self._voice,
            "-Rate",
            str(self._rate),
        ]
        try:
            proc = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("system TTS synth error: %s", e)
            _unlink(tmp)
            return None

        if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size <= _WAV_HEADER_BYTES:
            logger.warning(
                "system TTS failed rc=%s: %s",
                proc.returncode,
                proc.stderr.decode("utf-8", "replace")[:200],
            )
            _unlink(tmp)
            return None
        tmp.replace(out)
        return out


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
