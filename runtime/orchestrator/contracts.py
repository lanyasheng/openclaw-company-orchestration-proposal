from __future__ import annotations

from typing import Any, Dict, Optional

from continuation_backends import normalize_dispatch_backend

TASK_TIER_PLAIN = "plain"
TASK_TIER_TRACKED = "tracked"
TASK_TIER_ORCHESTRATED = "orchestrated"

CANONICAL_CALLBACK_ENVELOPE_KEY = "callback_envelope"
CANONICAL_CALLBACK_ENVELOPE_VERSION = "canonical_callback_envelope.v1"
BACKEND_TERMINAL_RECEIPT_KEY = "backend_terminal_receipt"
BUSINESS_CALLBACK_PAYLOAD_KEY = "business_callback_payload"
ADAPTER_SCOPED_PAYLOAD_KEY = "adapter_scoped_payload"

EXPLICIT_CONTRACT_KEYS = ("orchestration", "orchestrator_contract", "orchestration_contract")
SUPPORTED_ADAPTERS = {"trading_roundtable", "channel_roundtable"}


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _copy_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalize_channel_mapping(value: Any) -> Dict[str, Any]:
    mapping = dict(value) if isinstance(value, dict) else {}
    channel_id = _clean_str(mapping.get("id") or mapping.get("channel_id"))
    channel_name = _clean_str(mapping.get("name") or mapping.get("channel_name"))
    topic = _clean_str(mapping.get("topic"))

    normalized = dict(mapping)
    if channel_id:
        normalized["id"] = channel_id
        normalized["channel_id"] = channel_id
    if channel_name:
        normalized["name"] = channel_name
        normalized["channel_name"] = channel_name
    if topic:
        normalized["topic"] = topic
    return normalized


