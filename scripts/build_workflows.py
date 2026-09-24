#!/usr/bin/env python3
"""Generates the two importable n8n workflows in ../workflows/.

    python3 scripts/build_workflows.py

Edit the node definitions here (not the JSON) so node names, connections and
positions stay consistent. The JSON files are what you import into n8n.
"""
import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "workflows"

MAIN_ID = "sjStudentJourney"
ERR_ID = "sjErrHandler0001"

# Credential references. Create credentials with these names in n8n (or import
# demo/credentials.demo.json for the local mock run).
CRED = {
    "webhook": {"httpHeaderAuth": {"id": "sjCredWebhook001", "name": "Journey Webhook Secret"}},
    "ghl": {"httpHeaderAuth": {"id": "sjCredGhl0000001", "name": "GoHighLevel Private Integration"}},
    "klaviyo": {"httpHeaderAuth": {"id": "sjCredKlaviyo001", "name": "Klaviyo Private API Key"}},
    "zoom": {"httpBasicAuth": {"id": "sjCredZoom000001", "name": "Zoom Server-to-Server App"}},
    "wp": {"httpBasicAuth": {"id": "sjCredWordpress1", "name": "WordPress Application Password"}},
    "smtp": {"smtp": {"id": "sjCredSmtp000001", "name": "Alerts SMTP"}},
}

RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 3000}

# Every node in a webhook run reads lead data + config from here.
CTX = "$('Load Config').first().json"


def _id(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "student-journey/" + name))


class Flow:
    def __init__(self):
        self.nodes, self.conns = [], {}

    def add(self, name, type_, version, params, pos, **extra):
        node = {"parameters": params, "id": _id(name), "name": name, "type": type_,
                "typeVersion": version, "position": list(pos)}
        node.update(extra)
        self.nodes.append(node)
        return name

    def link(self, src, dst, out=0):
        outs = self.conns.setdefault(src, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": dst, "type": "main", "index": 0})

    def chain(self, *names):
        for a, b in zip(names, names[1:]):
            self.link(a, b)

    def sticky(self, key, content, pos, w, h, color):
        self.nodes.append({"parameters": {"content": content, "width": w, "height": h, "color": color},
                           "id": _id("sticky-" + key), "name": "Note: " + key,
                           "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": list(pos)})


def webhook(f, name, path, pos):
    return f.add(name, "n8n-nodes-base.webhook", 2,
                 {"httpMethod": "POST", "path": path, "authentication": "headerAuth",
                  "responseMode": "onReceived", "options": {}},
                 pos, webhookId=_id("hook-" + path), credentials=CRED["webhook"])


def code(f, name, js, pos, **extra):
    return f.add(name, "n8n-nodes-base.code", 2, {"jsCode": js.strip() + "\n"}, pos, **extra)


def http(f, name, method, url, pos, cred=None, headers=None, query=None, body=None, **extra):
    p = {"method": method, "url": url}
    creds = None
    if cred:
        (ctype, ref), = CRED[cred].items()
        p["authentication"] = "genericCredentialType"
        p["genericAuthType"] = ctype
        creds = CRED[cred]
    if query:
        p["sendQuery"] = True
        p["queryParameters"] = {"parameters": [{"name": k, "value": v} for k, v in query]}
    if headers:
        p["sendHeaders"] = True
        p["headerParameters"] = {"parameters": [{"name": k, "value": v} for k, v in headers]}
    if body is not None:
        p["sendBody"] = True
        p["specifyBody"] = "json"
        p["jsonBody"] = body
    p["options"] = {}
    kw = dict(RETRY)
    kw.update(extra)
    if creds:
        kw["credentials"] = creds
    return f.add(name, "n8n-nodes-base.httpRequest", 4.2, p, pos, **kw)


def if_exists(f, name, left, pos):
    return f.add(name, "n8n-nodes-base.if", 2.2, {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{"id": _id(name + "-c"), "leftValue": left, "rightValue": "",
                            "operator": {"type": "number", "operation": "exists", "singleValue": True}}],
            "combinator": "and"},
        "looseTypeValidation": True, "options": {}}, pos)


GHL_HEADERS = [("Version", "2021-07-28"), ("Accept", "application/json")]
KLAVIYO_HEADERS = [("revision", f"={{{{ {CTX}.cfg.klaviyoRevision }}}}"),
                   ("accept", "application/vnd.api+json"),
                   ("content-type", "application/vnd.api+json")]


