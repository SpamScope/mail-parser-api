# mail-parser-api

Stateless HTTP service that turns a raw email into the JSON produced by
mail-parser, without storing anything.

## Language

**Raw email**:
The bytes of an email exactly as received, in RFC 822 / RFC 5322 format, sent
as the request body with `Content-Type: message/rfc822`.
_Avoid_: EML, message body, input

**Parsed message**:
The `mail_json` that mail-parser produces for one raw email, returned under
`message` with the `payload` key removed from every attachment.
_Avoid_: Result, report, analysis

**Parse service**:
This API: it receives a raw email, runs the mail-parser CLI on it in a
subprocess, and returns the parsed message. It keeps no state except the rate
limiter's counters.
_Avoid_: Backend, parser server, worker

**Client key**:
The identity the rate limiter counts requests against: the first
`X-Forwarded-For` value or the peer address, an IPv4 address whole or an IPv6
address collapsed to its `/64` network.
_Avoid_: Client IP, user, session

**MIME tree**:
The flat list of the MIME parts of one raw email, returned under `mime_tree`
beside the parsed message; every part names the part that encloses it.
_Avoid_: Structure, MIME structure, part tree

**Part left out**:
A MIME part of the raw email that is not in the returned MIME tree because a
response bound was reached; it is counted, never dropped silently.
_Avoid_: Dropped part, truncated part

**Cut value**:
A text value of a MIME tree entry shortened to the bound, with the name of its
key recorded in that entry's `cut`.
_Avoid_: Truncated value, trimmed value
