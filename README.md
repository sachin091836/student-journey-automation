# Student Journey Automation

An n8n implementation of the full student lifecycle for an online course business: webinar opt-in,
nurture, purchase, course access and session replay. It runs across **WordPress, GoHighLevel, Klaviyo,
Zoom, LearnDash and Riverside**, and includes a dedicated error-handling layer so failures are reported
instead of silently dropping students.

![Architecture overview](docs/architecture.png)

## Contents

- [Features](#features)
- [Repository layout](#repository-layout)
- [Quick start (local sandbox)](#quick-start-local-sandbox)
- [Production deployment](#production-deployment)
- [Design principles](#design-principles)
- [Integration notes](#integration-notes)

## Features

| Journey | Trigger | Outcome |
|---|---|---|
| **Webinar opt-in** | WordPress form or GoHighLevel funnel | GHL contact created and tagged, Zoom webinar registration (invite and reminders sent by Zoom), Klaviyo profile saved with the join link, nurture flow started |
| **Purchase → access** | WooCommerce, GoHighLevel or Stripe order | WordPress account found or created, LearnDash course access granted, GHL tagged `enrolled`, Klaviyo onboarding event |
| **Recording → replay** | Riverside recording ready | Zoom registrants and attendees retrieved, members-only replay post published, Klaviyo event per registrant with attendance status |
| **Error handling** | Any failed execution; daily schedule | Automatic retries, Slack and email alerts with a link to the failed run, daily credential health check |

## Repository layout

```
workflows/
  student-journey.json     Main workflow: three webhook-triggered journeys
  error-alerts.json        Error workflow and daily health check
scripts/
  build_workflows.py       Source of truth for both workflow files
mock/
  mock_apis.py             Local sandbox for GoHighLevel, Klaviyo, Zoom, WordPress/LearnDash and Slack
demo/
  fire.sh                  Sends sample events to the workflow
  payloads/                Sample WordPress, GoHighLevel, WooCommerce and Riverside payloads
  credentials.demo.json    Placeholder credentials for the sandbox
docs/
  architecture.{pdf,png,html}   Architecture overview
```

The workflow JSON is generated. Make changes in `scripts/build_workflows.py`, then run
`python3 scripts/build_workflows.py` to regenerate both files.

## Quick start (local sandbox)

The sandbox exercises every journey end to end without any third-party accounts.

**Requirements:** Python 3.9+, and n8n 1.x or 2.x (Docker, or Node.js 24+).

```bash
python3 mock/mock_apis.py                                   # sandbox APIs on :4010
docker run -it --rm -p 5678:5678 docker.n8n.io/n8nio/n8n    # or: npx n8n
```

1. Import both workflows and the sandbox credentials:
   ```bash
   n8n import:credentials --input=demo/credentials.demo.json
   n8n import:workflow --input=workflows/error-alerts.json
   n8n import:workflow --input=workflows/student-journey.json
   ```
   The CLI keeps the credential and error-workflow references intact. If you import through the
   editor instead, reselect **Settings → Error workflow** on the main workflow.
2. Activate both workflows.
3. Send sample events:
   ```bash
   ./demo/fire.sh optin                                # WordPress opt-in
   ./demo/fire.sh optin-ghl                            # GoHighLevel opt-in (registrant who does not attend)
   ./demo/fire.sh enroll                               # WooCommerce purchase
   ./demo/fire.sh replay                               # Riverside recording ready
   ./demo/fire.sh unmapped                             # purchase of an unmapped product (raises an alert)
   ./demo/fire.sh break zoom && ./demo/fire.sh optin   # simulated Zoom outage (retries, then alert)
   ./demo/fire.sh heal                                 # restore the sandbox
   ```

The sandbox terminal logs every API call as it happens. `GET /__state` returns everything the sandbox has
stored, and `GET /__log` returns the call log as JSON.

When n8n runs in Docker, set `MOCK` to `http://host.docker.internal:4010` in the **Load Config**,
**Alert Config** and **Health Config** nodes.

## Production deployment

1. **Configuration.** In **Load Config**, **Alert Config** and **Health Config**, set `DEMO = false` and
   provide the GoHighLevel location ID, Zoom account and webinar IDs, the tag → Klaviyo list map and the
   product → LearnDash course map.
2. **Credentials.**

   | Credential | Type | Value |
   |---|---|---|
   | GoHighLevel Private Integration | Header auth | `Authorization: Bearer <private integration token>` |
   | Klaviyo Private API Key | Header auth | `Authorization: Klaviyo-API-Key <private key>` |
   | Zoom Server-to-Server App | Basic auth | Client ID and secret. Scopes: `webinar:write:registrant`, `webinar:read:list_registrants`, `report:read:list_webinar_participants` |
   | WordPress Application Password | Basic auth | Service account with permission to manage users, posts and LearnDash enrollments |
   | Journey Webhook Secret | Header auth | `X-Journey-Secret: <long random value>`, sent by every source |
   | Alerts SMTP | SMTP | Outbound mail for alerts (Slack uses the incoming-webhook URL in Alert Config) |

3. **Sources.** Point each source at its production webhook:

   | Endpoint | Source |
   |---|---|
   | `POST /webhook/student-journey/optin` | WordPress form webhook or GoHighLevel workflow webhook action |
   | `POST /webhook/student-journey/enrollment` | WooCommerce order webhook, GoHighLevel order webhook or Stripe `checkout.session.completed` |
   | `POST /webhook/student-journey/replay` | Riverside recording webhook |

4. **Klaviyo flows.** Create an *Added to list* flow for the webinar nurture (the join link is available as
   `{{ person.zoom_join_url }}`), a *Course Enrolled* metric flow for onboarding, and a *Replay Ready*
   metric flow split on `event.attended`.
5. **GoHighLevel.** Create the contact custom field `zoom_join_url`.

## Design principles

- **Single configuration point.** Every ID and mapping lives in one node. No other node needs editing.
- **Source normalization.** Each trigger maps its payload to one internal shape, so adding a new form or
  checkout provider only touches its normalizer.
- **Retries before alerts.** Every API call retries three times, three seconds apart. Failures that persist
  reach Slack and email with the failing node, the API response and a link to the execution.
- **Idempotent writes.** GoHighLevel upserts, WordPress find-or-create, LearnDash enrollment and Klaviyo
  `unique_id` deduplication make every execution safe to retry.
- **Reads before writes.** The replay journey completes all Zoom reads before publishing anything, so a
  failure never leaves partial output.
- **Fail loudly on configuration gaps.** An unmapped product or tag raises an alert rather than skipping
  the student.
- **Proactive monitoring.** A daily health check validates every credential before an expired token
  affects a real signup.

## Integration notes

- **LMS.** Enrollment targets the LearnDash REST API (`/ldlms/v2/sfwd-courses/{id}/users`). Tutor LMS,
  LifterLMS and MemberPress require changes to the *LearnDash · Grant Course Access* node only.
- **Riverside.** Webhooks and API access require a Riverside Business plan, and payload fields vary by
  configuration. *Normalize Replay* accepts the common formats. Without webhook access, the replay journey
  can be triggered from a cloud storage folder watch on Riverside exports.
- **Zoom pagination.** Registrant and attendee lists are fetched with `page_size=300`. Webinars larger
  than that need pagination added.
