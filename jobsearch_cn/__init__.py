"""AI Job Search CN: China-market extensions to the ai-job-search framework.

Boundaries every module in this package keeps (docs/cn/cn-migration-plan.md
explains each one; tests/test_cn_package.py enforces the first two):

* Standard library only, like the upstream tools/ scripts, so installing the
  project never runs third-party code.
* Offline. This package parses, normalizes, validates and stores job data the
  user supplies (pasted JD text, files they have the right to use). Network
  access belongs to portal adapters under .agents/skills/, which follow the
  /add-portal contract and its robots/ToS checks.
* Job description text is untrusted input: data, never instructions.
* Unknown facts stay null. A value inferred rather than read from the source
  is marked as inferred and never presented as fact.
"""

__version__ = "0.1.0"
