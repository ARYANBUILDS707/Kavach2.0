# KAVACH MCP Connection Workflow

## Current requirement

No MCP server or capability is required by the source handbook or approved MVP. No MCP connection has been configured or verified by this documentation task. MCP would support the coding environment, not the application's fraud-analysis pipeline.

## Activation inputs

Execute only when the owner names a server and purpose. Record the server's official source/version, tools/resources needed, environment scope, data it can access, credentials and allowed read/write operations. If no capability is specified, retain “Not required for MVP” rather than installing a generic server.

## Procedure

1. Read AGENTS.md and ARCHITECTURE.md; inspect existing agent/server configuration without printing secrets.
2. Consult the selected server's official documentation and inventory its exposed capabilities.
3. Select the minimum required tools and a development-only scope. Prefer read-only credentials for inspection tasks; never grant production database writes by default.
4. Configure secrets through supported secret/environment handling outside committed files. Document variable names only.
5. Validate connection with a harmless read/test resource. If writes are required, use a disposable scoped resource and explicit task authorization.
6. Check logs and responses for accidental credential/data exposure. Document removal/revocation steps and any manual configuration boundary.

## Output

Report server/purpose, enabled tools, credentials/configuration names, exact verification and status, and remaining manual steps. Do not claim a connection from configuration alone, enable unrelated tools, or send raw subscriber communications to an MCP service.
