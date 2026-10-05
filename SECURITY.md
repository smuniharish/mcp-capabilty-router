# Security policy

## Supported versions

Security fixes are released for the latest minor version.

| Version | Supported |
| --- | --- |
| 0.2.x | Yes |
| 0.1.x | No; upgrade to 0.2 |

## Reporting a vulnerability

Do not report vulnerabilities in public issues. Use
[private vulnerability reporting](https://github.com/smuniharish/mcp-capabilty-router/security/advisories/new)
instead, and include:

- the affected versions;
- the impact, and how an attacker could exploit it;
- steps or code to reproduce it;
- a proposed fix or mitigation, if you have one.

Do not include production secrets or personal data. The maintainer acknowledges
reports as soon as possible, coordinates the fix privately, and publishes an advisory
when a fixed release is available. Please keep the report confidential until then.

## Securing an integration

mcp-capability-router connects models to MCP servers that reach real systems. The
application decides which servers to trust, which credentials they receive, and which
tools models may call. In production:

- register only servers that you trust, and treat tool descriptions, resource
  contents, prompts, and tool results as untrusted input that can carry prompt
  injection;
- pass credentials through targets or adapter factories, with the least privilege each
  server needs, and never through tool arguments or prompts;
- isolate tenants in separate runtimes;
- restrict or require approval for tools that change data, with interceptors or
  LangChain's human-in-the-loop middleware;
- bound every server operation with `operation_timeout`, `max_concurrency`, and rate
  limits;
- scope local servers launched over stdio to the files and systems they need.

The [isolation and security guide](https://mcp-capabilty-router.readthedocs.io/en/latest/guides/security/)
explains each measure.
