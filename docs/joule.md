# SAP Joule integration

The Joule capability lets buyers and planners talk to SynapseSupply in the Joule chat. It is built
the same way as the event's Joule A2A sample (`joule_a2a/project/Python-LangGraph` in the workspace).

```
Joule chat ──► capability (joule/) ──► BTP destination SYNAPSE_AGENT_<team>
           ──► synapsesupply-joule (A2A server, src/synapse/joule)  ──► synapsesupply-api (/requests, /cases…)
```

## What a user can say

| Message | What happens |
|---|---|
| "Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood" | Runs the agent (`USER_REQUEST`, SOP-REQ-01). The reply shows the decision, the reasons, and a compliant alternative |
| "What needs my approval?" | Lists cases awaiting approval, including ones raised by the ERP poller (SC-01) |
| "status of 4500000091-10" | The case's action, cost, confidence, compliance, policy decision and a console link |
| "approve 4500000091-10" | Approves the case. Cedar re-checks the approver (`Policy-HumanApproval`) and the S/4 document is created |
| "reject 4500000091-10 because we slow down line 2" | Rejects the case; a reason is required |

**Demo flow:**
1. Trigger SC-01 in the console.
2. In Joule, ask *"what needs my approval?"*.
3. Approve the case in Joule.
4. Watch the console's trace show APPROVAL → ACTION → DONE live.

## Deployed (team yang-penting-daftar-dulu, 2026-10-21)

| App | URL | Access |
|---|---|---|
| API + console | `https://synapsesupply-api-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com` (console at `/console/`) | `x-api-key`, or browser login with any user name and `SYNAPSE_CF_API_KEY` from `.env` as the password |
| Joule agent (A2A) | `https://synapsesupply-joule-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com` | `x-api-key`, or Basic auth with `SYNAPSE_CF_A2A_KEY` from `.env` as the password |

Both run on Cloud Foundry with Claude 4.6 Sonnet on SAP AI Core (`SYNAPSE_MODEL_PROVIDERS=aicore`
until the AWS account is verified) and live SAP RPT-1. SC-02 took 18 s end to end there.

**Joule assistant:** `synapsesupply_assistant` was deployed on 2026-10-21. Web client:
`https://aws-sap-hackathon-si4ykj9d.ap10.sapdas.cloud.sap/webclient/standalone/synapsesupply_assistant`
(visible to the team's IAS group only; `joule lint` reports no issues).

**The BTP destination for this team** (created on 2026-10-21):

| Field | Value |
|---|---|
| Name | `SYNAPSE_AGENT_YPDD` (already set as the alias in `capability.sapdas.yaml`) |
| Type | HTTP |
| URL | `https://synapsesupply-joule-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com` |
| Proxy Type | Internet |
| Authentication | **BasicAuthentication**: user `joule`, password = `SYNAPSE_CF_A2A_KEY` from `.env` |

The sample uses NoAuthentication. Ours doesn't, because the agent holds the API key: an open endpoint
would let anyone on the internet approve cases. With Basic auth, Joule sends the destination's
credentials instead of the user's token, so approvals are labeled `joule:unknown-user`. Who may
approve is controlled by the scenarios' `visibility_condition` (your team's IAS group).

## Setup (per team)

1. **Deploy both apps.** Run `scripts/cf_prepare.sh`, then `cf push --no-start --var team=<team>`
   (see `manifest.yml`). Set the secrets with `cf set-env` before starting the apps:
   - `SYNAPSE_API_KEY` on both apps.
   - The `AICORE_*` client id and secret from the keybroker on the API app.
   - `SYNAPSE_A2A_KEY` on the Joule app.

   Then run `cf start` for each app. `runtime.txt` pins Python 3.13; without it, the buildpack
   silently uses 3.10 and staging fails.
2. **Create the BTP destination.** In the BTP cockpit, go to Connectivity → Destinations and create
   one named `SYNAPSE_AGENT_<team>`:
   - Type: HTTP. URL: `https://synapsesupply-joule-<team>.cfapps.ap10.hana.ondemand.com`.
   - Use the same proxy and authentication settings as the sample's exercise 03.
