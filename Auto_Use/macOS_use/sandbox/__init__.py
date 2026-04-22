"""
Sandbox Module - Secure shell execution environment (macOS).

This module provides isolated command execution within a sandboxed workspace,
preventing escape attempts and dangerous operations on the host system.
"""

from .service import Sandbox

__all__ = ['Sandbox']