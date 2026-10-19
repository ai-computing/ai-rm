"""ai-rm L4 placement controller: topology-aware placement written to the airm-placement ConfigMap."""
from .policy import TopologyPlacement

__all__ = ["TopologyPlacement"]
__version__ = "0.1.0"
