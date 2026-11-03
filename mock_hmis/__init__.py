"""Mock HMIS: a local stand-in for HMIS, run as its own process.

Writes come only through its POST entry routes, which return only success or failure
and the identifiers it assigns; there is no HTTP read route. Its records live in a
SQLite file that the intake system reads only through allowlisted read-only views,
standing in for read-only SQL access to the real HMIS [TBC with CHIP]. It does not
import the intake app.
"""
