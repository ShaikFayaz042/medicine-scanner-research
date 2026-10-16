"""Compatibility wrapper for workflow WebSocket management."""

from server.services.workflow_websocket import broadcast, manager

__all__ = ["broadcast", "manager"]
