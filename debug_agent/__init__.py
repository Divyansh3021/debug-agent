"""Reference implementation of an agentic debugging system.

The graph is: collect evidence, decide how much autonomy is allowed, fan out
root-cause specialists, classify a grounded diagnosis, plan a mitigation,
validate it, then write a reviewable diff. See ARCHITECTURE.md for why the
pipeline is shaped this way.
"""

from debug_agent.service import run_debug

__version__ = "0.1.0"

__all__ = ["__version__", "run_debug"]
