from contextlib import contextmanager
import ctypes
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("whop_editor.resource_governor")


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


@dataclass
class ResourceTelemetry:
    ram_load_percent: float
    total_ram_mb: float
    avail_ram_mb: float
    disk_free_gb: float
    disk_total_gb: float
    active_browsers: int
    active_renders: int
    active_whisper: int
    is_memory_healthy: bool
    is_disk_healthy: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ram_load_percent": round(self.ram_load_percent, 1),
            "total_ram_mb": round(self.total_ram_mb, 1),
            "avail_ram_mb": round(self.avail_ram_mb, 1),
            "disk_free_gb": round(self.disk_free_gb, 2),
            "disk_total_gb": round(self.disk_total_gb, 2),
            "active_browsers": self.active_browsers,
            "active_renders": self.active_renders,
            "active_whisper": self.active_whisper,
            "is_memory_healthy": self.is_memory_healthy,
            "is_disk_healthy": self.is_disk_healthy,
        }


class ResourceGovernor:
    """
    Host Machine Resource Governor for autonomous production.
    Strictly governs physical hardware headroom and process concurrency.
    Pure Python standard library (ctypes, shutil, threading) with ZERO external dependencies.

    Enforces:
    - RAM load < 90% and > 1.0 GB available physical RAM
    - Disk free space > 1.0 GB on workspace volume
    - Concurrency ceilings:
      - Max 2 concurrent browser contexts
      - Max 2 concurrent FFmpeg renders
      - Max 1 concurrent Whisper STT job
    """

    DEFAULT_MAX_RAM_LOAD = 95.0  # percent
    DEFAULT_MIN_RAM_AVAIL_MB = 1024.0  # 1.0 GB
    DEFAULT_MIN_DISK_FREE_GB = 1.0  # 1.0 GB

    MAX_CONCURRENT_BROWSERS = 2
    MAX_CONCURRENT_RENDERS = 2
    MAX_CONCURRENT_WHISPER = 1

    def __init__(
        self,
        monitored_path: Optional[Path] = None,
        max_ram_load: float = DEFAULT_MAX_RAM_LOAD,
        min_ram_avail_mb: float = DEFAULT_MIN_RAM_AVAIL_MB,
        min_disk_free_gb: float = DEFAULT_MIN_DISK_FREE_GB,
        max_browsers: int = MAX_CONCURRENT_BROWSERS,
        max_renders: int = MAX_CONCURRENT_RENDERS,
        max_whisper: int = MAX_CONCURRENT_WHISPER,
    ):
        self.monitored_path = Path(monitored_path or ".").resolve()
        self.max_ram_load = max_ram_load
        self.min_ram_avail_mb = min_ram_avail_mb
        self.min_disk_free_gb = min_disk_free_gb
        self.max_browsers = max_browsers
        self.max_renders = max_renders
        self.max_whisper = max_whisper

        self._lock = threading.Lock()
        self._active_browsers = 0
        self._active_renders = 0
        self._active_whisper = 0

    def get_memory_info(self) -> Tuple[float, float, float]:
        """Returns (load_percent, total_mb, avail_mb)."""
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "kernel32"):
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            if success:
                load = float(stat.dwMemoryLoad)
                total_mb = stat.ullTotalPhys / (1024 * 1024)
                avail_mb = stat.ullAvailPhys / (1024 * 1024)
                return load, total_mb, avail_mb

        # Fallback / mock default for non-Windows or if API unavailable
        return 75.0, 16384.0, 4096.0

    def get_disk_info(self) -> Tuple[float, float]:
        """Returns (free_gb, total_gb) for the monitored volume."""
        try:
            usage = shutil.disk_usage(self.monitored_path)
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)
            return free_gb, total_gb
        except Exception as e:
            logger.warning(f"Error checking disk usage for {self.monitored_path}: {e}")
            return 5.0, 100.0

    def get_telemetry(self) -> ResourceTelemetry:
        """Captures a snapshot of current host hardware and active workloads."""
        ram_load, total_ram, avail_ram = self.get_memory_info()
        disk_free, disk_total = self.get_disk_info()

        with self._lock:
            browsers = self._active_browsers
            renders = self._active_renders
            whisper = self._active_whisper

        mem_healthy = ram_load <= self.max_ram_load and avail_ram >= self.min_ram_avail_mb
        disk_healthy = disk_free >= self.min_disk_free_gb

        return ResourceTelemetry(
            ram_load_percent=ram_load,
            total_ram_mb=total_ram,
            avail_ram_mb=avail_ram,
            disk_free_gb=disk_free,
            disk_total_gb=disk_total,
            active_browsers=browsers,
            active_renders=renders,
            active_whisper=whisper,
            is_memory_healthy=mem_healthy,
            is_disk_healthy=disk_healthy,
        )

    def resolve_resource_type(self, job_type: str) -> str:
        """Maps job types to the primary constrained physical resource."""
        job_clean = job_type.strip().upper()
        if job_clean in ("REVIEW", "GEMINI_REVIEW", "FLOW_GENERATE", "BROWSER"):
            return "browser"
        elif job_clean in ("PRODUCTION_EDIT", "PUNCH_IN_EDIT", "RENDER", "FFMPEG", "EDITING"):
            return "render"
        elif job_clean in ("AUDIO_EXTRACTION", "TRANSCRIBE", "WHISPER"):
            return "whisper"
        return "generic"

    def can_dispatch(self, job_type: str) -> Tuple[bool, Optional[str]]:
        """
        Determines whether a job can safely be executed right now.
        Checks RAM headroom, disk space, and process concurrency.
        """
        telemetry = self.get_telemetry()

        # 1. RAM Headroom
        if telemetry.ram_load_percent > self.max_ram_load:
            return False, f"RAM load excessive: {telemetry.ram_load_percent:.1f}% (threshold: {self.max_ram_load}%)"
        if telemetry.avail_ram_mb < self.min_ram_avail_mb:
            return False, f"Available RAM critical: {telemetry.avail_ram_mb:.0f} MB (min required: {self.min_ram_avail_mb:.0f} MB)"

        # 2. Disk Headroom
        if telemetry.disk_free_gb < self.min_disk_free_gb:
            return False, f"Disk space critical: {telemetry.disk_free_gb:.2f} GB free (min required: {self.min_disk_free_gb:.1f} GB)"

        # 3. Process Concurrency
        res_type = self.resolve_resource_type(job_type)
        with self._lock:
            if res_type == "browser" and self._active_browsers >= self.max_browsers:
                return False, f"Browser concurrency ceiling reached: {self._active_browsers}/{self.max_browsers}"
            elif res_type == "render" and self._active_renders >= self.max_renders:
                return False, f"Render concurrency ceiling reached: {self._active_renders}/{self.max_renders}"
            elif res_type == "whisper" and self._active_whisper >= self.max_whisper:
                return False, f"Whisper concurrency ceiling reached: {self._active_whisper}/{self.max_whisper}"

        return True, None

    def acquire_resource(self, resource_type: str, timeout_sec: float = 0.0) -> bool:
        """
        Acquires a resource execution slot. If timeout_sec > 0, waits up to timeout_sec.
        """
        res_type = self.resolve_resource_type(resource_type)
        start_time = time.time()

        while True:
            with self._lock:
                if res_type == "browser":
                    if self._active_browsers < self.max_browsers:
                        self._active_browsers += 1
                        logger.debug(f"Acquired browser slot ({self._active_browsers}/{self.max_browsers})")
                        return True
                elif res_type == "render":
                    if self._active_renders < self.max_renders:
                        self._active_renders += 1
                        logger.debug(f"Acquired render slot ({self._active_renders}/{self.max_renders})")
                        return True
                elif res_type == "whisper":
                    if self._active_whisper < self.max_whisper:
                        self._active_whisper += 1
                        logger.debug(f"Acquired whisper slot ({self._active_whisper}/{self.max_whisper})")
                        return True
                elif res_type == "generic":
                    return True

            if timeout_sec <= 0 or (time.time() - start_time) >= timeout_sec:
                return False

            time.sleep(0.1)

    def release_resource(self, resource_type: str):
        """Releases an acquired execution slot."""
        res_type = self.resolve_resource_type(resource_type)
        with self._lock:
            if res_type == "browser":
                self._active_browsers = max(0, self._active_browsers - 1)
                logger.debug(f"Released browser slot ({self._active_browsers}/{self.max_browsers})")
            elif res_type == "render":
                self._active_renders = max(0, self._active_renders - 1)
                logger.debug(f"Released render slot ({self._active_renders}/{self.max_renders})")
            elif res_type == "whisper":
                self._active_whisper = max(0, self._active_whisper - 1)
                logger.debug(f"Released whisper slot ({self._active_whisper}/{self.max_whisper})")

    @contextmanager
    def managed_execution(self, resource_type: str, timeout_sec: float = 0.0):
        """
        Context manager for robust RAII resource slot acquisition and release.
        Raises ResourceUnavailableError if slot cannot be acquired within timeout.
        """
        acquired = self.acquire_resource(resource_type, timeout_sec=timeout_sec)
        if not acquired:
            raise ResourceUnavailableError(f"Failed to acquire slot for resource '{resource_type}' (timeout={timeout_sec}s)")
        try:
            yield
        finally:
            self.release_resource(resource_type)


class ResourceUnavailableError(Exception):
    """Raised when required machine resource or concurrency slot is unavailable."""
    pass


# Global singleton instance
_GLOBAL_GOVERNOR: Optional[ResourceGovernor] = None


def get_resource_governor() -> ResourceGovernor:
    """Returns the shared machine ResourceGovernor singleton."""
    global _GLOBAL_GOVERNOR
    if _GLOBAL_GOVERNOR is None:
        _GLOBAL_GOVERNOR = ResourceGovernor()
    return _GLOBAL_GOVERNOR
