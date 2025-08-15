# daimalyad_wildcard_processor.py
# -----------------------------------------------------------------------------
# API-Friendly Wildcard Processor by DaimAlYad
# a ComfyUI Utility Node for Wildcard Resolution
# Class/Key: DaimalyadNodes
# Category: Text/Wildcards
#
# Copyright © 2025 Daïm Al-Yad (@daimalyad)
# Licensed under the MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# -----------------------------------------------------------------------------

import time
import random
from typing import List, Tuple

def _resolve_wildcards(s: str, rng: random.Random) -> str:
    """
    Resolve {a|b|c} groups with nesting and backslash escapes (\{ \| \}).
    Returns a single fully-resolved string.
    """
    n = len(s)
    i = 0
    out: List[str] = []

    def _read_group(start_idx: int) -> Tuple[List[str], int]:
        """
        Read from s[start_idx:] until the matching '}' at depth 0.
        Split options by '|' only at depth 0. Respect escapes and nested braces.
        Returns (options, close_index_of_right_brace).
        If no matching '}', treat the entire remainder as a literal (unmatched '{').
        """
        opts: List[str] = []
        buf: List[str] = []
        depth = 0
        i2 = start_idx
        while i2 < n:
            c = s[i2]

            # handle escapes
            if c == "\\":
                if i2 + 1 < n:
                    buf.append(s[i2 + 1])
                    i2 += 2
                else:
                    # trailing backslash; keep it literal
                    buf.append("\\")
                    i2 += 1
                continue

            if c == "{":
                depth += 1
                buf.append(c)
                i2 += 1
                continue

            if c == "}":
                if depth == 0:
                    # close of the group
                    opts.append("".join(buf))
                    return opts, i2
                else:
                    depth -= 1
                    buf.append(c)
                    i2 += 1
                    continue

            if c == "|" and depth == 0:
                # split at top-level
                opts.append("".join(buf))
                buf = []
                i2 += 1
                continue

            # normal char
            buf.append(c)
            i2 += 1

        # unmatched '{' -> treat literally
        return ["{" + "".join(buf)], i2

    while i < n:
        c = s[i]
        if c == "\\":
            # escape sequence: keep next char literally if present
            if i + 1 < n:
                out.append(s[i + 1])
                i += 2
            else:
                out.append("\\")
                i += 1
        elif c == "{":
            options, close_idx = _read_group(i + 1)
            # pick one option, then resolve any nested groups within it
            picked = rng.choice(options) if options else ""
            out.append(_resolve_wildcards(picked, rng))
            i = close_idx + 1  # step past the closing '}'
        else:
            out.append(c)
            i += 1

    return "".join(out)


class DaimalyadWildcardProcessor:
    """
    Node: API-Friendly Wildcard Processor
    - text: STRING (multiline) possibly containing wildcards
    Output: STRING (fully-resolved with nanosecond timestamp-based randomization)
    
    This node always produces fresh, non-reproducible wildcard resolution.
    Each execution uses the current nanosecond timestamp for randomization.
    """

    OUTPUT_NODE = True  # Force re-execution
    CATEGORY = "Text/Wildcards"
    FUNCTION = "resolve"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"default": "", "multiline": True}),
            }
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        """
        Force fresh execution every time by returning NaN.
        This prevents any caching and ensures the node always executes.
        """
        return float("NaN")

    def resolve(self, text: str):
        """
        Resolve wildcards using current nanosecond timestamp for randomization.
        Output is never reproducible - always fresh randomization on each execution.
        """
        # Use current nanosecond timestamp for randomization
        timestamp_seed = int(time.time_ns())
        rng = random.Random(timestamp_seed)
        
        # Add debug output to see what's happening
        print(f"[WildcardProcessor] Using seed: {timestamp_seed}")
        print(f"[WildcardProcessor] Input: {text}")
        
        # Resolve wildcards and return
        result = _resolve_wildcards(text, rng)
        print(f"[WildcardProcessor] Output: {result}")
        
        return (result,)
