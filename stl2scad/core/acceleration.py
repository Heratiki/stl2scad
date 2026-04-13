"""Hardware acceleration detection and recommendations.

This module provides lightweight GPU discovery and a practical recommendation
layer for optional compute acceleration in stl2scad.
"""

from __future__ import annotations

from functools import lru_cache
import importlib.util
import shutil
import subprocess
from typing import Any, Dict, List


_GPU_RUNTIME_FAILURES: Dict[str, str] = {}


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _run_command(args: List[str], timeout: int = 3) -> str:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _parse_nvidia_smi_devices() -> List[Dict[str, Any]]:
    if shutil.which("nvidia-smi") is None:
        return []

    out = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader",
        ]
    )
    devices: List[Dict[str, Any]] = []
    if not out:
        return devices

    for idx, line in enumerate(out.splitlines()):
        parts = [p.strip() for p in line.split(",")]
        if not parts:
            continue
        devices.append(
            {
                "index": idx,
                "vendor": "nvidia",
                "name": parts[0],
                "driver": parts[1] if len(parts) > 1 else "",
                "memory_total": parts[2] if len(parts) > 2 else "",
            }
        )
    return devices


def _parse_lspci_devices() -> List[Dict[str, Any]]:
    if shutil.which("lspci") is None:
        return []

    out = _run_command(["lspci"])
    if not out:
        return []

    devices: List[Dict[str, Any]] = []
    for line in out.splitlines():
        text = line.lower()
        if "vga" not in text and "3d controller" not in text:
            continue

        vendor = "unknown"
        if "nvidia" in text:
            vendor = "nvidia"
        elif "amd" in text or "advanced micro devices" in text or "radeon" in text:
            vendor = "amd"
        elif "intel" in text:
            vendor = "intel"

        devices.append(
            {
                "vendor": vendor,
                "name": line,
                "driver": "",
                "memory_total": "",
            }
        )
    return devices


def _cupy_cuda_status() -> Dict[str, Any]:
    if not _has_module("cupy"):
        return {"available": False, "device_count": 0, "error": "cupy_not_installed"}

    try:
        import cupy as cp  # type: ignore

        count = int(cp.cuda.runtime.getDeviceCount())
        if count <= 0:
            return {
                "available": False,
                "device_count": 0,
                "error": "cuda_device_not_found",
            }
        return {"available": True, "device_count": count, "error": ""}
    except Exception as exc:
        return {
            "available": False,
            "device_count": 0,
            "error": f"cupy_runtime_error:{type(exc).__name__}",
        }


def _torch_gpu_status() -> Dict[str, Any]:
    if not _has_module("torch"):
        return {
            "available": False,
            "device_count": 0,
            "backend": "none",
            "error": "torch_not_installed",
        }

    try:
        import torch  # type: ignore

        cuda_like_available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if cuda_like_available else 0
        if not cuda_like_available or device_count <= 0:
            return {
                "available": False,
                "device_count": 0,
                "backend": "none",
                "error": "torch_gpu_not_available",
            }

        hip_version = getattr(torch.version, "hip", None)
        cuda_version = getattr(torch.version, "cuda", None)
        backend = "rocm" if hip_version else "cuda"

        return {
            "available": True,
            "device_count": device_count,
            "backend": backend,
            "hip_version": hip_version or "",
            "cuda_version": cuda_version or "",
            "error": "",
        }
    except Exception as exc:
        return {
            "available": False,
            "device_count": 0,
            "backend": "none",
            "error": f"torch_runtime_error:{type(exc).__name__}",
        }


def _torch_vulkan_status() -> Dict[str, Any]:
    if not _has_module("torch"):
        return {"available": False, "backend": "vulkan", "error": "torch_not_installed"}

    try:
        import torch  # type: ignore

        vulkan_backend = getattr(getattr(torch, "backends", None), "vulkan", None)
        if vulkan_backend is None:
            return {
                "available": False,
                "backend": "vulkan",
                "error": "torch_vulkan_backend_missing",
            }

        is_available = bool(vulkan_backend.is_available())
        if not is_available:
            return {
                "available": False,
                "backend": "vulkan",
                "error": "torch_vulkan_not_available",
            }

        return {
            "available": True,
            "backend": "vulkan",
            "error": "",
        }
    except Exception as exc:
        return {
            "available": False,
            "backend": "vulkan",
            "error": f"torch_vulkan_runtime_error:{type(exc).__name__}",
        }


def _vulkan_runtime_status() -> Dict[str, Any]:
    if shutil.which("vulkaninfo") is None:
        return {
            "available": False,
            "error": "vulkaninfo_not_found",
            "summary": "",
        }

    summary = _run_command(["vulkaninfo", "--summary"], timeout=5)
    if not summary:
        summary = _run_command(["vulkaninfo"], timeout=5)
    if not summary:
        return {
            "available": False,
            "error": "vulkan_runtime_unavailable",
            "summary": "",
        }

    return {
        "available": True,
        "error": "",
        "summary": summary.splitlines()[0] if summary else "",
    }


