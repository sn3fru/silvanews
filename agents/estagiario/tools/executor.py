"""
Estagiário v3 — Tool executor (thin re-export).

All tool logic (implementations, schemas, dispatch) lives in definitions.py.
This module exists for backward-compatible imports.
"""

from .definitions import dispatch_tool, build_tool_declarations

__all__ = ["dispatch_tool", "build_tool_declarations"]