def zoom_bearer():
    return [("Authorization", "=Bearer {{ $('Zoom · Get Token').first().json.access_token }}")]


# ---------------------------------------------------------------------------
# Shared config (Code node) — the only place a client edits IDs / mappings.
# ---------------------------------------------------------------------------
CONFIG_JS = r"""
// ────────────────────────────────────────────────────────────────
//  CONFIG: the only node you edit when IDs change.
//  DEMO = true routes every API call to the local mock server
//  (mock/mock_apis.py) so the whole journey can be fired with test data.
// ────────────────────────────────────────────────────────────────
const DEMO = true;
const MOCK = 'http://127.0.0.1:4010';   // host.docker.internal:4010 if n8n runs in Docker

const cfg = {
  ghlBase:         DEMO ? `${MOCK}/ghl`     : 'https://services.leadconnectorhq.com',
  ghlLocationId:   'YOUR_GHL_LOCATION_ID',
  klaviyoBase:     DEMO ? `${MOCK}/klaviyo` : 'https://a.klaviyo.com',
  klaviyoRevision: '2024-10-15',
  zoomBase:        DEMO ? `${MOCK}/zoom/v2` : 'https://api.zoom.us/v2',
  zoomTokenUrl:    DEMO ? `${MOCK}/zoom/oauth/token` : 'https://zoom.us/oauth/token',
  zoomAccountId:   'YOUR_ZOOM_ACCOUNT_ID',
  zoomWebinarId:   '81234567890',            // default webinar for opt-ins
  wpBase:          DEMO ? `${MOCK}/wp`      : 'https://your-academy.com',
  wpLoginUrl:      'https://your-academy.com/login',
  wpReplayCategoryId: 12,                     // members-only "Replays" category

  // GHL tag  →  Klaviyo list whose "added to list" trigger starts the nurture flow
  klaviyoLists: {
    'webinar-registered': 'WEBINAR_NURTURE_LIST_ID',
    'enrolled':           'STUDENT_ONBOARDING_LIST_ID',
  },
  // Checkout product ID (WooCommerce / GHL / Stripe)  →  LearnDash course ID
  courseMap: {
    '501': { courseId: 3101, name: 'Foundations Course' },
    '502': { courseId: 3102, name: 'Advanced Masterclass' },
  },
};

// Fail loudly on unmapped tags/products instead of silently dropping a student.
return $input.all().map(({ json }) => {
  if (json.event === 'optin' && !cfg.klaviyoLists[json.tag]) {
    throw new Error(`No Klaviyo list mapped for GHL tag "${json.tag}" — add it to cfg.klaviyoLists`);
  }
  if (json.event === 'enrollment') {
    const missing = json.productIds.filter((id) => !cfg.courseMap[id]);
    if (missing.length) {
      throw new Error(`Order ${json.orderId}: no LearnDash course mapped for product(s) ${missing.join(', ')} — add to cfg.courseMap`);
    }
    json.courses = json.productIds.map((id) => cfg.courseMap[id]);
  }
  if (json.event === 'replay') json.webinarId = json.webinarId || cfg.zoomWebinarId;
  return { json: { ...json, cfg } };
});
"""

NORMALIZE_OPTIN_JS = r"""
// Accepts WordPress form plugins (WPForms, Gravity, Elementor, CF7) or a
// GoHighLevel funnel/workflow webhook and emits one clean lead.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
return $input.all().map(({ json }) => {
  const b = json.body || {};
  const pick = (...keys) => keys.map((k) => b[k]).find((v) => v !== undefined && v !== null && v !== '');

  const email = String(pick('email', 'Email', 'your-email', 'contact_email') || '').trim().toLowerCase();
  if (!EMAIL_RE.test(email)) throw new Error(`Opt-in rejected: invalid email "${email}" from ${pick('source') || 'unknown form'}`);

  let firstName = pick('first_name', 'firstName', 'fname');
  let lastName = pick('last_name', 'lastName', 'lname');
  if (!firstName && pick('name', 'full_name')) [firstName, ...lastName] = String(pick('name', 'full_name')).trim().split(/\s+/);
  if (Array.isArray(lastName)) lastName = lastName.join(' ');

  const digits = String(pick('phone', 'Phone') || '').replace(/[^\d+]/g, '');
  const phone = digits.startsWith('+') ? digits : digits.length === 10 ? `+1${digits}` : null;

  return {
    json: {
      event: 'optin',
      email,
      firstName: firstName || '',
      lastName: lastName || '',
      phone,
      tag: pick('tag') || 'webinar-registered',
      webinarId: pick('webinar_id', 'webinarId') || null,
      source: pick('source') || (b.contact_id ? 'GoHighLevel funnel' : 'WordPress landing page'),
      utm: { source: pick('utm_source') || null, campaign: pick('utm_campaign') || null },
      receivedAt: $now.toISO(),
    },
  };
});
"""

