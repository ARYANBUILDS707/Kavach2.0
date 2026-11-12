"""SMS dataset preparation for M4.2: acquisition, cleaning, clustering, label audit, synthetic
hard negatives and leakage-safe splitting. Offline only; no model is trained here.

Raw messages exist only under the ignored data directory. Everything this package prints or
commits is aggregate: counts, record IDs, fingerprints and hashes.
"""
