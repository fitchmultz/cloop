# Workshop Outline (45–60 minutes)

## Audience
Engineers evaluating local-first AI service architecture and operational readiness.

## Agenda
1. **Architecture walkthrough (10 min)**
   - API/CLI/MCP share service/data layer
   - SQLite-first storage model and implications
2. **Quality gate design (10 min)**
   - `check-fast` vs `ci` vs `test-all`
   - CI workflow separation and resource controls
3. **Hands-on lab (20 min)**
   - Run `make check-fast`
   - Run `make ci`
   - Start service and validate `/health`
4. **Operational safety review (10 min)**
   - Secret scanning and config sync guardrails
   - Safe defaults and failure isolation
5. **Debrief (5–10 min)**
   - Trade-offs, residual risks, and next hardening opportunities

## Success criteria
- Participants can reproduce local CI-equivalent checks.
- Participants can explain why PR CI remains fast while deep checks remain available.
- Participants can locate docs for runbooks and release readiness evidence.

## Failure modes to discuss
- Time-sensitive tests and flake potential
- Misconfigured provider environment variables
- Drift between docs and workflow commands