NORMALIZE_ENROLL_JS = r"""
// Accepts a WooCommerce order webhook, a GoHighLevel order/payment webhook,
// or a Stripe checkout.session.completed event. Unpaid orders are ignored.
return $input.all().flatMap(({ json }) => {
  const b = json.body || {};
  let order;
  if (b.billing && b.line_items) {                                   // WooCommerce
    if (!['processing', 'completed'].includes(b.status)) return [];
    order = { orderId: `woo-${b.id}`, email: b.billing.email, firstName: b.billing.first_name,
              lastName: b.billing.last_name, productIds: b.line_items.map((l) => String(l.product_id)) };
  } else if (b.type === 'checkout.session.completed') {             // Stripe
    const s = b.data.object;
    order = { orderId: `stripe-${s.id}`, email: s.customer_details.email,
              firstName: (s.customer_details.name || '').split(' ')[0], lastName: (s.customer_details.name || '').split(' ').slice(1).join(' '),
              productIds: String(s.metadata.product_ids || s.metadata.product_id).split(',') };
  } else {                                                          // GoHighLevel order
    const c = b.contact || b;
    order = { orderId: `ghl-${b.order_id || b.id}`, email: c.email, firstName: c.first_name, lastName: c.last_name,
              productIds: [].concat(b.product_ids || b.product_id || []).map(String) };
  }
  if (!order.email || !order.productIds.length) throw new Error(`Enrollment payload missing email or products: ${JSON.stringify(b).slice(0, 300)}`);
  return [{ json: { event: 'enrollment', tag: 'enrolled', ...order, email: order.email.trim().toLowerCase(), receivedAt: $now.toISO() } }];
});
"""

NORMALIZE_REPLAY_JS = r"""
// Riverside "recording ready" payload (Riverside Business API webhook, or a
// forwarded export notification). Field names vary, so accept the common ones.
return $input.all().map(({ json }) => {
  const b = json.body || {};
  const r = b.recording || b.data || b;
  const replayUrl = r.share_link || r.shareUrl || r.video_url || r.download_url || r.url;
  if (!replayUrl) throw new Error(`Riverside payload has no replay link: ${JSON.stringify(b).slice(0, 300)}`);
  return {
    json: {
      event: 'replay',
      sessionId: String(r.id || r.recording_id || r.session_id || $execution.id),
      title: r.title || r.recording_title || r.studio_name || 'Session replay',
      replayUrl,
      recordedAt: r.recorded_at || r.created_at || $now.toISO(),
      webinarId: b.zoom_webinar_id || r.zoom_webinar_id || null,
    },
  };
});
"""

MATCH_WP_USER_JS = r"""
// WP user search is fuzzy; pick the exact email match (or none).
const email = $('Load Config').first().json.email;
const match = $input.all().map((i) => i.json).find((u) => (u.email || '').toLowerCase() === email);
return [{ json: { wpUserId: match ? match.id : null } }];
"""

RESOLVE_COURSES_JS = r"""
// One item per course so each LearnDash grant is its own (retryable) call.
const ctx = $('Load Config').first().json;
const wpUserId = $json.wpUserId ?? $json.id;
return ctx.courses.map((c) => ({ json: { wpUserId, courseId: c.courseId, courseName: c.name } }));
"""

REPLAY_AUDIENCE_JS = r"""
// Everyone who registered gets the replay; the event says whether they attended
// so Klaviyo can send "thanks for coming" vs "you missed it" copy.
const ctx = $('Load Config').first().json;
const regs = $('Zoom · List Registrants').first().json.registrants || [];
const attended = new Set(($('Zoom · List Attendees').first().json.participants || [])
  .map((p) => (p.user_email || '').toLowerCase()));
const post = $('WordPress · Publish Replay').first().json;
return regs.map((r) => {
  const email = r.email.toLowerCase();
  return { json: { email, firstName: r.first_name, attended: attended.has(email),
                   replayUrl: ctx.replayUrl, pageUrl: post.link, title: ctx.title, sessionId: ctx.sessionId } };
});
"""


