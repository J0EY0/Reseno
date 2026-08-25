from __future__ import annotations

from typing import Literal

# Provider-neutral runtime action selected by capability discovery. Adapters
# consume this value without needing a model-name table: ``provider_default``
# deliberately emits no control, while the two native modes request the
# provider's verified automatic or explicit-budget protocol respectively.
ThinkingControl = Literal[
    "none",
    "provider_default",
    "native_auto",
    "native_budget",
]
