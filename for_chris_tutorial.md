# For Chris: Tutorial & Code Review Request

Hi Chris,

This branch contains updates to the **node type selection / fallback logic** in EnvAgent-plus (v2.0). Please **review the code for correctness and usability** when you have time.

---

## What changed

1. **Node types are no longer sorted only by name (alphabetically).**
   - They are now ranked by:
     - **Reservable count** (how many hosts of that type are currently reservable) — higher first
     - **Total count** (capacity) — higher first
     - **Requirement fit** (how well the type matches the repo’s needs, e.g. GPU vs compute vs KVM) — better fit first
     - **Name** (alphabetical) — only as tiebreaker

2. **KVM is not forced to the end.**
   - KVM/VM types get a fit score of 0.5 so they sit above “misc” types but below bare-metal compute when the workflow prefers compute. If KVM has more reservable capacity, it can appear earlier in the list.

3. **Files modified**
   - `2.0/src/resource_discovery.py`: added `_is_reservable`, `_fit_score`, `_rank_node_types`; `discover_resources()` now takes optional `requirements` and returns `node_types` in ranked order plus `node_type_stats`.
   - `2.0/src/provision_v2.py`: calls `discover_resources(site, requirements=requirements)` so the ranked list is used for both AI selection and fallback.

---

## What to check (code usability)

Please review with these in mind:

1. **Blazar host fields**  
   Ranking uses `host.get('node_type')` and `host.get('reservable')`. Confirm that your Blazar/Chameleon host list actually returns these fields and in the format the code expects (e.g. `reservable` as boolean or string `"True"`). If your API uses different field names or values, we should align the code.

2. **Fit score rules**  
   In `resource_discovery.py`, `_fit_score()` gives:
   - 2.0: GPU required and name contains `gpu`
   - 1.0: name contains `compute`
   - 0.5: name contains `kvm` or `vm`
   - 0.3: name contains `gpu` (when GPU not required)
   - 0.2: name contains `storage`
   - 0.0: else  

   Check whether these rules match your site’s node type naming and your intended priority (e.g. any other types that should be preferred or deprioritized).

3. **Fallback behavior in provision_v2.py**  
   When AI selection fails, the code picks the first node type in the **already ranked** list that matches:
   - if `gpu_required`: first type whose name contains `gpu`, else first in list
   - else: first type whose name contains `compute`, else first in list  

   Verify that this “first match in ranked list” behavior is what you want and that it doesn’t skip types you care about (e.g. KVM when there’s no compute).

4. **Logging and CLI**  
   After discovery, the script prints each node type with `reservable / total`. Confirm that this is clear and that the printed order matches the order used for selection.

5. **Edge cases**  
   - No hosts or all `node_type` empty  
   - All `reservable` false  
   - Requirements missing or partial (`gpu_required` etc.)  

   Quick sanity checks with your real project and a few repos would help confirm nothing breaks and the chosen node type is sensible.

---

## How to run (quick test)

```bash
cd EnvAgent-plus
source /path/to/your/CHI-XXXX-openrc.sh   # or your OpenRC

# Single repo (will use ranked node types + optional AI)
python 2.0/src/provision_v2.py --repo https://github.com/some/repo --site uc
```

Check the “Discovering Available Resources” section in the output: node types should be listed in ranked order with `reservable / total` counts.

---

## Summary

Please **review the code and logic above for correctness and usability** on your side (Blazar API, node type names, and desired fallback behavior). If anything doesn’t match your environment or expectations, we can adjust the ranking or the fit scores.

Thanks,  
EnvAgent-plus