def build_main():
    f = Flow()
    X = lambda i: 980 + 240 * i  # lane columns

    # Triggers + normalizers
    t1 = webhook(f, "Opt-in · WordPress / GHL Form", "student-journey/optin", (0, 0))
    n1 = code(f, "Normalize Opt-in", NORMALIZE_OPTIN_JS, (240, 0))
    t2 = webhook(f, "Purchase · Woo / GHL / Stripe", "student-journey/enrollment", (0, 460))
    n2 = code(f, "Normalize Enrollment", NORMALIZE_ENROLL_JS, (240, 460))
    t3 = webhook(f, "Recording Ready · Riverside", "student-journey/replay", (0, 1000))
    n3 = code(f, "Normalize Replay", NORMALIZE_REPLAY_JS, (240, 1000))
    cfg = code(f, "Load Config", CONFIG_JS, (480, 460))
    route = f.add("Route by Event", "n8n-nodes-base.switch", 3.2, {
        "rules": {"values": [
            {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                            "conditions": [{"id": _id("route-" + ev), "leftValue": "={{ $json.event }}", "rightValue": ev,
                                            "operator": {"type": "string", "operation": "equals"}}],
                            "combinator": "and"},
             "renameOutput": True, "outputKey": label}
            for ev, label in [("optin", "Opt-in"), ("enrollment", "Enrollment"), ("replay", "Replay")]]},
        "options": {}}, (720, 460))
    f.chain(t1, n1, cfg)
    f.chain(t2, n2, cfg)
    f.chain(t3, n3, cfg)
    f.link(cfg, route)

    # ── Lane 1: opt-in ────────────────────────────────────────────────
    ghl_up = http(f, "GHL · Upsert Contact", "POST", f"={{{{ {CTX}.cfg.ghlBase }}}}/contacts/upsert", (X(0), 0),
                  cred="ghl", headers=GHL_HEADERS, body=(
                      "={{ JSON.stringify({ locationId: " + CTX + ".cfg.ghlLocationId, email: " + CTX + ".email, "
                      "firstName: " + CTX + ".firstName, lastName: " + CTX + ".lastName, phone: " + CTX + ".phone || undefined, "
                      "source: " + CTX + ".source }) }}"))
    ghl_tag = http(f, "GHL · Tag 'webinar-registered'", "POST",
                   f"={{{{ {CTX}.cfg.ghlBase }}}}/contacts/{{{{ $('GHL · Upsert Contact').first().json.contact.id }}}}/tags",
                   (X(1), 0), cred="ghl", headers=GHL_HEADERS, body="={{ JSON.stringify({ tags: [" + CTX + ".tag] }) }}")
    ztok1 = http(f, "Zoom · Get Token", "POST",
                 f"={{{{ {CTX}.cfg.zoomTokenUrl }}}}", (X(2), 0), cred="zoom",
                 query=[("grant_type", "account_credentials"), ("account_id", f"={{{{ {CTX}.cfg.zoomAccountId }}}}")])
    zreg = http(f, "Zoom · Register for Webinar", "POST",
                f"={{{{ {CTX}.cfg.zoomBase }}}}/webinars/{{{{ {CTX}.webinarId || {CTX}.cfg.zoomWebinarId }}}}/registrants",
                (X(3), 0), headers=zoom_bearer(), body=(
                    "={{ JSON.stringify({ email: " + CTX + ".email, first_name: " + CTX + ".firstName || 'Friend', "
                    "last_name: " + CTX + ".lastName, source_name: " + CTX + ".source }) }}"))
    kprof = http(f, "Klaviyo · Upsert Profile", "POST", f"={{{{ {CTX}.cfg.klaviyoBase }}}}/api/profile-import",
                 (X(4), 0), cred="klaviyo", headers=KLAVIYO_HEADERS, body=(
                     "={{ JSON.stringify({ data: { type: 'profile', attributes: { email: " + CTX + ".email, "
                     "first_name: " + CTX + ".firstName, last_name: " + CTX + ".lastName, properties: { "
                     "ghl_contact_id: $('GHL · Upsert Contact').first().json.contact.id, "
                     "zoom_join_url: $('Zoom · Register for Webinar').first().json.join_url, "
                     "journey_stage: " + CTX + ".tag, lead_source: " + CTX + ".source, "
                     "utm_campaign: " + CTX + ".utm.campaign } } } }) }}"))
    ksub = http(f, "Klaviyo · Add to Nurture List", "POST",
                f"={{{{ {CTX}.cfg.klaviyoBase }}}}/api/profile-subscription-bulk-create-jobs",
                (X(5), 0), cred="klaviyo", headers=KLAVIYO_HEADERS, body=(
                    "={{ JSON.stringify({ data: { type: 'profile-subscription-bulk-create-job', attributes: { "
                    "custom_source: 'Webinar opt-in (n8n)', profiles: { data: [ { type: 'profile', attributes: { "
                    "email: " + CTX + ".email, subscriptions: { email: { marketing: { consent: 'SUBSCRIBED' } } } } } ] } }, "
                    "relationships: { list: { data: { type: 'list', id: " + CTX + ".cfg.klaviyoLists[" + CTX + ".tag] } } } } }) }}"))
    ghl_save = http(f, "GHL · Save Zoom Join Link", "PUT",
                    f"={{{{ {CTX}.cfg.ghlBase }}}}/contacts/{{{{ $('GHL · Upsert Contact').first().json.contact.id }}}}",
                    (X(6), 0), cred="ghl", headers=GHL_HEADERS, body=(
                        "={{ JSON.stringify({ customFields: [ { key: 'zoom_join_url', field_value: "
                        "$('Zoom · Register for Webinar').first().json.join_url } ] }) }}"))
    f.link(route, ghl_up, 0)
    f.chain(ghl_up, ghl_tag, ztok1, zreg, kprof, ksub, ghl_save)

    # ── Lane 2: enrollment ────────────────────────────────────────────
    wfind = http(f, "WordPress · Find User", "GET", f"={{{{ {CTX}.cfg.wpBase }}}}/wp-json/wp/v2/users",
                 (X(0), 460), cred="wp", query=[("search", f"={{{{ {CTX}.email }}}}"), ("context", "edit")],
                 alwaysOutputData=True)
    wmatch = code(f, "Match Exact Email", MATCH_WP_USER_JS, (X(1), 460))
    wif = if_exists(f, "Has WP Account?", "={{ $json.wpUserId }}", (X(2), 460))
    wcreate = http(f, "WordPress · Create Student", "POST", f"={{{{ {CTX}.cfg.wpBase }}}}/wp-json/wp/v2/users",
                   (X(3), 600), cred="wp", body=(
                       "={{ JSON.stringify({ username: " + CTX + ".email, email: " + CTX + ".email, "
                       "first_name: " + CTX + ".firstName, last_name: " + CTX + ".lastName, roles: ['subscriber'], "
                       "password: $execution.id + '-' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2) }) }}"))
    wres = code(f, "Resolve Courses", RESOLVE_COURSES_JS, (X(4), 460))
    ld = http(f, "LearnDash · Grant Course Access", "POST",
              f"={{{{ {CTX}.cfg.wpBase }}}}/wp-json/ldlms/v2/sfwd-courses/{{{{ $json.courseId }}}}/users",
              (X(5), 460), cred="wp", body="={{ JSON.stringify({ user_ids: [$json.wpUserId] }) }}")
    ghl_up2 = http(f, "GHL · Upsert Student", "POST", f"={{{{ {CTX}.cfg.ghlBase }}}}/contacts/upsert", (X(6), 460),
                   cred="ghl", headers=GHL_HEADERS, executeOnce=True, body=(
                       "={{ JSON.stringify({ locationId: " + CTX + ".cfg.ghlLocationId, email: " + CTX + ".email, "
                       "firstName: " + CTX + ".firstName, lastName: " + CTX + ".lastName }) }}"))
    ghl_tag2 = http(f, "GHL · Tag 'enrolled'", "POST",
                    f"={{{{ {CTX}.cfg.ghlBase }}}}/contacts/{{{{ $json.contact.id }}}}/tags",
                    (X(7), 460), cred="ghl", headers=GHL_HEADERS, body="={{ JSON.stringify({ tags: ['enrolled'] }) }}")
    kev = http(f, "Klaviyo · 'Course Enrolled' Event", "POST", f"={{{{ {CTX}.cfg.klaviyoBase }}}}/api/events",
               (X(8), 460), cred="klaviyo", headers=KLAVIYO_HEADERS, body=(
                   "={{ JSON.stringify({ data: { type: 'event', attributes: { unique_id: " + CTX + ".orderId, "
                   "properties: { order_id: " + CTX + ".orderId, courses: " + CTX + ".courses.map(c => c.name), "
                   "login_url: " + CTX + ".cfg.wpLoginUrl }, "
                   "metric: { data: { type: 'metric', attributes: { name: 'Course Enrolled' } } }, "
                   "profile: { data: { type: 'profile', attributes: { email: " + CTX + ".email, "
                   "first_name: " + CTX + ".firstName, properties: { journey_stage: 'enrolled' } } } } } } }) }}"))
    f.link(route, wfind, 1)
    f.chain(wfind, wmatch, wif)
    f.link(wif, wres, 0)
    f.link(wif, wcreate, 1)
    f.link(wcreate, wres)
    f.chain(wres, ld, ghl_up2, ghl_tag2, kev)

    # ── Lane 3: replay ────────────────────────────────────────────────
    ztok3 = http(f, "Zoom · Get Token (Replay)", "POST", f"={{{{ {CTX}.cfg.zoomTokenUrl }}}}", (X(0), 1000), cred="zoom",
                 query=[("grant_type", "account_credentials"), ("account_id", f"={{{{ {CTX}.cfg.zoomAccountId }}}}")])
    bearer3 = [("Authorization", "=Bearer {{ $('Zoom · Get Token (Replay)').first().json.access_token }}")]
    zregs = http(f, "Zoom · List Registrants", "GET", f"={{{{ {CTX}.cfg.zoomBase }}}}/webinars/{{{{ {CTX}.webinarId }}}}/registrants",
                 (X(1), 1000), headers=bearer3, query=[("page_size", "300")])
    zatt = http(f, "Zoom · List Attendees", "GET", f"={{{{ {CTX}.cfg.zoomBase }}}}/past_webinars/{{{{ {CTX}.webinarId }}}}/participants",
                (X(2), 1000), headers=bearer3, query=[("page_size", "300")])
    wpost = http(f, "WordPress · Publish Replay", "POST", f"={{{{ {CTX}.cfg.wpBase }}}}/wp-json/wp/v2/posts",
                 (X(3), 1000), cred="wp", body=(
                     "={{ JSON.stringify({ title: 'Replay: ' + " + CTX + ".title, status: 'publish', "
                     "slug: 'replay-' + " + CTX + ".sessionId, categories: [" + CTX + ".cfg.wpReplayCategoryId], "
                     "content: '<p>Recorded ' + DateTime.fromISO(" + CTX + ".recordedAt).toFormat('LLLL d, yyyy') + '.</p>"
                     "<p><a href=\"' + " + CTX + ".replayUrl + '\">Watch the replay</a></p>' }) }}"))
    aud = code(f, "Build Replay Audience", REPLAY_AUDIENCE_JS, (X(4), 1000))
    kev3 = http(f, "Klaviyo · 'Replay Ready' Event", "POST", f"={{{{ {CTX}.cfg.klaviyoBase }}}}/api/events",
                (X(5), 1000), cred="klaviyo", headers=KLAVIYO_HEADERS, body=(
                    "={{ JSON.stringify({ data: { type: 'event', attributes: { unique_id: $json.sessionId + ':' + $json.email, "
                    "properties: { title: $json.title, replay_url: $json.replayUrl, page_url: $json.pageUrl, attended: $json.attended }, "
                    "metric: { data: { type: 'metric', attributes: { name: 'Replay Ready' } } }, "
                    "profile: { data: { type: 'profile', attributes: { email: $json.email } } } } } }) }}"))
    f.link(route, ztok3, 2)
    f.chain(ztok3, zregs, zatt, wpost, aud, kev3)

    # Sticky notes (these read well on screen during the walkthrough)
    f.sticky("Entry", "## ① Entry points\nThree webhooks (shared-secret header auth). Each normalizer turns whatever the "
             "source sends — WP form plugins, GHL, WooCommerce, Stripe, Riverside — into one clean shape.\n\n"
             "**Load Config** is the only node a human edits: IDs, tag→list and product→course maps. "
             "Unmapped tags/products fail loudly.", (-40, -300), 700, 240, 7)
    f.sticky("Optin", "## ② Webinar opt-in\nGHL contact + tag → Zoom registrant (Zoom emails the calendar invite & reminders) "
             "→ Klaviyo profile **with the join link already on it** → added to the nurture list that triggers the flow.",
             (X(0) - 40, -300), 1680, 240, 4)
    f.sticky("Enroll", "## ③ Purchase → course access\nFind-or-create the WordPress student, grant each LearnDash course, "
             "tag 'enrolled' in GHL, fire Klaviyo 'Course Enrolled' (onboarding flow; exits the webinar nurture).",
             (X(0) - 40, 200), 2160, 170, 6)
    f.sticky("Replay", "## ④ Recording → replay\nRiverside recording ready → attendance from Zoom → members-only replay post "
             "in WordPress → one Klaviyo 'Replay Ready' event per registrant with `attended` true/false.",
             (X(0) - 40, 780), 1440, 170, 5)
    f.sticky("Errors", "## ⑤ Nothing fails silently\nEvery API step retries 3× (3 s apart). If it still fails, the "
             "**Student Journey · Error Alerts** workflow posts to Slack + email with the failing node and a one-click "
             "link to the execution. All writes are upserts / idempotent (Klaviyo `unique_id`, WP slug), so "
             "“Retry” is always safe.", (-40, 1260), 700, 200, 3)

    return {
        "id": MAIN_ID,
        "name": "Student Journey · Opt-in → Nurture → Enroll → Replay",
        "nodes": f.nodes,
        "connections": f.conns,
        "active": False,
        "settings": {"executionOrder": "v1", "errorWorkflow": ERR_ID, "saveDataErrorExecution": "all",
                     "saveDataSuccessExecution": "all", "saveManualExecutions": True, "timezone": "America/New_York"},
        "pinData": {},
        "tags": [],
    }


