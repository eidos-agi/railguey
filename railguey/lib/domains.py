"""Domain lifecycle verbs: list, status (with wait), delete.

The create/update half lives in tools.domain(). This module closes the rest
of the loop that previously required raw GraphQL: seeing what domains exist,
watching a certificate through its state machine, and deleting a domain.

All queries run on the project token — no Bearer account token needed.
"""

import asyncio
import socket
import ssl
from datetime import datetime, timezone

from .graphql import _gql, _resolve_project, _resolve_service_id
from .token import _load_token

# Full domain state for a service: both kinds, cert status, required DNS.
#
# CRITICAL: ownership verification (verified / verificationDnsHost /
# verificationToken) lives OUTSIDE dnsRecords. Reading dnsRecords alone
# hides the required TXT record and the cert sits in VALIDATING_OWNERSHIP
# forever. Cost us hours on prim.eidosagi.com, 2026-08-19.
_DOMAINS_QUERY = """
query domains($projectId: String!, $environmentId: String!, $serviceId: String!) {
  domains(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) {
    serviceDomains { id domain targetPort }
    customDomains {
      id domain targetPort
      status {
        certificateStatus
        certificateErrorMessage
        cdnProvider
        verified
        verificationDnsHost
        verificationToken
        dnsRecords {
          hostlabel recordType requiredValue currentValue status purpose
        }
      }
    }
  }
}
"""

# Exact enum tokens (post-prefix): substring checks are a trap —
# "VALID" is a substring of "VALIDATING_OWNERSHIP".
_CERT_OK = ("VALID", "ISSUED")
_CERT_FAIL = ("FAIL", "ERROR")


async def _resolve(workspace: str, service: str) -> dict:
    """Shared preamble: workspace token -> project/environment/service ids."""
    token = _load_token(workspace)
    project = await _resolve_project(token)
    if "error" in project:
        return project
    project_id = project.get("projectId")
    environment_id = project.get("environmentId")
    if not project_id or not environment_id:
        return {"error": "Could not resolve projectId/environmentId from token"}
    service_id = await _resolve_service_id(token, project_id, service)
    if not service_id:
        return {"error": f"Service '{service}' not found in project"}
    return {
        "token": token,
        "project_id": project_id,
        "environment_id": environment_id,
        "service_id": service_id,
    }


async def _fetch_domains(ctx: dict) -> dict:
    result = await _gql(
        ctx["token"],
        _DOMAINS_QUERY,
        {
            "projectId": ctx["project_id"],
            "environmentId": ctx["environment_id"],
            "serviceId": ctx["service_id"],
        },
    )
    if "error" in result:
        return result
    return result.get("domains", {}) or {}


def _zone_of(domain: str) -> str:
    """Registrable zone guess: last two labels. Good enough for our zones."""
    return ".".join(domain.split(".")[-2:])


def _dns_requirements(domain: str, status: dict) -> list[dict]:
    """The dns_requirements v1 contract: every record the DNS provider must
    hold for this domain to go live, as flat neutral records with FQDN names.

    This is the railguey<->clawdflare seam: `clawdflare dns-apply` consumes
    exactly this shape. The ownership-verification TXT is synthesized here
    because Railway's API does not include it in dnsRecords.
    """
    zone = _zone_of(domain)
    records = []
    for r in status.get("dnsRecords") or []:
        rtype = (r.get("recordType") or "").replace("DNS_RECORD_TYPE_", "")
        host = r.get("hostlabel") or ""
        name = domain if host in ("", "@") else f"{host}.{zone}"
        records.append(
            {
                "type": rtype or "CNAME",
                "name": name,
                "value": r.get("requiredValue", ""),
                "proxied": False,
                "satisfied": "PROPAGATED" in (r.get("status") or ""),
            }
        )
    if status.get("verificationDnsHost") and status.get("verificationToken"):
        records.append(
            {
                "type": "TXT",
                "name": f"{status['verificationDnsHost']}.{zone}",
                "value": status["verificationToken"],
                "proxied": False,
                "satisfied": bool(status.get("verified")),
            }
        )
    return records


def _summarize_custom(d: dict) -> dict:
    status = d.get("status") or {}
    return {
        "domain": d["domain"],
        "id": d["id"],
        "custom": True,
        "targetPort": d.get("targetPort"),
        "certificateStatus": status.get("certificateStatus", ""),
        "certificateError": status.get("certificateErrorMessage"),
        "verified": status.get("verified"),
        "cdnProvider": status.get("cdnProvider"),
        "dnsRecords": status.get("dnsRecords", []),
        "dns_requirements": _dns_requirements(d["domain"], status),
    }


def _summarize_service(d: dict) -> dict:
    return {
        "domain": d["domain"],
        "id": d["id"],
        "custom": False,
        "targetPort": d.get("targetPort"),
    }


async def domains_list(workspace: str, service: str) -> dict:
    """List every domain on a service with cert + DNS state."""
    ctx = await _resolve(workspace, service)
    if "error" in ctx:
        return ctx
    data = await _fetch_domains(ctx)
    if "error" in data:
        return data
    out = [_summarize_custom(d) for d in data.get("customDomains", [])]
    out += [_summarize_service(d) for d in data.get("serviceDomains", [])]
    return {"service": service, "domains": out, "count": len(out)}


def _name_covered(domain: str, name: str) -> bool:
    """Does a cert subject/SAN entry cover this domain? Handles one-label wildcards."""
    name = name.lower().rstrip(".")
    domain = domain.lower().rstrip(".")
    if name == domain:
        return True
    if name.startswith("*."):
        return domain.split(".", 1)[-1] == name[2:] and "." in domain
    return False


