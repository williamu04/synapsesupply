# Links used to build and run SynapseSupply

Every link this project depends on or was built from, with what it was used for (as of
2026-10-22). Collected from the repo, the event material in the parent folder, and the build
session's history. No link here carries a credential; where a page hands out secrets (the
keybroker), that is noted.

## 1. Our deployed system

| Link | Use |
|---|---|
| https://synapsesupply-api-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com/console/ | **The console** (live trace, stock chart, options, policy). Login: any user name, `SYNAPSE_CF_API_KEY` as the password |
| https://synapsesupply-api-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com | The API (`/cases`, `/demo/...`, SSE trace; `api.md`). Same key, as `x-api-key` |
| https://synapsesupply-api-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com/health | Health check, no key needed |
| https://synapsesupply-joule-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com | The Joule A2A agent. Called by Joule through the destination `SYNAPSE_AGENT_YPDD`; answers 401 without the A2A key |
| https://aws-sap-hackathon-si4ykj9d.ap10.sapdas.cloud.sap/webclient/standalone/synapsesupply_assistant | **SAP Joule web client** with our assistant (the planner's and buyer's workplace) |
| `arn:aws:bedrock-agentcore:ap-southeast-2:398074591173:runtime/synapsesupply-vFgJ0n85b6` | AgentCore runtime (no public URL; invoked with `aws bedrock-agentcore invoke-agent-runtime`, `agentcore.md`) |
| `398074591173.dkr.ecr.ap-southeast-2.amazonaws.com/synapsesupply-agent` | ECR repository holding the AgentCore image |
| https://claude.ai/artifact/KYimyCiQMeC4VBj9zqqa5f | **Demo Day deck** (12 slides). Private: share it from its Share menu |
| https://claude.ai/artifact/8jTsAFQMFDb2oA8MsPJ2eL | The slide-deck template the deck is built on (fixed; not edited) |

## 2. Hackathon platform (SAP BTP tenant)

| Link | Use |
|---|---|
| https://github.com/SAP-AWS-ID-Hackathon-2026/SAP_AWS_Hackathon_ID_2026 | The event repo (its contents are this project's parent folder): setup guide `README.md`, `BTP_Instructions/`, the Joule A2A starter `joule_a2a/`, slide PDFs in `files/`. Its Issues tab is for help requests |
| https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/group/yang-penting-daftar-dulu | Team page of the keybroker. **Hands out secrets** |
| https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/ai-core/yang-penting-daftar-dulu-key | SAP AI Core service key, copied into `.env` (`AICORE_*`) and Secrets Manager. **Secret** |
| https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/joule/yang-penting-daftar-dulu-key | Joule Studio CLI client id/secret (`JOULE_CLIENT_*` in `.env`). **Secret** |
| https://apac.cockpit.btp.cloud.sap/cockpit/?idp=auisywroy.accounts.ondemand.com/ | BTP cockpit: where the destination `SYNAPSE_AGENT_YPDD` was created |
| https://auisywroy.accounts.ondemand.com | SAP Cloud Identity (IAS) tenant: logins for the cockpit, Cloud Foundry (`cf login --sso`) and Joule; our team's IAS group limits who sees the Joule scenarios |
| https://api.cf.ap10.hana.ondemand.com | Cloud Foundry API (`cf login -a …`); org `SEAIO_aws-sap-hackathon-si4ykj9d`, space `hackathon-yang-penting-daftar-dulu` |
| https://api.ai.prod.ap-southeast-2.aws.ml.hana.ondemand.com | SAP AI Core API (`AICORE_BASE_URL`): Claude 4.6 Sonnet and SAP RPT-1 |
| https://aws-sap-hackathon-si4ykj9d.authentication.ap10.hana.ondemand.com/oauth/token | AI Core token endpoint (`AICORE_AUTH_URL`) |
| https://aws-sap-hackathon-si4ykj9d.authentication.ap10.hana.ondemand.com | Auth URL for `joule login --authurl` (**the one that works**) |
| https://aws-sap-hackathon-si4ykj9d.ap10.sapdas.cloud.sap | Joule tenant API for `joule login --apiurl` / `joule deploy` |
| https://auisywroy.authentication.ap10.hana.ondemand.com | Auth URL given in the setup guide; **don't use** for `joule login`: no OpenID discovery, so it fails with `AUTH_LOAD_FAILED` |
| https://hackathon-manual.cfapps.ap10.hana.ondemand.com | Hackathon manual named in the setup guide (not needed for the build) |

