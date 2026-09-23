"""Import the Viewer-managed binary layer without relying on site packages."""

from __future__ import annotations

import importlib
import sys
from typing import Any

from app.core.config import settings


class BinaryLayerUnavailableError(RuntimeError):
    pass


def ensure_binary_layer_importable() -> None:
    package_root = settings.resolved_zp_engine_path()
    package_root_text = str(package_root)
    if package_root.is_dir() and package_root_text not in sys.path:
        sys.path.insert(0, package_root_text)
    try:
        importlib.import_module("binary_layer")
    except ModuleNotFoundError as exc:
        raise BinaryLayerUnavailableError("binary_layer_unavailable") from exc


def zp_reader_class() -> type[Any]:
    ensure_binary_layer_importable()
    return importlib.import_module("binary_layer.reader").ZpReader


def bottom_up_reader_class() -> type[Any]:
    ensure_binary_layer_importable()
    return importlib.import_module("binary_layer.bottom_up_reader").BottomUpReader


def top_down_reader_class() -> type[Any]:
    ensure_binary_layer_importable()
    return importlib.import_module("binary_layer.top_down_reader").TopDownReader


def zp_read_error_classes() -> tuple[type[BaseException], ...]:
    ensure_binary_layer_importable()
    module = importlib.import_module("binary_layer.exceptions")
    bottom_up_module = importlib.import_module("binary_layer.bottom_up_exceptions")
    conversion_module = importlib.import_module("binary_layer.conversion_exceptions")
    names = (
        "UnsupportedVersionError",
        "ZpReadError",
        "ZpV2ArrayReadError",
        "ZpVersionNotImplementedError",
    )
    classes = [getattr(module, name) for name in names if hasattr(module, name)]
    for module_obj, name in (
        (bottom_up_module, "BottomUpSchemaError"),
        (conversion_module, "TopDownSchemaError"),
    ):
        if hasattr(module_obj, name):
            classes.append(getattr(module_obj, name))
    return tuple(classes)