def _edge_cert_sync(domain: str, timeout: float = 6.0) -> dict:
    """What certificate does the edge ACTUALLY serve for this hostname?

    Railway's API can say issued/verified while an edge still hands out the
    *.up.railway.app fallback (seen live on prim.eidosagi.com, 2026-08-19:
    curl got the real cert, a browser got the wildcard). Only a fresh TLS
    handshake with SNI tells the truth.
    """
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False  # we inspect coverage ourselves
        with socket.create_connection((domain, 443), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as tls:
                cert = tls.getpeercert() or {}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    subject_cn = next(
        (
            str(v)
            for rdn in cert.get("subject", ())
            for k, v in rdn
            if k == "commonName"
        ),
        "",
    )
    sans = [str(v) for t, v in cert.get("subjectAltName", ()) if t == "DNS"]
    names = sans or ([subject_cn] if subject_cn else [])
    expires = None
    if cert.get("notAfter"):
        not_after = datetime.strptime(str(cert["notAfter"]), "%b %d %H:%M:%S %Y %Z")
        expires = (not_after.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
    return {
        "servedCN": subject_cn,
        "sans": names,
        "matches": any(_name_covered(domain, n) for n in names),
        "expiresInDays": expires,
    }


async def edge_cert(domain: str) -> dict:
    return await asyncio.to_thread(_edge_cert_sync, domain)


def _cert_state(summary: dict) -> str:
    cert = summary.get("certificateStatus", "") or ""
    token = cert.replace("CERTIFICATE_STATUS_TYPE_", "")
    if token in _CERT_OK:
        return "issued"
    if any(k in token for k in _CERT_FAIL):
        return "failed"
    return "pending"


async def domain_status(
    workspace: str,
    service: str,
    domain_str: str | None = None,
    wait: int = 0,
    interval: int = 15,
) -> dict:
    """Snapshot (or poll, with wait>0 seconds) a domain's cert/DNS state.

    Without --domain, reports the first custom domain (they carry the cert
    state machine; service domains are always ready).
    """
    ctx = await _resolve(workspace, service)
    if "error" in ctx:
        return ctx

    deadline = asyncio.get_event_loop().time() + max(wait, 0)
    polls = 0
    nudged = False
    while True:
        polls += 1
        data = await _fetch_domains(ctx)
        if "error" in data:
            return data
        customs = [_summarize_custom(d) for d in data.get("customDomains", [])]
        if domain_str:
            customs = [c for c in customs if c["domain"] == domain_str]
            if not customs:
                services = [
                    _summarize_service(d)
                    for d in data.get("serviceDomains", [])
                    if d["domain"] == domain_str
                ]
                if services:
                    return {**services[0], "state": "issued", "polls": polls}
                return {"error": f"Domain '{domain_str}' not found on {service}"}
        if not customs:
            return {"error": f"No custom domains on {service}"}

        summary = customs[0]
        state = _cert_state(summary)
        # Not verified => not live, whatever the cert enum says.
        if state == "issued" and summary.get("verified") is False:
            state = "pending"
        # API "issued" is a claim; the edge handshake is the proof. An edge
        # can keep serving the *.up.railway.app fallback after issuance.
        if state == "issued":
            edge = await edge_cert(summary["domain"])
            summary["edge"] = edge
            if edge.get("error") or not edge.get("matches"):
                state = "pending"
                summary["edgeAction"] = (
                    f"edge serving {edge.get('servedCN') or edge.get('error')} "
                    f"instead of a cert covering {summary['domain']} — "
                    "cert issued but not attached at the edge yet"
                )
        unsatisfied = [
            r for r in summary.get("dns_requirements", []) if not r["satisfied"]
        ]
        if unsatisfied:
            summary["dnsAction"] = [
                f"set {r['type']} {r['name']} -> {r['value']}" for r in unsatisfied
            ]
        summary["state"] = state
        summary["polls"] = polls

        # Railway does not reliably re-check verification on its own: once
        # DNS is in place, an explicit customDomainIssueCertificate nudge
        # flips verified within seconds (proven on prim.eidosagi.com after
        # 20+ stuck minutes). Fire it once per wait.
        if (
            wait > 0
            and not nudged
            and state == "pending"
            and summary.get("verified") is False
        ):
            nudged = True
            summary["nudged"] = True
            await _gql(
                ctx["token"],
                "mutation($id: String!) { customDomainIssueCertificate(id: $id) }",
                {"id": summary["id"]},
            )

        if state != "pending" or asyncio.get_event_loop().time() >= deadline:
            if state == "pending" and wait > 0:
                summary["timedOut"] = True
            return summary
        await asyncio.sleep(interval)


async def domain_delete(workspace: str, service: str, domain_str: str) -> dict:
    """Delete a domain (custom or generated) from a service by name."""
    ctx = await _resolve(workspace, service)
    if "error" in ctx:
        return ctx
    data = await _fetch_domains(ctx)
    if "error" in data:
        return data

    for d in data.get("customDomains", []):
        if d["domain"] == domain_str:
            result = await _gql(
                ctx["token"],
                "mutation($id: String!) { customDomainDelete(id: $id) }",
                {"id": d["id"]},
            )
            if "error" in result:
                return result
            return {
                "deleted": True,
                "domain": domain_str,
                "custom": True,
                "note": (
                    "Re-adding this domain mints a NEW CNAME target — after "
                    "recreate, update DNS to the new requiredValue before "
                    "expecting cert issuance."
                ),
            }
    for d in data.get("serviceDomains", []):
        if d["domain"] == domain_str:
            result = await _gql(
                ctx["token"],
                "mutation($id: String!) { serviceDomainDelete(id: $id) }",
                {"id": d["id"]},
            )
            if "error" in result:
                return result
            return {"deleted": True, "domain": domain_str, "custom": False}

    return {"error": f"Domain '{domain_str}' not found on {service}"}