def _merge_missing(target: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(target)
    for key, value in patch.items():
        if key not in result or result[key] in (None, "", [], {}):
            result[key] = value
    return result


def _optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(value)


def extract_callback_envelope(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = payload.get(CANONICAL_CALLBACK_ENVELOPE_KEY)
    if isinstance(raw, dict):
        return dict(raw)
    return None


def extract_adapter_scoped_payload(payload: Dict[str, Any], adapter: Optional[str] = None) -> Dict[str, Any]:
    resolved_adapter = _clean_str(adapter)
    envelope = extract_callback_envelope(payload) or {}
    scoped_info = _copy_mapping(envelope.get(ADAPTER_SCOPED_PAYLOAD_KEY))
    scoped_adapter = _clean_str(scoped_info.get("adapter"))
    scoped_payload = _copy_mapping(scoped_info.get("payload") or scoped_info.get("scoped_payload"))

    if resolved_adapter is None:
        resolved_adapter = scoped_adapter or _clean_str(envelope.get("adapter"))

    if resolved_adapter == "trading_roundtable":
        if isinstance(payload.get("trading_roundtable"), dict):
            return dict(payload["trading_roundtable"])
        if scoped_adapter == "trading_roundtable" and scoped_payload:
            return scoped_payload
        business_payload = _copy_mapping(envelope.get(BUSINESS_CALLBACK_PAYLOAD_KEY))
        if isinstance(business_payload.get("trading_roundtable"), dict):
            return dict(business_payload["trading_roundtable"])
        return {}

    if resolved_adapter == "channel_roundtable":
        if isinstance(payload.get("channel_roundtable"), dict):
            return dict(payload["channel_roundtable"])
        if isinstance(payload.get("generic_roundtable"), dict):
            return dict(payload["generic_roundtable"])
        if scoped_adapter == "channel_roundtable" and scoped_payload:
            return scoped_payload
        business_payload = _copy_mapping(envelope.get(BUSINESS_CALLBACK_PAYLOAD_KEY))
        if isinstance(business_payload.get("channel_roundtable"), dict):
            return dict(business_payload["channel_roundtable"])
        if isinstance(business_payload.get("generic_roundtable"), dict):
            return dict(business_payload["generic_roundtable"])
        return {}

    if resolved_adapter and isinstance(payload.get(resolved_adapter), dict):
        return dict(payload[resolved_adapter])
    if scoped_payload:
        return scoped_payload

    business_payload = _copy_mapping(envelope.get(BUSINESS_CALLBACK_PAYLOAD_KEY))
    if resolved_adapter and isinstance(business_payload.get(resolved_adapter), dict):
        return dict(business_payload[resolved_adapter])
    return {}


def build_canonical_callback_envelope(
    *,
    adapter: Optional[str],
    scenario: Optional[str],
    batch_id: Optional[str],
    backend_terminal_receipt: Optional[Dict[str, Any]],
    business_callback_payload: Optional[Dict[str, Any]],
    orchestration_contract: Optional[Dict[str, Any]],
    business_payload_source: Optional[str] = None,
    callback_payload_schema: Optional[str] = None,
    adapter_scoped_payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    contract = _copy_mapping(orchestration_contract)
    receipt = _copy_mapping(backend_terminal_receipt)
    business_payload = _copy_mapping(business_callback_payload)
    resolved_adapter = _clean_str(adapter) or _clean_str(contract.get("adapter"))
    resolved_schema = _clean_str(callback_payload_schema) or _clean_str(contract.get("callback_payload_schema"))
    scoped_payload = _copy_mapping(adapter_scoped_payload) or extract_adapter_scoped_payload(
        business_payload,
        resolved_adapter,
    )

    return {
        "envelope_version": CANONICAL_CALLBACK_ENVELOPE_VERSION,
        "adapter": resolved_adapter,
        "scenario": _clean_str(scenario) or _clean_str(contract.get("scenario")),
        "batch_id": _clean_str(batch_id) or _clean_str(contract.get("batch_key") or contract.get("batch_id")),
        "backend": _clean_str(receipt.get("backend")),
        BACKEND_TERMINAL_RECEIPT_KEY: receipt,
        BUSINESS_CALLBACK_PAYLOAD_KEY: business_payload,
        ADAPTER_SCOPED_PAYLOAD_KEY: {
            "adapter": resolved_adapter,
            "schema": resolved_schema,
            "payload": scoped_payload,
        },
        "orchestration_contract": contract,
        "source": {
            "business_payload_source": _clean_str(business_payload_source),
            "backend_terminal_receipt_schema": _clean_str(receipt.get("receipt_version")),
            "business_callback_schema": resolved_schema,
            **_copy_mapping(metadata),
        },
    }


def normalize_callback_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    envelope = extract_callback_envelope(payload)
    if not envelope:
        return normalized

    business_payload = _copy_mapping(envelope.get(BUSINESS_CALLBACK_PAYLOAD_KEY))
    if business_payload:
        normalized = _merge_missing(normalized, business_payload)

    contract = _copy_mapping(envelope.get("orchestration_contract"))
    if contract:
        if not isinstance(normalized.get("orchestration"), dict):
            normalized["orchestration"] = contract
        if not isinstance(normalized.get("orchestration_contract"), dict):
            normalized["orchestration_contract"] = contract

    backend_terminal_receipt = _copy_mapping(envelope.get(BACKEND_TERMINAL_RECEIPT_KEY))
    if backend_terminal_receipt:
        normalized[BACKEND_TERMINAL_RECEIPT_KEY] = backend_terminal_receipt
        backend = _clean_str(backend_terminal_receipt.get("backend"))
        if backend == "tmux" and not isinstance(normalized.get("tmux_terminal_receipt"), dict):
            normalized["tmux_terminal_receipt"] = backend_terminal_receipt

    adapter = _clean_str(envelope.get("adapter")) or _clean_str(
        (_copy_mapping(envelope.get(ADAPTER_SCOPED_PAYLOAD_KEY))).get("adapter")
    )
    scoped_payload = extract_adapter_scoped_payload(payload, adapter)
    if adapter and scoped_payload and not isinstance(normalized.get(adapter), dict):
        normalized[adapter] = scoped_payload
    if adapter == "channel_roundtable" and scoped_payload and not isinstance(normalized.get("generic_roundtable"), dict):
        normalized["generic_roundtable"] = scoped_payload

    normalized[CANONICAL_CALLBACK_ENVELOPE_KEY] = envelope
    return normalized


def _envelope_contract(payload: Dict[str, Any]) -> Dict[str, Any]:
    envelope = extract_callback_envelope(payload) or {}
    return _copy_mapping(envelope.get("orchestration_contract"))


def _infer_adapter_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    envelope = extract_callback_envelope(payload) or {}
    envelope_adapter = _clean_str(envelope.get("adapter"))
    if envelope_adapter:
        return envelope_adapter

    scoped_info = _copy_mapping(envelope.get(ADAPTER_SCOPED_PAYLOAD_KEY))
    scoped_adapter = _clean_str(scoped_info.get("adapter"))
    if scoped_adapter:
        return scoped_adapter

    if isinstance(payload.get("trading_roundtable"), dict):
        return "trading_roundtable"
    if isinstance(payload.get("channel_roundtable"), dict) or isinstance(payload.get("generic_roundtable"), dict):
        return "channel_roundtable"

    business_payload = _copy_mapping(envelope.get(BUSINESS_CALLBACK_PAYLOAD_KEY))
    if isinstance(business_payload.get("trading_roundtable"), dict):
        return "trading_roundtable"
    if isinstance(business_payload.get("channel_roundtable"), dict) or isinstance(business_payload.get("generic_roundtable"), dict):
        return "channel_roundtable"
    return None


def _infer_scenario_from_payload(payload: Dict[str, Any], adapter: Optional[str]) -> Optional[str]:
    envelope = extract_callback_envelope(payload) or {}
    if _clean_str(envelope.get("scenario")):
        return _clean_str(envelope.get("scenario"))

    if adapter == "trading_roundtable":
        scoped = extract_adapter_scoped_payload(payload, adapter)
        packet = scoped.get("packet") if isinstance(scoped.get("packet"), dict) else {}
        phase_id = _clean_str(packet.get("phase_id"))
        if phase_id == "trading_phase1":
            return "trading_roundtable_phase1"
        return phase_id

    if adapter == "channel_roundtable":
        scoped = extract_adapter_scoped_payload(payload, adapter)
        packet = scoped.get("packet") if isinstance(scoped.get("packet"), dict) else {}
        return _clean_str(packet.get("scenario"))

    return None


def _infer_owner_from_payload(payload: Dict[str, Any], adapter: Optional[str]) -> Optional[str]:
    envelope_contract = _envelope_contract(payload)
    if _clean_str(envelope_contract.get("owner")):
        return _clean_str(envelope_contract.get("owner"))

    if adapter == "trading_roundtable":
        scoped = extract_adapter_scoped_payload(payload, adapter)
        packet = scoped.get("packet") if isinstance(scoped.get("packet"), dict) else {}
        roundtable = scoped.get("roundtable") if isinstance(scoped.get("roundtable"), dict) else {}
        return _clean_str(roundtable.get("owner")) or _clean_str(packet.get("owner"))

    if adapter == "channel_roundtable":
        scoped = extract_adapter_scoped_payload(payload, adapter)
        packet = scoped.get("packet") if isinstance(scoped.get("packet"), dict) else {}
        roundtable = scoped.get("roundtable") if isinstance(scoped.get("roundtable"), dict) else {}
        return _clean_str(roundtable.get("owner")) or _clean_str(packet.get("owner"))

    return _clean_str(payload.get("owner"))


def _infer_channel_from_payload(payload: Dict[str, Any], adapter: Optional[str]) -> Dict[str, Any]:
    envelope_contract = _envelope_contract(payload)
    normalized_envelope_channel = _normalize_channel_mapping(envelope_contract.get("channel"))
    if normalized_envelope_channel:
        return normalized_envelope_channel

    if adapter == "channel_roundtable":
        scoped = extract_adapter_scoped_payload(payload, adapter)
        packet = scoped.get("packet") if isinstance(scoped.get("packet"), dict) else {}
        return _normalize_channel_mapping(
            {
                "channel_id": packet.get("channel_id"),
                "channel_name": packet.get("channel_name"),
                "topic": packet.get("topic"),
            }
        )

    return {}


def _infer_callback_payload_schema(payload: Dict[str, Any], adapter: Optional[str]) -> Optional[str]:
    envelope = extract_callback_envelope(payload) or {}
    contract = _copy_mapping(envelope.get("orchestration_contract"))
    if _clean_str(contract.get("callback_payload_schema")):
        return _clean_str(contract.get("callback_payload_schema"))

    scoped_info = _copy_mapping(envelope.get(ADAPTER_SCOPED_PAYLOAD_KEY))
    if _clean_str(scoped_info.get("schema")):
        return _clean_str(scoped_info.get("schema"))

    if adapter == "trading_roundtable" or isinstance(payload.get("trading_roundtable"), dict):
        return "trading_roundtable.v1.callback"
    if adapter == "channel_roundtable" or isinstance(payload.get("channel_roundtable"), dict) or isinstance(payload.get("generic_roundtable"), dict):
        return "channel_roundtable.v1.callback"

    business_payload = _copy_mapping(envelope.get(BUSINESS_CALLBACK_PAYLOAD_KEY))
    if isinstance(business_payload.get("trading_roundtable"), dict):
        return "trading_roundtable.v1.callback"
    if isinstance(business_payload.get("channel_roundtable"), dict) or isinstance(business_payload.get("generic_roundtable"), dict):
        return "channel_roundtable.v1.callback"
    return None


def extract_explicit_orchestration_contract(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    envelope_contract = _envelope_contract(payload)
    if envelope_contract:
        enabled_raw = envelope_contract.get("enabled")
        enabled = True if enabled_raw is None else bool(enabled_raw)
        backend_preference = _clean_str(envelope_contract.get("backend_preference"))
        if backend_preference:
            backend_preference = normalize_dispatch_backend(backend_preference)
        return {
            "enabled": enabled,
            "adapter": _clean_str(envelope_contract.get("adapter")),
            "scenario": _clean_str(envelope_contract.get("scenario")),
            "batch_key": _clean_str(envelope_contract.get("batch_key") or envelope_contract.get("batch_id")),
            "flow_id": _clean_str(envelope_contract.get("flow_id")),
            "owner": _clean_str(envelope_contract.get("owner")),
            "backend_preference": backend_preference,
            "callback_payload_schema": _clean_str(envelope_contract.get("callback_payload_schema")),
            "auto_execute": _optional_bool(envelope_contract.get("auto_execute")),
            "entrypoint": _copy_mapping(envelope_contract.get("entrypoint")),
            "gate_policy": _copy_mapping(envelope_contract.get("gate_policy")),
            "channel": _normalize_channel_mapping(envelope_contract.get("channel")),
            "session": _copy_mapping(envelope_contract.get("session")),
            "metadata": _copy_mapping(envelope_contract.get("metadata")),
            "source": f"envelope:{CANONICAL_CALLBACK_ENVELOPE_KEY}",
        }

    for key in EXPLICIT_CONTRACT_KEYS:
        raw = payload.get(key)
        if not isinstance(raw, dict):
            continue

        enabled_raw = raw.get("enabled")
        enabled = True if enabled_raw is None else bool(enabled_raw)
        adapter = _clean_str(raw.get("adapter"))
        backend_preference = _clean_str(raw.get("backend_preference"))

        if backend_preference:
            backend_preference = normalize_dispatch_backend(backend_preference)

        return {
            "enabled": enabled,
            "adapter": adapter,
            "scenario": _clean_str(raw.get("scenario")),
            "batch_key": _clean_str(raw.get("batch_key") or raw.get("batch_id")),
            "flow_id": _clean_str(raw.get("flow_id")),
            "owner": _clean_str(raw.get("owner")),
            "backend_preference": backend_preference,
            "callback_payload_schema": _clean_str(raw.get("callback_payload_schema")),
            "auto_execute": _optional_bool(raw.get("auto_execute")),
            "entrypoint": _copy_mapping(raw.get("entrypoint")),
            "gate_policy": _copy_mapping(raw.get("gate_policy")),
            "channel": _normalize_channel_mapping(raw.get("channel")),
            "session": _copy_mapping(raw.get("session")),
            "metadata": _copy_mapping(raw.get("metadata")),
            "source": f"explicit:{key}",
        }

    return None


def classify_callback_payload(payload: Dict[str, Any]) -> str:
    explicit = extract_explicit_orchestration_contract(payload)
    if explicit and explicit.get("enabled") and explicit.get("adapter") and explicit.get("scenario"):
        return TASK_TIER_ORCHESTRATED

    envelope = extract_callback_envelope(payload)
    if envelope and (_copy_mapping(envelope.get(BUSINESS_CALLBACK_PAYLOAD_KEY)) or _copy_mapping(envelope.get(BACKEND_TERMINAL_RECEIPT_KEY))):
        return TASK_TIER_TRACKED

    if _infer_adapter_from_payload(payload) or any(
        key in payload for key in ("summary", "verdict", "error")
    ):
        return TASK_TIER_TRACKED

    return TASK_TIER_PLAIN


def resolve_orchestration_contract(
    payload: Dict[str, Any],
    *,
    default_adapter: Optional[str] = None,
    default_scenario: Optional[str] = None,
    batch_key: Optional[str] = None,
    default_owner: Optional[str] = None,
    default_backend: Optional[str] = None,
) -> Dict[str, Any]:
    explicit = extract_explicit_orchestration_contract(payload)
    adapter = (explicit or {}).get("adapter") or default_adapter or _infer_adapter_from_payload(payload)
    scenario = (explicit or {}).get("scenario") or default_scenario or _infer_scenario_from_payload(payload, adapter)
    owner = (explicit or {}).get("owner") or default_owner or _infer_owner_from_payload(payload, adapter)

    backend_preference = (explicit or {}).get("backend_preference")
    if not backend_preference:
        backend_preference = normalize_dispatch_backend(default_backend or "subagent")

    callback_payload_schema = (explicit or {}).get("callback_payload_schema") or _infer_callback_payload_schema(payload, adapter)
    task_tier = classify_callback_payload(payload)
    channel = _merge_missing(
        _normalize_channel_mapping((explicit or {}).get("channel")),
        _infer_channel_from_payload(payload, adapter),
    )

    resolved = {
        "enabled": bool((explicit or {}).get("enabled", False)),
        "task_tier": task_tier,
        "adapter": adapter,
        "scenario": scenario,
        "batch_key": (explicit or {}).get("batch_key") or batch_key,
        "flow_id": (explicit or {}).get("flow_id"),
        "owner": owner,
        "backend_preference": backend_preference,
        "callback_payload_schema": callback_payload_schema,
        "auto_execute": (explicit or {}).get("auto_execute"),
        "entrypoint": (explicit or {}).get("entrypoint", {}),
        "gate_policy": (explicit or {}).get("gate_policy", {}),
        "channel": channel,
        "session": (explicit or {}).get("session", {}),
        "metadata": (explicit or {}).get("metadata", {}),
        "source": (explicit or {}).get("source") or "adapter_defaults",
    }

    if resolved["adapter"] not in SUPPORTED_ADAPTERS:
        resolved["adapter"] = None

    return resolved


def is_orchestrated_payload(payload: Dict[str, Any]) -> bool:
    return classify_callback_payload(payload) == TASK_TIER_ORCHESTRATED
