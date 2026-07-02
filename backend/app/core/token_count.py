import json
import re
from typing import Any


class TokenCounter:
    """Provider-isolated token counter.

    This conservative local counter avoids pure character-length heuristics while
    keeping the first implementation slice credential-free. The adapter boundary
    lets us swap in an Anthropic-native counter later.
    """

    _token_pattern = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def count_text(self, value: str) -> int:
        return len(self._token_pattern.findall(value))

    def count_json(self, value: Any) -> int:
        return self.count_text(json.dumps(value, default=str, sort_keys=True))