## 3. AWS

| Link | Use |
|---|---|
| https://console.aws.amazon.com | AWS console, region **Asia Pacific (Sydney) `ap-southeast-2`**: Bedrock model access (Anthropic use-case form), Service Quotas (Sonnet 4.6 token quota requests), AgentCore, ECR, IAM, Secrets Manager. Other regions are denied by the organization |

Everything else on AWS was done with the AWS CLI (`aws login`), so no further URLs.

## 4. Documentation and samples consulted while building

| Link | Use |
|---|---|
| https://help.sap.com/docs/joule/joule-development-guide-ba88d1ec6a1b442098863d577c19b0c0/messages | Joule message types: how the capability shows the **Approve / Show status** buttons (`quickReplies`) |
| https://community.sap.com/t5/technology-blog-posts-by-sap/building-custom-joule-capabilities-message-types-in-practice/ba-p/14406014 | Worked examples of the same message types |
| https://github.com/fyx99/joule-pro-code-a2a | Joule pro-code A2A samples (simple, multi-turn, async; read through the GitHub API and raw files): structure of the A2A server, capability, scenario and function YAML |
| `joule_a2a/project/Python-LangGraph/` in the event repo | Python starter: Cloud Foundry `runtime.txt`/`requirements.txt` layout, and exercise `03-integrate-agent-into-joule.md` (destination + capability deployment) |
| https://github.com/cloudfoundry/python-buildpack/releases/download/v1.8.43/python-buildpack-cflinuxfs4-v1.8.43.zip | Cloud Foundry Python buildpack pinned in `manifest.yml` |
| https://open-resource-discovery.github.io/a2a-editor/playground/ | A2A Editor from the starter's exercises, for poking an A2A endpoint by hand (optional) |

## 5. Software sources

| Source | What we take from it |
|---|---|
| https://pypi.org (via `uv`, pinned in `uv.lock`) | `strands-agents` (agent loop, `ModelRouter`, Bedrock), `strands-agents[litellm]` (SAP AI Core via LiteLLM), `bedrock-agentcore` (runtime entry point), `cedarpy` (Cedar policies), `a2a-sdk` 0.3.25 (Joule A2A), `fastapi`, `uvicorn`, `pydantic`, `httpx`, `botocore`, `python-dotenv` |
| https://registry.npmjs.org (via `npm`, pinned in `ui/package-lock.json`) | Console: `react` 18.3.1, `vite` 5.4.11, `typescript` 5.6.3, `vitest` |
| Docker Hub `python:3.12-slim-bookworm` | AgentCore image base (`Dockerfile`) |
| `ghcr.io/astral-sh/uv:0.11.16` | `uv` binary copied into the image |
| https://fonts.googleapis.com (Domine, IBM Plex Sans) | Deck typography |

## 6. In the event material, but not used for the build

Listed for completeness; the session history shows none of these opened while building.

- **SAP docs:** Joule development guide pages on code-based agents, installing the Joule Studio CLI,
  and UI integration cards; BTP *create HTTP destinations* and *deploy application*; SAP AI Core
  help; LiteLLM's SAP provider page; SAP Cloud SDK for AI (`sap.github.io/ai-sdk`); SAP-samples
  *sap-btp-ai-best-practices*; SAP Community *Joule A2A: connect code-based agents*;
  learning.sap.com courses.
- **AWS:** `aws-samples/sample-agentic-ai-process-automation-for-sap`, AWS for SAP blog posts
  (agentic SOPs, agentic ERP), AWS for SAP MCP docs, Builder Center / Skill Builder, Kiro.
- **Protocols and frameworks:** a2a-protocol.org, the `a2a-js` repo, LangGraph docs.
- **Data:** Global Forest Watch data API (`data-api.globalforestwatch.org`), named in the original
  concept for deforestation checks; the EUDR gate uses synthetic compliance profiles instead.
- **Research:** about 400 Scopus references on agentic AI in pulp and paper (`files/13-scopus.txt.md`,
  university-proxy links). The deck uses figures labeled "industry estimates" instead.
