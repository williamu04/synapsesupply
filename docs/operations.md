# Operations: run, deploy, configure, troubleshoot

How to run SynapseSupply locally, deploy it to SAP BTP, configure it, and recover when something breaks.
Component docs: `api.md` (HTTP API), `joule.md` (Joule integration), `agentcore.md` (AWS AgentCore),
`agent.md` (agent internals and evals), `demo.md` (Demo Day runbook).

## Local development

```bash
uv sync --extra aicore --extra agentcore       # Python deps (+ LiteLLM for AI Core, + AgentCore SDK)
uv run pytest                                  # unit, HTTP and scenario tests
uv run python -m synapse.agent.cli all         # all scenarios end to end in the terminal
uv run uvicorn synapse.api.main:app --port 8080   # API + console (in-process mock S/4)
(cd ui && npm install && npm run dev)          # console dev server, proxies the API on :8080
uv run python scripts/eval_scenarios.py --runs 3  # regression eval against the real model (costs model calls)
```

Local secrets live in `.env` (git-ignored, mode 600). Every entry point (CLI, API, Joule agent,
AgentCore) loads it via `synapse.env.load_env()`. Variables already set in the environment win.

## Deployed system (SAP BTP, Cloud Foundry)

Org `SEAIO_aws-sap-hackathon-si4ykj9d`, space `hackathon-yang-penting-daftar-dulu`, landscape ap10.

| App | Memory | Serves |
|---|---|---|
| `synapsesupply-api-yang-penting-daftar-dulu` | 1 GB | API, console at `/console/`, agent, in-process mock S/4 |
| `synapsesupply-joule-yang-penting-daftar-dulu` | 512 MB | Joule A2A agent |

Plus, outside Cloud Foundry: the BTP destination `SYNAPSE_AGENT_YPDD` (BasicAuthentication) and the
Joule assistant `synapsesupply_assistant` (deployed with `joule deploy`; see `joule.md`).

### Deploying

```bash
cf login -a https://api.cf.ap10.hana.ondemand.com --sso     # origin key auisywroy-platform
cf target -o SEAIO_aws-sap-hackathon-si4ykj9d -s hackathon-yang-penting-daftar-dulu
./scripts/cf_prepare.sh                                      # requirements.txt + ui/dist

# The space quota is 2 GB: staging a new API (1 GB) beside both running apps fails with
# "space's memory limit exceeded". Push in this order:
cf push synapsesupply-joule-yang-penting-daftar-dulu --var team=yang-penting-daftar-dulu
cf stop synapsesupply-api-yang-penting-daftar-dulu
cf push synapsesupply-api-yang-penting-daftar-dulu --var team=yang-penting-daftar-dulu
```

`cf push` uploads the repo minus `.cfignore` (which keeps out `.env`, `.venv`, tests, docs and UI
sources; the built `ui/dist` and `recordings/` are included).

On every start the API stages SC-01 (`SYNAPSE_DEMO_BOOT_SCENARIO`), so the demo always has a case
waiting for approval within about 20 seconds.

| You changed… | Redeploy |
|---|---|
| agent, SOPs, API, console (`src/`, `ui/`) | `cf_prepare.sh`, then stop + push the API app |
| Joule chat logic (`src/synapse/joule/`) | push the Joule agent app |
| Joule YAML (`joule/`) | `cd joule && joule lint . && joule deploy --compile .` |
| a secret | `cf set-env <app> NAME value`, then `cf restart <app>` |
| AWS resources (`infra/`, `lambdas/`) | `./scripts/aws_deploy.sh` (user; guarded) |
| agent code on AgentCore | build + push the image, then `./scripts/agentcore_update.sh` (user; guarded) |

### Health check

```bash
cf apps                                                   # both started, web:1/1
curl -s https://synapsesupply-api-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com/health
curl -s -o /dev/null -w "%{http_code}\n" https://synapsesupply-joule-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com/
                                                          # 401 expected without the A2A key
cf logs synapsesupply-joule-yang-penting-daftar-dulu --recent | grep "A2A message"   # what Joule sent
```

