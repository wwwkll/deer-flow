"""Global variables module."""

from .storage import (
    GlobalVariablesStorage,
    get_storage,
    get_system_variables,
)

__all__ = [
    "GlobalVariablesStorage",
    "get_storage",
    "get_system_variables",
]
