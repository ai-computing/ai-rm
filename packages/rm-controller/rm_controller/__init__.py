"""ai-rm L4 placement controller: topology-aware and optimal P/D placement written to the airm-placement ConfigMap."""
from .optimal import OptimalPlacement
from .policy import TopologyPlacement

__all__ = ["OptimalPlacement", "TopologyPlacement"]
__version__ = "0.2.0"
