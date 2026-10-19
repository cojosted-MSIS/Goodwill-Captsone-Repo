"""Mock HMIS: an entry-only local service.

It accepts three entry operations and returns only success or failure and the
identifiers it assigns. It has no search, lookup, list, or read endpoint. It does
not import the intake app, so it can run as a separate process.
"""
