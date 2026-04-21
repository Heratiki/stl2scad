"""
Lightweight tests for GUI helper utilities.
"""

from stl2scad.gui.main_window import _format_acceleration_report, _resolve_gui_workers


def test_format_acceleration_report_includes_devices_and_recommendations():
    report = {
        "gpu_detected": True,
        "gpu_compute_ready": False,
        "gpu_compute_backend": "cupy",
        "gpu_compute_reason": "CuPy not installed",
        "devices": [
            {
                "vendor": "NVIDIA",
                "name": "RTX Example",
                "memory_total": "12 GB",
            }
        ],
        "recommendations": ["Install CuPy."],
    }

    formatted = _format_acceleration_report(report)

    assert "Acceleration Report" in formatted
    assert "GPU detected: True" in formatted
    assert "- NVIDIA: RTX Example (12 GB)" in formatted
    assert "- Install CuPy." in formatted


def test_resolve_gui_workers_zero_means_auto(monkeypatch):
    monkeypatch.setattr("stl2scad.gui.main_window.os.cpu_count", lambda: 64)

    assert _resolve_gui_workers(0) == 32
    assert _resolve_gui_workers(3) == 3
