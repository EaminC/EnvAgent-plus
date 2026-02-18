# Robustness & Safety Fixes (Feb 18, 2026)

## Overview

This document outlines defensive robustness improvements made to the resource discovery and provisioning pipeline. All changes maintain backward compatibility and do not alter public function signatures or behavior—only add null-safety and edge-case handling.

---

## Files Modified

- `2.0/src/resource_discovery.py`
- `2.0/src/provision_v2.py`

---

## Changes by Module

### 1. resource_discovery.py

#### `_is_reservable(host: Dict[str, Any]) -> bool` (Lines 118–150)

**Purpose**: Safely check if a host is marked as reservable in Blazar.

**What was improved**:
- **Defensive type checking**: Host input is validated as a dict before accessing fields
- **Multiple input formats**: Handles `reservable` field as:
  - `bool`: `True` / `False`
  - `int`: `0` / `1` or any non-zero
  - `str`: `"True"` / `"true"` / `"1"` / `"yes"` (case-insensitive)
  - `None`: Defaults to `False`
  - Missing: Uses `.get()` with default `False`
  
**Risk mitigated**: 
- Prevents `TypeError` from type mismatches
- Never raises `KeyError` on missing `'reservable'` field
- Handles inconsistent API responses gracefully

---

#### `_fit_score(node_type: str, requirements: Dict[str, Any]) -> float` (Lines 152–181)

**Purpose**: Score how well a node type matches workload requirements.

**What was improved**:
- **Null-safety for node_type**: Validates it's a string before calling `.strip()` or `.lower()`
- **Safe requirements handling**: Treats `None` or non-dict requirements as empty dict
- **Explicit scoring rules**:
  - `2.0`: GPU required AND "gpu" in node_type name
  - `1.0`: "compute" in node_type name
  - `0.5`: "kvm" or "vm" in node_type name (fallback tier)
  - `0.3`: "gpu" in node_type name (GPU available but not required)
  - `0.2`: "storage" in node_type name
  - `0.0`: Everything else

**Risk mitigated**:
- Prevents `AttributeError` if node_type is `None`
- Handles missing `gpu_required` field (defaults to `False`)
- Never crashes on edge cases like empty strings

---

#### `_rank_node_types(...) -> List[str]` (Lines 183–225)

**Purpose**: Rank node types by availability and suitability.

**What was improved**:
- **Explicit filtering loop**: Iterates through node_types set line-by-line:
  - Skips `None` entries
  - Skips non-string entries
  - Skips empty/whitespace-only strings
  - Appends only valid, stripped node_type strings
- **Explicit tuple sorting**: Clear priority order:
  ```python
  return (-reservable, -total, -fit, nt.lower())
  ```
  - **Position 1**: `-reservable_count` (descending by count)
  - **Position 2**: `-total_count` (descending by count)
  - **Position 3**: `-fit_score` (descending by score)
  - **Position 4**: `name_lowercase` (ascending alphabetically)
- **Clarity**: `reverse=False` is explicit (not implicit)

**Sorting behavior**:
- Types with more available capacity tried first
- Within same availability, better requirement fit wins
- KVM not forced to end (scores 0.5, above storage types)
- Deterministic ordering by name when all else equal

**Risk mitigated**:
- Prevents crashes from None entries in node_types set
- No accidental alphabetical dominance
- Sorting is predictable and documented

---

#### `discover_resources(site, requirements) -> Dict[str, Any]` (Lines 227–284)

**Purpose**: Discover and rank available resources based on requirements.

**What was improved**:
- **Defensive logging**: After ranking, prints each node_type with:
  - `reservable / total` counts
  - `fit_score` value
  - Helps ops teams debug ranking decisions
- **Guaranteed return type**: Always returns a dict with:
  - `'node_types'`: List of ranked node type names
  - `'node_type_stats'`: Per-type statistics
  - `'site'`: Site name
  - `'total_hosts'`: Total host count
  - `'hosts'`: Raw host list
- **Never returns `None`**: Even with empty host list, returns valid dict with empty `'node_types'` list

**Risk mitigated**:
- Calling code can safely check `available_resources.get('node_types')`
- No NoneType errors downstream
- Rankings are visible for troubleshooting

---

### 2. provision_v2.py

#### Fallback Logic in `main()` (Lines 560–588)

**Context**: When AI resource selection fails, code falls back to picking first suitable node type from ranked discovery results.

**What was improved**:
- **Empty list guard**: Checks `if not ranked_types` and raises clear error:
  ```python
  if not ranked_types:
      raise Exception("No ranked node types available after discovery")
  ```
  Prevents `IndexError` on `ranked_types[0]`

- **Type-safe loops**: GPU and compute search loops validate each entry:
  ```python
  if nt and isinstance(nt, str) and 'gpu' in nt.lower():
  ```
  - Checks `nt` is truthy (not None)
  - Checks `isinstance(nt, str)` before calling `.lower()`
  - Only then checks substring

- **Smart fallback order**:
  - **If GPU required**: Loop through ranked types seeking "gpu" in name
  - **Else**: Loop through ranked types seeking "compute" in name
  - **If no match**: Use first ranked type (could be KVM, storage, etc.)

- **KVM not skipped**: If first ranked type is KVM (e.g., when GPU unavailable), it will be selected

**Risk mitigated**:
- Prevents `IndexError` crashes
- No substring search crashes from type mismatches
- Preserves fallback chain intention
- Doesn't accidentally skip valid types like KVM

---

## Edge Cases Now Handled

| Scenario | Before | After |
|----------|--------|-------|
| Empty host list | Potential crash | Returns valid dict with empty node_types list |
| All hosts unreservable | Sorting assumes counts exist | Works correctly with 0 counts |
| Missing node_type field | KeyError possible | Skipped by filter |
| requirements=None | Crash on `.get()` | Treated as empty dict |
| GPU required but missing | May crash | Falls back to first ranked type |
| ranked_types[0] access | IndexError if empty | Protected by is-empty check |
| Non-string in node_types | Might cause crash | Skipped by type check |
| Host not a dict | Potential TypeError | Checked in _is_reservable() |
| reservable field various types | Type assumption fails | Handles bool/int/str/None |

---

## Testing Recommendations

```bash
# Test basic discovery
python 2.0/src/provision_v2.py --repo <url> --site tacc

# Expected output:
# - ResourceDiscovery logs showing ranked node types
# - Each type shows: name | reservable/total | fit_score

# Verify fallback logic when AI fails
# - Check that GPU repos fall back to GPU types when available
# - Check that compute repos fall back to compute types when available
# - Check that final fallback uses first ranked type
```

---

## Deployment Notes

- **Backward compatible**: No public API changes
- **No new dependencies**: Uses only Python standard library
- **No performance regression**: Sorting is `O(n log n)` as before
- **Improved debuggability**: Defensive logging helps troubleshoot failures

---

## Questions?

See `for_chris_tutorial.md` for code review notes and expected Blazar API field formats.