3. **Edit the alias.** In `joule/synapse_capability/capability.sapdas.yaml`, change
   `destination: SYNAPSE_AGENT_TEAM` to your destination's name.
4. **Restrict who sees it (recommended).** Add a `visibility_condition` with your team's IAS group
   id (from `/group/<team>` on the keybroker; see `BTP_Instructions/README.md` § Visibility Conditions).
5. **Deploy the capability.** In your own terminal (the CLI asks for your IAS user and password),
   run `joule login --no-app-tid …` (never `--sso`) with the client id and secret from the
   keybroker's `/joule/<team>-key`. Then, from `joule/`, run `joule deploy --compile .` and
   `joule launch synapsesupply_assistant`.

   **Use the auth URL from the Joule key (`uaa.url`):**
   `--authurl https://aws-sap-hackathon-si4ykj9d.authentication.ap10.hana.ondemand.com`.
   The URL in `BTP_Instructions/README.md` (`https://auisywroy.authentication…`) has no OpenID
   discovery document (it returns 404). Joule Studio CLI 2.0.4 then fails with the misleading
   `loading authentication properties failed (AUTH_LOAD_FAILED)` before it even asks for
   credentials.

## Findings from the first live Joule test (2026-10-21)

- **Joule quotes the user's text.** The A2A `message/send` part arrives as a JSON string literal,
  e.g. `"approve 4500000091-10"` with the quotes, plus `metadata.user-language`. The agent unwraps
  it (`server.unwrap`) and matches commands anywhere in the message. Each message's structure is
  logged to `cf logs synapsesupply-joule-<team>`.
- **All five conversations work end to end:** pending approvals, case status, approve (S/4 document
  created), reject, and a blocked buyer request.
- **The demo button resets everything.** "Run SC-01" in the console clears every case. Don't
  click it between steps of a Joule demo.

## Redeploying within the 2 GB space quota

The two apps use 1.5 GB, and staging the API needs another 1 GB, so `cf push` of both at once fails
with `space's memory limit exceeded`. Deploy in this order:

```
cf push synapsesupply-joule-<team> --var team=<team>
cf stop synapsesupply-api-<team>
cf push synapsesupply-api-<team> --var team=<team>
```

Cases live in memory, so every API restart clears them. Re-run the demo scenario afterwards.

## Limits to know before the demo

- **Approver identity is not verified.** The bridge labels the approver `joule:<user>` from the
  forwarded token's `user_name`, `email` or `sub` claim, but doesn't check the token's signature.
  Who may approve is controlled by who can see the capability (step 4) and by the API key between
  the bridge and the API. Verifying the token against XSUAA is future work. Say so if a judge asks.
- **Replies are synchronous, with a 60-second limit.** Joule's `agent-request` waits for the A2A
  reply, and its synchronous timeout is 60 s (per the sample's exercise 03). The fallback planner
  answers in under a second. Real Claude runs took **18 s on Cloud Foundry** (38–47 s from a laptop),
  inside the limit. If they creep toward 60 s, switch to the multi-turn async pattern linked in
  the workspace README; on stage, a recorded run is the fallback.
- **Buttons.** When exactly one case awaits approval, Joule shows **Approve** and **Show status**
  quick replies under the reply. The agent's artifact carries a data part (`case_id`, `status`,
  `awaiting_approval`) after the markdown, and the function's second action group reads it.
  Verified in the web client on 2026-10-22: the button appears, and clicking it sends
  `approve 4500000091-10`, which executed the case (S/4 document 4500000105). Reject stays typed,
  because it needs a reason.
- **Not yet deployed to the BTP tenant.** Verified locally:
  - Unit and A2A tests: the exact `message/send` call, and the `artifacts[0].parts[0].text` path
    the function reads.
  - Both apps booted from a clean Python 3.13 install of the generated `requirements.txt`, as the
    Cloud Foundry buildpack does it.
  - The three conversations above, run over HTTP.