# ---------------------------------------------------------------------------
# Error workflow + daily credential health check
# ---------------------------------------------------------------------------
ALERT_CFG_JS = r"""
const DEMO = true;
const MOCK = 'http://127.0.0.1:4010';   // host.docker.internal:4010 if n8n runs in Docker
const cfg = {
  slackWebhookUrl: DEMO ? `${MOCK}/slack/webhook` : 'https://hooks.slack.com/services/XXX/YYY/ZZZ',
  alertEmail:      'ops@your-academy.com',
  ghlBase:         DEMO ? `${MOCK}/ghl`     : 'https://services.leadconnectorhq.com',
  ghlLocationId:   'YOUR_GHL_LOCATION_ID',
  klaviyoBase:     DEMO ? `${MOCK}/klaviyo` : 'https://a.klaviyo.com',
  zoomTokenUrl:    DEMO ? `${MOCK}/zoom/oauth/token` : 'https://zoom.us/oauth/token',
  zoomAccountId:   'YOUR_ZOOM_ACCOUNT_ID',
  wpBase:          DEMO ? `${MOCK}/wp`      : 'https://your-academy.com',
};
return $input.all().map(({ json }) => ({ json: { ...json, cfg } }));
"""

FORMAT_ALERT_JS = r"""
// Error Trigger payload → one human-readable alert.
const e = $('Alert Config').first().json;
const exec = e.execution || {};
const failed = exec.error || e.trigger?.error || {};
const node = exec.lastNodeExecuted || failed.node?.name || 'trigger';
const status = failed.httpCode || failed.context?.httpCode || '';
const msg = String(failed.description || failed.message || 'Unknown error').slice(0, 500);
const wf = e.workflow?.name || 'Student Journey';
const url = exec.url || '';
const text = `:rotating_light: *${wf}* failed at *${node}*${status ? ` (HTTP ${status})` : ''}\n>${msg}\n` +
             (url ? `<${url}|Open execution> → fix → click *Retry* (all steps are safe to re-run).` : '');
return [{ json: { cfg: e.cfg, text, subject: `[n8n] ${wf} failed at ${node}`, node, msg, url } }];
"""

