"""Compatibility wrapper for the workflow route module."""

from server.routes.workflow import (
    approve,
    get_normalized_artifacts_route,
    get_run_manifest_route,
    list_events_route,
    list_runs_route,
    reject,
    router,
    websocket_endpoint,
)

list_events = list_events_route
list_runs = list_runs_route
get_run_manifest = get_run_manifest_route
get_normalized_artifacts = get_normalized_artifacts_route

__all__ = [
    "approve",
    "reject",
    "router",
    "list_events",
    "list_runs",
    "get_run_manifest",
    "get_normalized_artifacts",
    "websocket_endpoint",
]
