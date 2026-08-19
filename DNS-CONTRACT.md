# dns_requirements v1 — the railguey <-> clawdflare contract

Every railguey domain verb (`domains`, `domain-status`) emits a
`dns_requirements` array: the complete set of DNS records the provider must
hold for the domain to go live. **Complete** means it includes the ownership
verification TXT that Railway's API keeps outside `dnsRecords`
(`verificationDnsHost`/`verificationToken`) — missing that record leaves a
cert in VALIDATING_OWNERSHIP forever (prim.eidosagi.com, 2026-08-19).

Record shape (names are FQDNs; producer stays DNS-provider-ignorant):

```json
{
  "type": "CNAME | TXT | ...",
  "name": "prim.eidosagi.com",
  "value": "xyz.up.railway.app",
  "proxied": false,
  "satisfied": false
}
```

`satisfied` is the producer's view (Railway's propagation/verification check),
not the DNS provider's state. Consumers apply idempotently regardless.

The consumer is `clawdflare dns-apply` (zone inferred per record by
longest-suffix match; dry-run by default):

```bash
railguey domain-status . my-service | clawdflare dns-apply -            # preview
railguey domain-status . my-service | clawdflare dns-apply - --apply    # do it
railguey domain-status . my-service --wait 600                          # await cert
```

Any other producer (SES planner, future tools) may emit the same shape.
