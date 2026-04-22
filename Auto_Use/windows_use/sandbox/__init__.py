"""
Sandbox Module - Secure PowerShell execution environment.

This module provides isolated command execution within a sandboxed workspace,
preventing escape attempts and dangerous operations on the host system.
"""

from .service import Sandbox

__all__ = ['Sandbox']