HEALTH_JS = r"""
// Each ping ran with "continue on error"; collect the ones that failed.
const checks = ['Ping GoHighLevel', 'Ping Klaviyo', 'Ping Zoom', 'Ping WordPress'];
const failures = checks
  .map((n) => ({ n, j: $(n).first().json }))
  .filter(({ j }) => j.error)
  .map(({ n, j }) => `• ${n.replace('Ping ', '')}: ${String(j.error.message || j.error).slice(0, 200)}`);
return [{ json: {
  cfg: $('Health Config').first().json.cfg,
  failed: failures.length,
  text: `:warning: *Student Journey health check*: ${failures.length} integration(s) failing auth/API check — ` +
        `new students would break here. Fix before the next opt-in:\n${failures.join('\n')}`,
} }];
"""


def build_errors():
    f = Flow()
    et = f.add("On Journey Failure", "n8n-nodes-base.errorTrigger", 1, {}, (0, 0))
    ac = code(f, "Alert Config", ALERT_CFG_JS, (240, 0))
    fm = code(f, "Format Alert", FORMAT_ALERT_JS, (480, 0))
    slack = http(f, "Slack · #automation-alerts", "POST", "={{ $json.cfg.slackWebhookUrl }}", (740, -100),
                 body="={{ JSON.stringify({ text: $json.text }) }}", onError="continueRegularOutput")
    mail = f.add("Email · Ops Inbox", "n8n-nodes-base.emailSend", 2.1, {
        "fromEmail": "automations@your-academy.com", "toEmail": "={{ $json.cfg.alertEmail }}",
        "subject": "={{ $json.subject }}", "emailFormat": "text",
        "text": "={{ $json.text.replace(/[*>]|:rotating_light:/g, '') }}", "options": {}},
        (740, 100), credentials=CRED["smtp"], onError="continueRegularOutput", **RETRY)
    f.chain(et, ac, fm)
    f.link(fm, slack)
    f.link(fm, mail)

    sch = f.add("Daily 7:30am", "n8n-nodes-base.scheduleTrigger", 1.2,
                {"rule": {"interval": [{"field": "cronExpression", "expression": "30 7 * * *"}]}}, (0, 400))
    hc = code(f, "Health Config", ALERT_CFG_JS, (240, 400))
    H = "$('Health Config').first().json.cfg"
    ping = dict(onError="continueRegularOutput", alwaysOutputData=True)
    p1 = http(f, "Ping GoHighLevel", "GET", f"={{{{ {H}.ghlBase }}}}/locations/{{{{ {H}.ghlLocationId }}}}", (480, 400),
              cred="ghl", headers=GHL_HEADERS, **ping)
    p2 = http(f, "Ping Klaviyo", "GET", f"={{{{ {H}.klaviyoBase }}}}/api/accounts", (720, 400), cred="klaviyo",
              headers=[("revision", "2024-10-15"), ("accept", "application/vnd.api+json")], **ping)
    p3 = http(f, "Ping Zoom", "POST", f"={{{{ {H}.zoomTokenUrl }}}}", (960, 400), cred="zoom",
              query=[("grant_type", "account_credentials"), ("account_id", f"={{{{ {H}.zoomAccountId }}}}")], **ping)
    p4 = http(f, "Ping WordPress", "GET", f"={{{{ {H}.wpBase }}}}/wp-json/wp/v2/users/me", (1200, 400), cred="wp", **ping)
    summ = code(f, "Summarize Health", HEALTH_JS, (1440, 400))
    anyf = f.add("Anything Failing?", "n8n-nodes-base.if", 2.2, {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                       "conditions": [{"id": _id("health-failed"), "leftValue": "={{ $json.failed }}", "rightValue": 0,
                                       "operator": {"type": "number", "operation": "gt"}}],
                       "combinator": "and"}, "options": {}}, (1680, 400))
    slack2 = http(f, "Slack · Health Warning", "POST", "={{ $json.cfg.slackWebhookUrl }}", (1920, 400),
                  body="={{ JSON.stringify({ text: $json.text }) }}")
    f.chain(sch, hc, p1, p2, p3, p4, summ, anyf)
    f.link(anyf, slack2, 0)

    f.sticky("Alerts", "## Failure alerts\nFires whenever any step of the Student Journey workflow still fails after "
             "its retries. Slack + email, with the failing node, the API error, and a link to the execution.",
             (-40, -260), 980, 170, 3)
    f.sticky("Health", "## Daily health check\nExpired tokens are the #1 silent killer of automations. Every morning "
             "we test each credential and warn in Slack **before** a real student hits the broken step.",
             (-40, 250), 1600, 130, 5)
    return {
        "id": ERR_ID,
        "name": "Student Journey · Error Alerts + Health Check",
        "nodes": f.nodes,
        "connections": f.conns,
        "active": False,
        "settings": {"executionOrder": "v1", "timezone": "America/New_York"},
        "pinData": {},
        "tags": [],
    }


def validate(wf):
    names = [n["name"] for n in wf["nodes"]]
    assert len(names) == len(set(names)), "duplicate node names"
    for src, c in wf["connections"].items():
        assert src in names, src
        for outs in c["main"]:
            for t in outs:
                assert t["node"] in names, t["node"]


if __name__ == "__main__":
    for fname, wf in [("student-journey.json", build_main()), ("error-alerts.json", build_errors())]:
        validate(wf)
        (OUT / fname).write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote workflows/{fname}  ({len(wf['nodes'])} nodes)")
