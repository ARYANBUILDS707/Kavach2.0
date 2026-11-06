"""Isolated pretrained SMS inference worker.

Runs as a child process of the KAVACH API and speaks length-prefixed JSON over stdin/stdout
(docs/M4_SMS_INFERENCE_ARCHITECTURE.md §5). It never opens a socket, never logs message text and
returns only numbers. Third-party weights, not a KAVACH-trained model; outputs are uncalibrated.
"""
