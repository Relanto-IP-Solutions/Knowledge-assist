"""Agent constants: batch_id → agent_id mapping for traceability.

Maps 1:1 with batch_registry batches (batch_order 1–6).
"""

from __future__ import annotations


# Batch ID (sase_batches.batch_id) → agent_id for traceability
BATCH_ID_TO_AGENT_ID: dict[str, str] = {
    "sase_use_case_details": "agent_use_case",
    "sase_customer_tenant": "agent_customer_tenant",
    "sase_infrastructure_details": "agent_infrastructure",
    "sase_mobile_user_details": "agent_mobile_users",
    "sase_ztna_details": "agent_ztna",
    "sase_remote_network_svc_conn": "agent_remote_network",
}