## Configuration reference

**Secret** = never in git or the manifest: set it in `.env` locally and with `cf set-env` on BTP.

### API app and agent

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_API_KEY` | none (open) | **Secret.** Required as `x-api-key`, `?api_key=`, or the Basic-auth password (browsers) on every route except `/health` |
| `SYNAPSE_PLANNER` | `auto` | `auto` = Claude with autopilot fallback; `autopilot` = no model |
| `SYNAPSE_MODEL_PROVIDERS` | `bedrock,aicore` | Order of model providers (all deployments use the default). A provider that fails is skipped for `SYNAPSE_MODEL_COOLDOWN_S`, so Bedrock without quota or credentials costs about a second per 5 minutes |
| `SYNAPSE_REASONING_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Bedrock planning model |
| `SYNAPSE_TRIAGE_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Bedrock triage model |
| `SYNAPSE_MODEL_COOLDOWN_S` | `300` | How long a failed model provider is skipped before it is tried again |
| `SYNAPSE_AICORE_MODEL_ID` | `sap/anthropic--claude-4.6-sonnet` | Model on SAP AI Core, via LiteLLM |
| `AWS_REGION` | `ap-southeast-2` | The account's region; the organization denies AgentCore, ECR, DynamoDB etc. elsewhere. Don't change it |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | none | **Secret.** Cloud Foundry only: IAM user `synapsesupply-cf-bedrock` (Bedrock invoke only), set by `scripts/cf_bedrock_credentials.sh`. AgentCore uses its IAM role instead |
| `SYNAPSE_CASES_TABLE`, `SYNAPSE_TRACE_TABLE` | none: memory | DynamoDB tables shared by the API and AgentCore (`SynapseSupplyCases`, `SynapseSupplyTrace`); memory fallback |
| `SYNAPSE_AUDIT_BUCKET` | none | S3 bucket for one audit file per final case |
| `SYNAPSE_EXPOSE_S4` | off | `1` = serve the in-process mock S/4 at `/s4` behind the API key (BTP app only) |
| `SYNAPSE_SECRETS_ID` | none | Secrets Manager secret (JSON of variables) loaded at startup; AgentCore uses `synapsesupply/runtime` |
| `AICORE_CLIENT_ID`, `AICORE_CLIENT_SECRET` | none | **Secret.** AI Core service key (keybroker `/ai-core/<team>-key`); enables the AI Core model and live RPT-1 |
| `AICORE_AUTH_URL`, `AICORE_BASE_URL`, `AICORE_RESOURCE_GROUP` | (manifest) | AI Core endpoints, resource group `default` |
| `LITELLM_PROVIDER` | (manifest: `sap`) | LiteLLM provider for AI Core |
| `SYNAPSE_RPT_DEPLOYMENT_ID` | `d76cf689a05d504f` | SAP RPT-1 deployment; without AI Core credentials an empirical estimate is used, labeled as such |
| `SYNAPSE_ERP_URL` | none: in-process mock | S/4 (or external mock) base URL |
| `SYNAPSE_ERP_USER`, `SYNAPSE_ERP_PASSWORD` | none | **Secret.** Basic auth for a real S/4 |
| `SYNAPSE_FALLBACK_MOCK` | off | `1` = fail over to an in-process mock if `SYNAPSE_ERP_URL` is unreachable |
| `SYNAPSE_DEMO` | off | `1` = demo routes against an external mock at `SYNAPSE_ERP_URL` (always on with the in-process mock) |
| `SYNAPSE_DEMO_BOOT_SCENARIO` | none | Stage this scenario at startup (BTP: `SC-01`) |
| `SYNAPSE_UI_DIR` | `ui/dist` | Built console served at `/console/` |
| `SYNAPSE_RECORDINGS_DIR` | `recordings` | Recorded runs for the replay fallback |
| `SYNAPSE_CORS_ORIGINS` | none | Comma-separated origins allowed to call the API |
| `SYNAPSE_PLANT_NAMES` | Riau-1 / Jambi-2 JSON | Plant code → name, for triage and option names |

### Joule agent app

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_API_URL` | `http://localhost:8080` | Where the API is (BTP: set in the manifest) |
| `SYNAPSE_API_KEY` | none | **Secret.** Sent as `x-api-key` to the API |
| `SYNAPSE_A2A_KEY` | none (open) | **Secret.** Joule must present it (the destination's Basic-auth password). Always set it in production: the agent holds the API key |
| `SYNAPSE_CONSOLE_URL` | `<SYNAPSE_API_URL>/console` | Base for the console links in Joule replies |

### Local `.env` keys

`AICORE_*`, `LITELLM_PROVIDER`, `SYNAPSE_CF_API_KEY` and `SYNAPSE_CF_A2A_KEY` (the deployed apps' keys,
kept here only so you can log in and redeploy), `JOULE_CLIENT_ID` and `JOULE_CLIENT_SECRET` (Joule
Studio CLI login).

## Secrets: where each one lives, and rotation

| Secret | Origin | Lives in | Rotate |
|---|---|---|---|
| AI Core client id/secret | hackathon keybroker | `.env`; API app env; Secrets Manager `synapsesupply/runtime` (ap-southeast-2) | ask the organizers for a new key, then `cf set-env` + restart, and `put-secret-value` |
| Joule client id/secret | hackathon keybroker | `.env` | ask the organizers |
| API key | generated by us | `.env` (`SYNAPSE_CF_API_KEY`); API and Joule app env (`SYNAPSE_API_KEY`) | new random value in all three places, restart both apps |
| CF Bedrock access key | IAM user `synapsesupply-cf-bedrock` | API app env only | re-run `scripts/cf_bedrock_credentials.sh` (deletes the old key) |
| A2A key | generated by us | `.env` (`SYNAPSE_CF_A2A_KEY`); Joule app env; BTP destination password | new value in all three, restart the Joule app |

Rotate all of them after Demo Day. Never print `.env`, and never paste it into issues or chats.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Staging fails, buildpack shows "Installing python 3.10" | `runtime.txt` missing (`BP_PYTHON_VERSION` is ignored) | keep `runtime.txt` with `python-3.13.x` |
| `space's memory limit exceeded` on push | 2 GB space quota | the push order above |
| `joule login` fails with `AUTH_LOAD_FAILED` | wrong auth URL (the hackathon guide's `auisywroy…` has no OpenID discovery) | use `https://aws-sap-hackathon-si4ykj9d.authentication.ap10.hana.ondemand.com` |
| Joule commands treated as buyer requests | Joule sends the text as a JSON string with quotes | handled by `synapse.joule.server.unwrap`; check the agent's "A2A message" log |
| Console asks for a password | API key is set | any user name, `SYNAPSE_CF_API_KEY` as the password |
| Console shows no cases after a redeploy | the boot scenario resets the demo (the mock S/4 is in memory) and clears the cases | wait about 20 s for the boot scenario, or click Reset demo → SC-01 |
| Trace says "Model unavailable — deterministic autopilot takes over" | model provider unreachable | the case still completes; check AI Core credentials and `SYNAPSE_MODEL_PROVIDERS` |
| Log: `model provider bedrock failed (ModelThrottledException); skipping it for 300 s` | the hackathon account's Bedrock quota for Claude is zero (for now there is no Bedrock account or quota) | nothing to do: Claude runs on SAP AI Core. ModelRouter still lists Bedrock first; moving to Bedrock is a configuration change on an account with quota |
| Log: `model provider bedrock failed (NoCredentialsError)` on Cloud Foundry | no AWS key on the app | run `scripts/cf_bedrock_credentials.sh` |
| Bedrock `Model use case details have not been submitted` | Anthropic use-case form not done | submit it in the Bedrock console (done 2026-10-22) |
| AWS `AccessDenied` on ECR, S3, Lambda, DynamoDB, AgentCore | organization policy denies `us-west-2` | use `--region ap-southeast-2` |