@lru_cache(maxsize=1)
def get_acceleration_report() -> Dict[str, Any]:
    """Collect GPU hardware and acceleration readiness information."""
    devices = _parse_nvidia_smi_devices()
    if not devices:
        devices = _parse_lspci_devices()

    cupy_status = _cupy_cuda_status()
    torch_status = _torch_gpu_status()
    torch_vulkan_status = _torch_vulkan_status()
    vulkan_status = _vulkan_runtime_status()

    vendors = sorted({str(d.get("vendor", "unknown")) for d in devices})
    recommendations: List[str] = []

    if not devices:
        recommendations.append("No GPU detected. CPU mode is recommended.")
    elif "nvidia" in vendors:
        if not cupy_status["available"] and not torch_status["available"]:
            recommendations.append(
                "Install CuPy for CUDA acceleration (for example: pip install cupy-cuda12x)."
            )
            recommendations.append(
                "Or install a CUDA-enabled PyTorch build for GPU acceleration fallback."
            )
            recommendations.append(
                "Ensure NVIDIA driver and CUDA runtime are available to Python."
            )
        else:
            recommendations.append(
                "GPU acceleration is available (CuPy or PyTorch CUDA)."
            )
    elif "amd" in vendors:
        if torch_status["available"] and torch_status.get("backend") == "rocm":
            recommendations.append(
                "PyTorch ROCm detected; GPU acceleration is available for deduplication."
            )
        elif torch_vulkan_status["available"]:
            recommendations.append(
                "PyTorch Vulkan detected; Vulkan GPU fallback path is available."
            )
        else:
            recommendations.append(
                "AMD GPU detected. Install a ROCm-enabled PyTorch build to enable GPU acceleration."
            )
            if vulkan_status["available"]:
                recommendations.append(
                    "Vulkan runtime is present; install a PyTorch build with Vulkan backend to use Vulkan fallback."
                )
            recommendations.append(
                "After install, verify with: python -m stl2scad acceleration --json"
            )
    else:
        recommendations.append(
            "GPU detected but no supported compute backend configured; CPU mode is used."
        )

    gpu_compute_ready = bool(
        cupy_status["available"]
        or torch_status["available"]
        or torch_vulkan_status["available"]
    )
    if cupy_status["available"]:
        gpu_compute_reason = "cupy_cuda_ready"
        gpu_compute_backend = "cupy"
    elif torch_status["available"]:
        torch_backend = str(torch_status.get("backend", "torch"))
        gpu_compute_reason = f"torch_{torch_backend}_ready"
        gpu_compute_backend = "torch"
    elif torch_vulkan_status["available"]:
        gpu_compute_reason = "torch_vulkan_ready"
        gpu_compute_backend = "torch_vulkan"
    else:
        gpu_compute_reason = (
            f"{cupy_status['error']};{torch_status['error']};"
            f"{torch_vulkan_status['error']}"
        )
        gpu_compute_backend = "none"

    return {
        "gpu_detected": bool(devices),
        "devices": devices,
        "vendors": vendors,
        "cupy_cuda": cupy_status,
        "torch_gpu": torch_status,
        "torch_vulkan": torch_vulkan_status,
        "vulkan_runtime": vulkan_status,
        "gpu_compute_ready": gpu_compute_ready,
        "gpu_compute_backend": gpu_compute_backend,
        "gpu_compute_reason": gpu_compute_reason,
        "recommendations": recommendations,
    }


def resolve_compute_backend(requested: str = "auto") -> Dict[str, str]:
    """Resolve requested compute backend to actual backend with reason."""
    mode = requested.strip().lower()
    if mode not in {"auto", "cpu", "gpu"}:
        raise ValueError("compute backend must be one of: auto, cpu, gpu")

    if mode == "cpu":
        return {"requested": mode, "used": "cpu", "reason": "requested_cpu"}

    report = get_acceleration_report()
    ready = bool(report.get("gpu_compute_ready", False))
    reason = str(report.get("gpu_compute_reason", "unknown"))

    if mode == "gpu":
        if ready:
            return {"requested": mode, "used": "gpu", "reason": "requested_gpu"}
        return {
            "requested": mode,
            "used": "cpu",
            "reason": f"gpu_unavailable:{reason}",
        }

    # auto
    if ready:
        backend = str(report.get("gpu_compute_backend", "none"))
        if backend in _GPU_RUNTIME_FAILURES:
            cached_reason = _GPU_RUNTIME_FAILURES[backend]
            return {
                "requested": mode,
                "used": "cpu",
                "reason": f"auto_cpu:cached_gpu_failure:{backend}:{cached_reason}",
            }
        return {"requested": mode, "used": "gpu", "reason": "auto_gpu_ready"}
    return {"requested": mode, "used": "cpu", "reason": f"auto_cpu:{reason}"}


def register_gpu_runtime_failure(backend: str, reason: str) -> None:
    """Remember a backend-specific GPU runtime failure for this process."""
    key = backend.strip().lower()
    if not key:
        return
    _GPU_RUNTIME_FAILURES[key] = reason.strip()[:240]
