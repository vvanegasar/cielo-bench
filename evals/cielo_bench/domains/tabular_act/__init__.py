"""Act vs. answer (ADR-0009): the tabular domain's company, an agent asked to *do* something.

Each item is one request about one entity. The harness changes the database, not the text: a
scenario patch puts the entity in one of four worlds (``true``, ``far``, ``near``, ``two_table``).
The agent works on a per-trial database in memory, with read tools and write tools, under one
system prompt that states the company's policies. Scoring is a pure function of the fixture, the
patch and the ordered write log.
"""
