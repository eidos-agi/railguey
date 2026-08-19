"""Tests for the domain lifecycle verbs (domains / domain-status / domain-delete)."""

from unittest.mock import AsyncMock, patch

import pytest

from railguey.lib.domains import domain_delete, domain_status, domains_list

pytestmark = pytest.mark.asyncio

_CTX = {
    "token": "tok",
    "project_id": "proj-1",
    "environment_id": "env-1",
    "service_id": "svc-1",
}

_CUSTOM_VALIDATING = {
    "id": "cd-1",
    "domain": "prim.example.com",
    "targetPort": 8080,
    "status": {
        "certificateStatus": "CERTIFICATE_STATUS_TYPE_VALIDATING_OWNERSHIP",
        "cdnProvider": None,
        "dnsRecords": [
            {
                "hostlabel": "prim",
                "recordType": "DNS_RECORD_TYPE_CNAME",
                "requiredValue": "abc.up.railway.app",
                "currentValue": "",
                "status": "DNS_RECORD_STATUS_REQUIRES_UPDATE",
                "purpose": "DNS_RECORD_PURPOSE_TRAFFIC_ROUTE",
            }
        ],
    },
}

_CUSTOM_VALID = {
    "id": "cd-1",
    "domain": "prim.example.com",
    "targetPort": 8080,
    "status": {
        "certificateStatus": "CERTIFICATE_STATUS_TYPE_VALID",
        "cdnProvider": None,
        "dnsRecords": [
            {
                "hostlabel": "prim",
                "recordType": "DNS_RECORD_TYPE_CNAME",
                "requiredValue": "abc.up.railway.app",
                "currentValue": "abc.up.railway.app",
                "status": "DNS_RECORD_STATUS_PROPAGATED",
                "purpose": "DNS_RECORD_PURPOSE_TRAFFIC_ROUTE",
            }
        ],
    },
}

_SERVICE_DOMAIN = {"id": "sd-1", "domain": "web-abc.up.railway.app", "targetPort": None}


def _patch_ctx():
    return patch(
        "railguey.lib.domains._resolve", new_callable=AsyncMock, return_value=_CTX
    )


def _patch_gql(*responses):
    if len(responses) == 1:
        return patch(
            "railguey.lib.domains._gql",
            new_callable=AsyncMock,
            return_value=responses[0],
        )
    return patch(
        "railguey.lib.domains._gql",
        new_callable=AsyncMock,
        side_effect=list(responses),
    )


def _domains_resp(customs, services):
    return {"domains": {"customDomains": customs, "serviceDomains": services}}


async def test_domains_list_both_kinds():
    with _patch_ctx(), _patch_gql(_domains_resp([_CUSTOM_VALID], [_SERVICE_DOMAIN])):
        result = await domains_list(".", "web")
    assert result["count"] == 2
    custom = result["domains"][0]
    assert custom["custom"] is True
    assert custom["certificateStatus"] == "CERTIFICATE_STATUS_TYPE_VALID"
    assert result["domains"][1]["custom"] is False


async def test_status_snapshot_pending_reports_dns_action():
    with _patch_ctx(), _patch_gql(_domains_resp([_CUSTOM_VALIDATING], [])):
        result = await domain_status(".", "web")
    assert result["state"] == "pending"
    assert result["polls"] == 1
    assert result["dnsAction"] == ["set CNAME prim.example.com -> abc.up.railway.app"]


async def test_verification_txt_synthesized_into_requirements():
    """The TXT ownership record is NOT in Railway's dnsRecords — the contract
    must synthesize it so no consumer can miss it again (prim.eidosagi.com)."""
    unverified = {
        **_CUSTOM_VALIDATING,
        "status": {
            **_CUSTOM_VALIDATING["status"],
            "verified": False,
            "verificationDnsHost": "_railway-verify.prim",
            "verificationToken": "railway-verify=tok123",
        },
    }
    with _patch_ctx(), _patch_gql(_domains_resp([unverified], [])):
        result = await domain_status(".", "web")
    txt = [r for r in result["dns_requirements"] if r["type"] == "TXT"]
    assert txt == [
        {
            "type": "TXT",
            "name": "_railway-verify.prim.example.com",
            "value": "railway-verify=tok123",
            "proxied": False,
            "satisfied": False,
        }
    ]
    assert "set TXT _railway-verify.prim.example.com -> railway-verify=tok123" in result["dnsAction"]


async def test_issued_cert_but_unverified_stays_pending():
    unverified_valid = {
        **_CUSTOM_VALID,
        "status": {**_CUSTOM_VALID["status"], "verified": False},
    }
    with _patch_ctx(), _patch_gql(_domains_resp([unverified_valid], [])):
        result = await domain_status(".", "web")
    assert result["state"] == "pending"


async def test_status_issued():
    with _patch_ctx(), _patch_gql(_domains_resp([_CUSTOM_VALID], [])):
        result = await domain_status(".", "web", domain_str="prim.example.com")
    assert result["state"] == "issued"
    assert "dnsAction" not in result


async def test_status_wait_polls_until_issued():
    with (
        _patch_ctx(),
        _patch_gql(
            _domains_resp([_CUSTOM_VALIDATING], []),
            _domains_resp([_CUSTOM_VALID], []),
        ),
        patch("railguey.lib.domains.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await domain_status(".", "web", wait=60, interval=1)
    assert result["state"] == "issued"
    assert result["polls"] == 2


async def test_status_unknown_domain_errors():
    with _patch_ctx(), _patch_gql(_domains_resp([_CUSTOM_VALID], [])):
        result = await domain_status(".", "web", domain_str="nope.example.com")
    assert "error" in result


async def test_delete_custom_warns_about_new_cname():
    with (
        _patch_ctx(),
        _patch_gql(
            _domains_resp([_CUSTOM_VALID], []),
            {"customDomainDelete": True},
        ) as mock_gql,
    ):
        result = await domain_delete(".", "web", "prim.example.com")
    assert result["deleted"] is True
    assert result["custom"] is True
    assert "NEW CNAME target" in result["note"]
    assert mock_gql.call_args[0][2] == {"id": "cd-1"}


async def test_delete_service_domain():
    with (
        _patch_ctx(),
        _patch_gql(
            _domains_resp([], [_SERVICE_DOMAIN]),
            {"serviceDomainDelete": True},
        ),
    ):
        result = await domain_delete(".", "web", "web-abc.up.railway.app")
    assert result["deleted"] is True
    assert result["custom"] is False


async def test_delete_missing_domain_errors():
    with _patch_ctx(), _patch_gql(_domains_resp([], [])):
        result = await domain_delete(".", "web", "ghost.example.com")
    assert "error" in result
