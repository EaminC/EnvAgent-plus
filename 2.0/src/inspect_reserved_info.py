#!/usr/bin/env python3
"""Inspect provision_v2.py output and resolve the actual reserved resources.

This script reads a *_info.json file produced by provision_v2.py, queries
Blazar and OpenStack for the live lease/server state, and writes a normalized
JSON summary that is safe to consume by follow-up automation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from envboot.osutil import blz, conn


UNKNOWN = "unknown"

# Chameleon CHI@TACC node type to hardware specs mapping
# These are approximate specs based on Chameleon documentation
CHAMELEON_HARDWARE_SPECS = {
    # GPU nodes (from highest to lowest tier)
    "gpu_mi100": {"cpus": 24, "memory_mb": 512000, "disk_gb": 6400, "gpus": 4, "gpu_type": "NVIDIA MI100"},
    "gpu_a100_nvlink": {"cpus": 24, "memory_mb": 512000, "disk_gb": 6400, "gpus": 4, "gpu_type": "NVIDIA A100 NVLink"},
    "gpu_a100_pcie": {"cpus": 24, "memory_mb": 512000, "disk_gb": 6400, "gpus": 4, "gpu_type": "NVIDIA A100 PCIe"},
    "gpu_p100": {"cpus": 28, "memory_mb": 256000, "disk_gb": 4000, "gpus": 2, "gpu_type": "NVIDIA P100"},
    "gpu_v100": {"cpus": 16, "memory_mb": 128000, "disk_gb": 2000, "gpus": 1, "gpu_type": "NVIDIA V100"},
    "gpu_m40": {"cpus": 20, "memory_mb": 256000, "disk_gb": 4000, "gpus": 2, "gpu_type": "NVIDIA M40"},
    "gpu_k80": {"cpus": 16, "memory_mb": 192000, "disk_gb": 4000, "gpus": 2, "gpu_type": "NVIDIA K80"},
    "gpu_rtx_6000": {"cpus": 24, "memory_mb": 384000, "disk_gb": 6400, "gpus": 2, "gpu_type": "NVIDIA RTX 6000"},

    # Compute nodes
    "compute_cascadelake_r": {"cpus": 48, "memory_mb": 384000, "disk_gb": 6400, "gpus": 0, "gpu_type": None},
    "compute_cascadelake_r640": {"cpus": 40, "memory_mb": 768000, "disk_gb": 6400, "gpus": 0, "gpu_type": None},
    "compute_cascadelake": {"cpus": 24, "memory_mb": 192000, "disk_gb": 2000, "gpus": 0, "gpu_type": None},
    "compute_gigaio": {"cpus": 24, "memory_mb": 192000, "disk_gb": 2000, "gpus": 0, "gpu_type": None},
    "compute_nvdimm": {"cpus": 24, "memory_mb": 384000, "disk_gb": 2000, "gpus": 0, "gpu_type": None},
    "compute_skylake": {"cpus": 24, "memory_mb": 192000, "disk_gb": 2000, "gpus": 0, "gpu_type": None},

    # Storage nodes
    "storage_nvme": {"cpus": 24, "memory_mb": 192000, "disk_gb": 6400, "gpus": 0, "gpu_type": None},

    # FPGA nodes
    "fpga": {"cpus": 24, "memory_mb": 192000, "disk_gb": 2000, "gpus": 0, "gpu_type": None},
}


def _unknown_if_empty(value: Any) -> Any:
    if value in (None, "", [], {}, ()):  # keep JSON-friendly empties readable
        return UNKNOWN
    return value


def _is_missing(value: Any) -> bool:
    if value in (None, "", UNKNOWN, [], {}, ()):
        return True
    if isinstance(value, dict) and set(value.keys()) == {"error"}:
        return True
    return False


def _choose_value(primary: Any, fallback: Any, prefer_fallback: bool = False) -> Any:
    ordered = (fallback, primary) if prefer_fallback else (primary, fallback)
    for value in ordered:
        if not _is_missing(value):
            return value
    return UNKNOWN


def _safe_str(value: Any) -> str:
    if value in (None, ""):
        return UNKNOWN
    try:
        return str(value)
    except Exception:
        return UNKNOWN


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            pass
    try:
        return _json_safe(dict(value))
    except Exception:
        return _safe_str(value)


def _resource_to_dict(resource: Any) -> Dict[str, Any]:
    if resource is None:
        return {}
    if isinstance(resource, dict):
        return dict(resource)
    if hasattr(resource, "to_dict"):
        try:
            return resource.to_dict()
        except Exception:
            pass
    data: Dict[str, Any] = {}
    for attr in dir(resource):
        if attr.startswith("_"):
            continue
        try:
            value = getattr(resource, attr)
        except Exception:
            continue
        if callable(value):
            continue
        data[attr] = value
    return data


def _read_info_file(info_path: Path) -> Dict[str, Any]:
    with info_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("info file must contain a JSON object")
    return payload


def _load_snapshot(input_info: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = input_info.get("provision_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _snapshot_raw(snapshot: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    for key in keys:
        value = snapshot.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


def _snapshot_field(snapshot: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = snapshot.get(key)
        if not _is_missing(value):
            return value
    summary = snapshot.get("summary")
    if isinstance(summary, dict):
        for key in keys:
            value = summary.get(key)
            if not _is_missing(value):
                return value
    return UNKNOWN


def _first_value(mapping: Dict[str, Any], keys: Iterable[str], default: Any = UNKNOWN) -> Any:
    for key in keys:
        if key in mapping:
            value = mapping.get(key)
            if value not in (None, "", [], {}, ()):
                return value
    return default


def _find_reservation(lease: Dict[str, Any], reservation_id: str) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    reservations = lease.get("reservations") or []
    if not isinstance(reservations, list):
        reservations = [reservations]

    for reservation in reservations:
        reservation_dict = _resource_to_dict(reservation)
        candidate_ids = [
            _safe_str(reservation_dict.get("id")),
            _safe_str(reservation_dict.get("reservation_id")),
            _safe_str(reservation_dict.get("reservation")),
        ]
        if reservation_id in candidate_ids:
            return lease, reservation_dict

    return lease, None


def _parse_time(value: Any) -> Any:
    if value in (None, "", UNKNOWN):
        return UNKNOWN
    if isinstance(value, datetime):
        return value.isoformat()
    return _safe_str(value)


def _find_server_host(server: Dict[str, Any]) -> str:
    host = _first_value(
        server,
        [
            "OS-EXT-SRV-ATTR:host",
            "os-extended-server-attributes:host",
            "host",
            "hypervisor_hostname",
            "OS-EXT-SRV-ATTR:hypervisor_hostname",
            "instance_name",
            "OS-EXT-SRV-ATTR:instance_name",
        ],
    )
    return _safe_str(host)


def _iter_hypervisors(os_conn: Any) -> Iterable[Dict[str, Any]]:
    compute = getattr(os_conn, "compute", None)
    if compute is None:
        return []

    candidates = []
    for method_name in ("hypervisors", "list_hypervisors"):
        method = getattr(compute, method_name, None)
        if not callable(method):
            continue
        try:
            result = method()
        except TypeError:
            try:
                result = method(details=True)
            except Exception:
                continue
        except Exception:
            continue
        if result is None:
            continue
        if isinstance(result, dict):
            candidates.append(result)
        else:
            try:
                candidates.extend(list(result))
            except TypeError:
                candidates.append(result)
    for item in candidates:
        yield _resource_to_dict(item)


def _iter_baremetal_nodes(os_conn: Any) -> Iterable[Dict[str, Any]]:
    baremetal = getattr(os_conn, "baremetal", None)
    if baremetal is None:
        return []

    candidates = []
    for method_name in ("nodes", "list_nodes"):
        method = getattr(baremetal, method_name, None)
        if not callable(method):
            continue
        try:
            result = method(details=True)
        except TypeError:
            try:
                result = method()
            except Exception:
                continue
        except Exception:
            continue
        if result is None:
            continue
        if isinstance(result, dict):
            candidates.append(result)
        else:
            try:
                candidates.extend(list(result))
            except TypeError:
                candidates.append(result)
    for item in candidates:
        yield _resource_to_dict(item)


def _match_hypervisor(os_conn: Any, host_value: str) -> Dict[str, Any]:
    if host_value in (None, UNKNOWN, ""):
        return {}

    compute = getattr(os_conn, "compute", None)
    if compute is not None:
        finder = getattr(compute, "find_hypervisor", None)
        if callable(finder):
            try:
                hypervisor = finder(host_value)
                if hypervisor:
                    return _resource_to_dict(hypervisor)
            except Exception:
                pass

    for hypervisor in _iter_hypervisors(os_conn):
        values = [
            _safe_str(hypervisor.get("hypervisor_hostname")),
            _safe_str(hypervisor.get("name")),
            _safe_str(hypervisor.get("host")),
            _safe_str(hypervisor.get("id")),
        ]
        if host_value in values:
            return hypervisor
    return {}


def _match_baremetal_node(os_conn: Any, server_id: str, host_value: str) -> Dict[str, Any]:
    baremetal = getattr(os_conn, "baremetal", None)
    if baremetal is None:
        return {}

    for node in _iter_baremetal_nodes(os_conn):
        values = [
            _safe_str(node.get("uuid")),
            _safe_str(node.get("id")),
            _safe_str(node.get("name")),
            _safe_str(node.get("instance_uuid")),
            _safe_str(node.get("instance_info", {}).get("image_source") if isinstance(node.get("instance_info"), dict) else None),
        ]
        if server_id in values or host_value in values:
            return node

    return {}


def _extract_server_details(os_conn: Any, server_id: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    try:
        server = os_conn.compute.get_server(server_id)
    except Exception:
        return {}, {}, {}

    server_dict = _resource_to_dict(server)
    host_value = _find_server_host(server_dict)
    hypervisor_dict = _match_hypervisor(os_conn, host_value)
    node_dict = _match_baremetal_node(os_conn, server_id, host_value)
    return server_dict, hypervisor_dict, node_dict


def _extract_image(server: Dict[str, Any], info: Dict[str, Any], os_conn: Any) -> Tuple[str, str]:
    image_id = _safe_str(info.get("image_id") or _first_value(server, ["image_id", "image", "OS-EXT-IMG-SIZE:img_id"]))
    image_name = _safe_str(info.get("image_name"))

    image_field = server.get("image")
    if isinstance(image_field, dict):
        image_id = _safe_str(image_field.get("id") or image_field.get("uuid") or image_id)
        image_name = _safe_str(image_field.get("name") or image_name)
    elif image_field not in (None, ""):
        image_id = _safe_str(image_field)

    if image_name == UNKNOWN and image_id != UNKNOWN:
        try:
            image = os_conn.compute.find_image(image_id)
            if image:
                image_name = _safe_str(_resource_to_dict(image).get("name"))
        except Exception:
            pass

    return image_name, image_id


def _extract_flavor(server: Dict[str, Any], os_conn: Any) -> Tuple[str, str, str, str, str]:
    flavor_field = server.get("flavor")
    flavor_dict: Dict[str, Any] = {}
    if isinstance(flavor_field, dict):
        flavor_dict = flavor_field
    elif flavor_field not in (None, ""):
        try:
            flavor = os_conn.compute.find_flavor(flavor_field)
            if flavor:
                flavor_dict = _resource_to_dict(flavor)
        except Exception:
            flavor_dict = {"id": flavor_field}

    return (
        _safe_str(flavor_dict.get("name")),
        _safe_str(flavor_dict.get("id")),
        _safe_str(flavor_dict.get("vcpus")),
        _safe_str(flavor_dict.get("ram")),
        _safe_str(flavor_dict.get("disk")),
    )


def _extract_addresses(server: Dict[str, Any]) -> Dict[str, Any]:
    addresses = server.get("addresses") or {}
    if not isinstance(addresses, dict):
        return {}
    return _json_safe(addresses)


def _extract_baremetal_hardware(node_raw: Dict[str, Any]) -> Tuple[str, str, str, Optional[str], str]:
    """Extract actual hardware specs from baremetal node raw data.
    
    Returns: (actual_cpus, actual_memory_mb, actual_disk_gb, actual_gpu_type, actual_gpu_count)
    """
    if not isinstance(node_raw, dict) or not node_raw:
        return (UNKNOWN, UNKNOWN, UNKNOWN, None, UNKNOWN)
    
    properties = node_raw.get("properties", {})
    if not isinstance(properties, dict):
        return (UNKNOWN, UNKNOWN, UNKNOWN, None, UNKNOWN)
    
    cpus = _safe_str(properties.get("cpus", UNKNOWN))
    memory_mb = _safe_str(properties.get("memory_mb", UNKNOWN))
    disk_gb = _safe_str(properties.get("local_gb", UNKNOWN))
    
    gpu_type = None
    gpu_count = UNKNOWN
    
    # Try to extract GPU info from capabilities
    capabilities = properties.get("capabilities", {})
    if isinstance(capabilities, dict):
        # Some nodes may have gpu_type and gpu_count in capabilities
        gpu_type = capabilities.get("gpu_type")
        if gpu_type:
            gpu_type = _safe_str(gpu_type)
        gpu_count_val = capabilities.get("gpu_count") or capabilities.get("gpu_num") or properties.get("gpu_count") or properties.get("gpu_num")
        if gpu_count_val:
            gpu_count = _safe_str(gpu_count_val)
    
    return (cpus, memory_mb, disk_gb, gpu_type, gpu_count)


def _lookup_hardware_by_node_type(node_type: str) -> Tuple[str, str, str, Optional[str], str]:
    """Look up hardware specs from node type mapping.
    
    Returns: (cpus, memory_mb, disk_gb, gpu_type, gpu_count)
    """
    if node_type in (None, "", UNKNOWN):
        return (UNKNOWN, UNKNOWN, UNKNOWN, None, UNKNOWN)
    
    specs = CHAMELEON_HARDWARE_SPECS.get(node_type)
    if specs:
        return (
            _safe_str(specs.get("cpus", UNKNOWN)),
            _safe_str(specs.get("memory_mb", UNKNOWN)),
            _safe_str(specs.get("disk_gb", UNKNOWN)),
            specs.get("gpu_type"),
            _safe_str(specs.get("gpus", UNKNOWN)),
        )
    
    return (UNKNOWN, UNKNOWN, UNKNOWN, None, UNKNOWN)


def _snapshot_flavor_details(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    flavor = snapshot.get("flavor_details")
    if isinstance(flavor, dict) and flavor:
        return flavor
    return {}


def _snapshot_server_dict(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    server_raw = _snapshot_raw(snapshot, "server_raw", "server")
    if server_raw:
        return server_raw
    return _snapshot_raw(snapshot, "server_info")


def _snapshot_baremetal_node_dict(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return _snapshot_raw(snapshot, "baremetal_node_raw", "baremetal_node", "node_raw")


def _pick_floating_ip(server: Dict[str, Any], info: Dict[str, Any]) -> str:
    if info.get("floating_ip") not in (None, "", UNKNOWN):
        return _safe_str(info.get("floating_ip"))

    addresses = server.get("addresses") or {}
    if isinstance(addresses, dict):
        for addrs in addresses.values():
            if not isinstance(addrs, list):
                continue
            for addr in addrs:
                if not isinstance(addr, dict):
                    continue
                if addr.get("OS-EXT-IPS:type") == "floating" and addr.get("addr"):
                    return _safe_str(addr.get("addr"))
    return UNKNOWN


def _extract_lease_details(lease: Dict[str, Any], reservation_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    lease_dict = _resource_to_dict(lease)
    _, reservation = _find_reservation(lease_dict, reservation_id)
    return lease_dict, reservation or {}


def _reservation_resource_properties(reservation: Dict[str, Any]) -> Any:
    resource_properties = reservation.get("resource_properties")
    if resource_properties in (None, ""):
        return UNKNOWN
    return _json_safe(resource_properties)


def _reservation_summary(reservation: Dict[str, Any]) -> Dict[str, Any]:
    if not reservation:
        return {}
    return {
        "reservation_id": _safe_str(reservation.get("id")),
        "resource_type": _safe_str(reservation.get("resource_type")),
        "status": _safe_str(reservation.get("status")),
        "min": _unknown_if_empty(reservation.get("min")),
        "max": _unknown_if_empty(reservation.get("max")),
        "resource_properties": _reservation_resource_properties(reservation),
        "hypervisor_properties": _unknown_if_empty(reservation.get("hypervisor_properties")),
    }


def inspect_reserved_info(info_path: Path, prefer_snapshot: bool = False) -> Dict[str, Any]:
    input_info = _read_info_file(info_path)
    snapshot = _load_snapshot(input_info)

    lease_id = _safe_str(input_info.get("lease_id"))
    reservation_id = _safe_str(input_info.get("reservation_id"))
    server_id = _safe_str(input_info.get("server_id"))

    lease_raw: Dict[str, Any] = {}
    reservation_raw: Dict[str, Any] = {}
    server_raw: Dict[str, Any] = {}
    hypervisor_raw: Dict[str, Any] = {}
    node_raw: Dict[str, Any] = {}

    lease_status = UNKNOWN
    lease_start = UNKNOWN
    lease_end = UNKNOWN

    if lease_id != UNKNOWN:
        try:
            lease = blz().lease.get(lease_id)
            lease_raw, reservation_raw = _extract_lease_details(lease, reservation_id)
            lease_status = _safe_str(_first_value(lease_raw, ["status"]))
            lease_start = _parse_time(_first_value(lease_raw, ["start", "start_date", "start_time"]))
            lease_end = _parse_time(_first_value(lease_raw, ["end", "end_date", "end_time"]))
        except Exception as exc:
            lease_raw = {"error": _safe_str(exc)}

    try:
        os_conn = conn()
    except Exception as exc:
        os_conn = None
        server_raw = {"error": _safe_str(exc)}

    if os_conn is not None and server_id != UNKNOWN:
        try:
            server_raw, hypervisor_raw, node_raw = _extract_server_details(os_conn, server_id)
        except Exception as exc:
            server_raw = {"error": _safe_str(exc)}

    selected_node_type = _safe_str(input_info.get("node_type"))
    snapshot_server = _snapshot_server_dict(snapshot)
    snapshot_flavor = _snapshot_flavor_details(snapshot)
    snapshot_node = _snapshot_baremetal_node_dict(snapshot)
    snapshot_lease_raw = _resource_to_dict(snapshot.get("lease_raw", {}))
    snapshot_reservation_raw = _resource_to_dict(snapshot.get("reservation_raw", {}))

    effective_server_raw = _choose_value(server_raw, snapshot_server, prefer_snapshot)
    effective_node_raw = _choose_value(node_raw, snapshot_node, prefer_snapshot)
    effective_lease_raw = _choose_value(lease_raw, snapshot_lease_raw, prefer_snapshot)
    effective_reservation_raw = _choose_value(reservation_raw, snapshot_reservation_raw, prefer_snapshot)

    lease_status = _safe_str(_choose_value(
        _first_value(lease_raw, ["status"]),
        _first_value(snapshot_lease_raw, ["status"]),
        prefer_snapshot,
    ))
    lease_start = _parse_time(_choose_value(
        _first_value(lease_raw, ["start", "start_date", "start_time"]),
        _first_value(snapshot_lease_raw, ["start", "start_date", "start_time"]),
        prefer_snapshot,
    ))
    lease_end = _parse_time(_choose_value(
        _first_value(lease_raw, ["end", "end_date", "end_time"]),
        _first_value(snapshot_lease_raw, ["end", "end_date", "end_time"]),
        prefer_snapshot,
    ))

    server_status = _safe_str(_choose_value(
        _first_value(server_raw, ["status"]),
        _first_value(snapshot_server, ["status"]),
        prefer_snapshot,
    ))
    server_name = _safe_str(_choose_value(
        _first_value(server_raw, ["name"], default=UNKNOWN) if server_raw else UNKNOWN,
        _snapshot_field(snapshot, "server_name"),
        prefer_snapshot,
    ))
    actual_host = _safe_str(_choose_value(
        _find_server_host(server_raw) if server_raw else UNKNOWN,
        _choose_value(
            _first_value(snapshot.get("server_attributes", {}) if isinstance(snapshot.get("server_attributes"), dict) else {}, ["host"]),
            _snapshot_field(snapshot, "actual_host", "host", "hypervisor_hostname", "instance_name"),
            prefer_snapshot,
        ),
        prefer_snapshot,
    ))

    actual_flavor_name, actual_flavor_id, actual_vcpus, actual_ram_mb, actual_disk_gb = (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN)
    if server_raw and os_conn:
        actual_flavor_name, actual_flavor_id, actual_vcpus, actual_ram_mb, actual_disk_gb = _extract_flavor(server_raw, os_conn)

    # Keep OpenStack flavor fields separate
    openstack_flavor = actual_flavor_name
    openstack_flavor_vcpus = actual_vcpus
    openstack_flavor_ram_mb = actual_ram_mb
    openstack_flavor_disk_gb = actual_disk_gb

    actual_flavor_name = _safe_str(_choose_value(actual_flavor_name, _snapshot_field(snapshot, "actual_flavor", "flavor_name", "name"), prefer_snapshot))
    actual_flavor_id = _safe_str(_choose_value(actual_flavor_id, _snapshot_field(snapshot, "actual_flavor_id", "flavor_id", "id"), prefer_snapshot))

    # For bare metal, extract actual hardware from baremetal node or use node_type mapping
    actual_cpus = UNKNOWN
    actual_memory_mb = UNKNOWN
    actual_disk_gb = UNKNOWN
    actual_gpu_type = None
    actual_gpu_count = UNKNOWN
    using_placeholder_baremetal = False

    if actual_flavor_name == "baremetal":
        # Try to extract from baremetal node raw data
        node_cpus, node_memory_mb, node_disk_gb, node_gpu_type, node_gpu_count = _extract_baremetal_hardware(effective_node_raw)
        
        if node_cpus != UNKNOWN and node_memory_mb != UNKNOWN:
            # Successfully extracted from baremetal node
            actual_cpus = node_cpus
            actual_memory_mb = node_memory_mb
            actual_disk_gb = node_disk_gb if node_disk_gb != UNKNOWN else UNKNOWN
            actual_gpu_type = node_gpu_type
            actual_gpu_count = node_gpu_count
        else:
            # Fall back to node_type mapping
            mapped_cpus, mapped_memory_mb, mapped_disk_gb, mapped_gpu_type, mapped_gpu_count = _lookup_hardware_by_node_type(selected_node_type)
            if mapped_cpus != UNKNOWN:
                actual_cpus = mapped_cpus
                actual_memory_mb = mapped_memory_mb
                actual_disk_gb = mapped_disk_gb
                actual_gpu_type = mapped_gpu_type
                actual_gpu_count = mapped_gpu_count
            else:
                # Fall back to OpenStack flavor (if baremetal spec is not placeholder)
                if openstack_flavor_vcpus not in (UNKNOWN, "1", "0"):
                    actual_cpus = openstack_flavor_vcpus
                    actual_memory_mb = openstack_flavor_ram_mb
                    actual_disk_gb = openstack_flavor_disk_gb
                else:
                    # Using placeholder baremetal flavor
                    using_placeholder_baremetal = True
                    actual_cpus = openstack_flavor_vcpus
                    actual_memory_mb = openstack_flavor_ram_mb
                    actual_disk_gb = openstack_flavor_disk_gb
    else:
        # Not bare metal, use flavor values
        actual_cpus = actual_vcpus
        actual_memory_mb = actual_ram_mb
        actual_disk_gb = actual_disk_gb

    if _is_missing(actual_disk_gb) or actual_disk_gb == UNKNOWN:
        for source in (effective_node_raw, hypervisor_raw, snapshot_node):
            if not isinstance(source, dict):
                continue
            for key in ("local_gb", "disk_gb", "disk", "root_gb"):
                value = source.get(key)
                if not _is_missing(value):
                    actual_disk_gb = _safe_str(value)
                    break
            if actual_disk_gb != UNKNOWN:
                break

    image_name, image_id = (_safe_str(input_info.get("image_name")), _safe_str(input_info.get("image_id")))
    if server_raw and os_conn:
        image_name, image_id = _extract_image(server_raw, input_info, os_conn)
    image_name = _safe_str(_choose_value(image_name, _snapshot_field(snapshot, "image_name"), prefer_snapshot))
    image_id = _safe_str(_choose_value(image_id, _snapshot_field(snapshot, "image_id"), prefer_snapshot))

    floating_ip = _safe_str(_choose_value(
        _pick_floating_ip(server_raw, input_info) if server_raw else UNKNOWN,
        _snapshot_field(snapshot, "floating_ip"),
        prefer_snapshot,
    ))

    scheduler_hints = _first_value(server_raw, ["scheduler_hints", "OS-EXT-SRV-ATTR:scheduler_hints", "os-extended-server-attributes:scheduler_hints"]) if server_raw else UNKNOWN
    if scheduler_hints != UNKNOWN:
        scheduler_hints = _json_safe(scheduler_hints)

    if scheduler_hints == UNKNOWN and isinstance(snapshot_server, dict):
        scheduler_hints = _first_value(snapshot_server, ["scheduler_hints", "OS-EXT-SRV-ATTR:scheduler_hints", "os-extended-server-attributes:scheduler_hints"])
        if scheduler_hints != UNKNOWN:
            scheduler_hints = _json_safe(scheduler_hints)

    reservation_summary = _reservation_summary(_resource_to_dict(effective_reservation_raw))

    output = {
        "input_info_file": str(info_path),
        "inspected_at": datetime.utcnow().isoformat() + "Z",
        "provisioning_type": _safe_str(input_info.get("provisioning_type")),
        "lease_id": lease_id,
        "reservation_id": reservation_id,
        "lease_status": lease_status,
        "lease_start": lease_start,
        "lease_end": lease_end,
        "server_id": server_id,
        "server_name": server_name,
        "server_status": server_status,
        "floating_ip": floating_ip,
        "image_name": image_name,
        "image_id": image_id,
        "selected_node_type": selected_node_type,
        "actual_host": actual_host,
        "actual_flavor": actual_flavor_name,
        "actual_flavor_id": actual_flavor_id,
        # OpenStack flavor fields (may be placeholder for baremetal)
        "openstack_flavor": openstack_flavor,
        "openstack_flavor_vcpus": openstack_flavor_vcpus,
        "openstack_flavor_ram_mb": openstack_flavor_ram_mb,
        "openstack_flavor_disk_gb": openstack_flavor_disk_gb,
        # Actual hardware fields (for baremetal, extracted from node or mapping)
        "actual_cpus": actual_cpus,
        "actual_memory_mb": actual_memory_mb,
        "actual_disk_gb": actual_disk_gb,
        "actual_gpu_type": actual_gpu_type,
        "actual_gpu_count": actual_gpu_count,
        "using_placeholder_baremetal": using_placeholder_baremetal,
        # Legacy fields (deprecated, kept for compatibility)
        "actual_vcpus": actual_vcpus,
        "actual_ram_mb": actual_ram_mb,
        "resource_properties": reservation_summary.get("resource_properties", UNKNOWN),
        "hypervisor_properties": reservation_summary.get("hypervisor_properties", UNKNOWN),
        "reservation_status": reservation_summary.get("status", UNKNOWN),
        "reservation_min": reservation_summary.get("min", UNKNOWN),
        "reservation_max": reservation_summary.get("max", UNKNOWN),
        "reservation_resource_type": reservation_summary.get("resource_type", UNKNOWN),
        "scheduler_hints": scheduler_hints,
        "reservation_raw": _json_safe(effective_reservation_raw),
        "full_lease_raw": _json_safe(effective_lease_raw),
        "full_server_raw": _json_safe(effective_server_raw),
        "full_hypervisor_raw": _json_safe(hypervisor_raw),
        "full_baremetal_node_raw": _json_safe(effective_node_raw),
        "provision_snapshot": _json_safe(snapshot),
    }

    return output


def _print_summary(data: Dict[str, Any]) -> None:
    print("\nReserved Resource Summary")
    print("=" * 60)
    print(f"Lease: {data.get('lease_id', UNKNOWN)} [{data.get('lease_status', UNKNOWN)}]")
    print(f"Reservation: {data.get('reservation_id', UNKNOWN)} [{data.get('reservation_status', UNKNOWN)}]")
    print(f"Server: {data.get('server_name', UNKNOWN)} ({data.get('server_id', UNKNOWN)}) [{data.get('server_status', UNKNOWN)}]")
    print(f"Image: {data.get('image_name', UNKNOWN)} ({data.get('image_id', UNKNOWN)})")
    print(f"Flavor: {data.get('actual_flavor', UNKNOWN)}")
    print(f"Host: {data.get('actual_host', UNKNOWN)}")
    print(f"Floating IP: {data.get('floating_ip', UNKNOWN)}")
    print(f"Node Type: {data.get('selected_node_type', UNKNOWN)}")
    print(f"Lease Window: {data.get('lease_start', UNKNOWN)} -> {data.get('lease_end', UNKNOWN)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect a provision_v2.py *_info.json file and resolve live reservation details.",
    )
    parser.add_argument("--info", required=True, help="Path to the *_info.json file")
    parser.add_argument(
        "--out",
        default="actual_reserved_info.json",
        help="Output path for the normalized JSON summary",
    )
    parser.add_argument(
        "--prefer-snapshot",
        action="store_true",
        help="Prefer the provision_snapshot block when live fields are missing or stale",
    )
    args = parser.parse_args()

    info_path = Path(args.info).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = inspect_reserved_info(info_path, prefer_snapshot=args.prefer_snapshot)
    except Exception as exc:
        print(f"ERROR: failed to inspect {info_path}: {exc}", file=sys.stderr)
        return 1

    _print_summary(data)

    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(_json_safe(data), handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"\nWrote normalized JSON to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())