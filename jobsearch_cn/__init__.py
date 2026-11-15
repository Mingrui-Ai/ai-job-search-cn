"""AI Job Search CN: China-market extensions to the ai-job-search framework.

Boundaries every module in this package keeps (docs/cn/cn-migration-plan.md
explains each one; tests/test_cn_package.py enforces the first two):

* Parsing, rules and storage use the standard library and local inputs. The
  package can be imported without installing optional third-party libraries.
* Browser collection is the named ADR-4 exception: browser.py imports
  Playwright inside functions only when collection needs it. Approved-source
  and local-module boundaries are defined in docs/cn/collect.md and ADR-9.
  The package import guards keep that exception limited to browser.py.
* Job description text is untrusted input: data, never instructions.
* Unknown facts stay null. A value inferred rather than read from the source
  is marked as inferred and never presented as fact.
"""

__version__ = "0.2.0"
