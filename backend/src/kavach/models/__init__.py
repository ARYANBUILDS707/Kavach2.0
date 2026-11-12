"""Inference adapters and artifact manifests (ARCHITECTURE.md `backend/models/`).

Nothing here imports torch or any ML library: models run in separate worker processes with their
own environments, and this package only supervises them.
"""
