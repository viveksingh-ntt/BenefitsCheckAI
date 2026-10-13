# `docs/deployment-runbook.md`

Source: [`docs/deployment-runbook.md`](../../../deployment-runbook.md)

> **Summary:** A step-by-step Azure CLI deployment of the pilot, used instead of Terraform.

Steps:

1. Foundations
2. Identities and Entra apps
3. HSM signing key
4. Images
5. Container Apps
6. AI Search
7. Foundry, connections, agents, A2A and roles
8. Azure Bot and Direct Line with enhanced authentication
9. APIM APIs and policies
10. Final wiring
11. n8n
12. Portal integration
13. Smoke tests and troubleshooting

Steps that were not verified against a subscription are marked ⚠️. Follow it in order: several steps reuse shell variables set in earlier steps.
