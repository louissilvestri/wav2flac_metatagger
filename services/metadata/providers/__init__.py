"""Provider plugins. Each module normalizes one source into common shapes.

Conventions:
- Every public function is wrapped in the aggregator's try/except — providers
  may raise; the aggregator records the failure and continues.
- Network calls go through ratelimit.wait(name) and cache.cached(...).
"""
