#!/usr/bin/env python3
"""Local stand-in for GoHighLevel, Klaviyo, Zoom, WordPress/LearnDash and Slack.

    python3 mock/mock_apis.py            # listens on http://localhost:4010

Lets the whole student journey fire end-to-end with test data before any real
credentials exist. Each call is logged as the handoff it represents, so this
terminal doubles as the "what just happened" view in the walkthrough.

Failure injection (for demoing the alert layer):
    curl -X POST localhost:4010/__fail/zoom     # every Zoom call now returns 503
    curl -X POST localhost:4010/__heal          # back to normal
    curl localhost:4010/__state                 # everything the mock has stored
    curl localhost:4010/__log?since=0           # every logged handoff as JSON
"""
import hashlib
import json
import re
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4010

COLORS = {"ghl": "\033[38;5;39m", "klaviyo": "\033[38;5;46m", "zoom": "\033[38;5;33m",
          "wp": "\033[38;5;208m", "slack": "\033[38;5;199m", "mock": "\033[38;5;245m"}
LABEL = {"ghl": "GoHighLevel", "klaviyo": "Klaviyo", "zoom": "Zoom", "wp": "WordPress", "slack": "Slack", "mock": "mock"}
RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"

state = {"contacts": {}, "tags": {}, "klaviyo_profiles": {}, "klaviyo_lists": {}, "klaviyo_events": [],
         "registrants": {}, "wp_users": {}, "enrollments": [], "posts": [], "alerts": [], "failing": set()}


def sid(prefix, s):
    return prefix + hashlib.sha1(s.encode()).hexdigest()[:8]


LOG = []  # plain-text copy of every line, served at /__log for recordings/dashboards


def log(svc, msg):
    t = datetime.now().strftime("%H:%M:%S")
    LOG.append({"t": t, "svc": svc, "label": LABEL[svc], "msg": re.sub(r"\033\[[0-9;]*m", "", msg)})
    print(f"{DIM}{t}{RESET} {COLORS[svc]}{BOLD}{LABEL[svc]:>11}{RESET}  {msg}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def _send(self, code, payload=None):
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(code)
        if data:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def route(self, method):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = u.path.strip("/").split("/")
        svc, path = parts[0], "/" + "/".join(parts[1:])
        body = self._body() if method in ("POST", "PUT") else {}

        if svc == "__fail":
            state["failing"].add(parts[1])
            log("mock", f"{BOLD}\033[31m{LABEL.get(parts[1], parts[1])} is now DOWN (503){RESET}")
            return self._send(200, {"failing": sorted(state["failing"])})
        if svc == "__heal":
            state["failing"].clear()
            log("mock", "all services healthy again")
            return self._send(200, {"failing": []})
        if svc == "__log":
            return self._send(200, LOG[int(q.get("since", 0)):])
        if svc == "__state":
            return self._send(200, {k: (sorted(v) if isinstance(v, set) else v) for k, v in state.items()})
        if svc == "__reset":
            for k, v in state.items():
                v.clear()
            LOG.clear()
            log("mock", "state cleared")
            return self._send(200, {"ok": True})

        if svc in state["failing"]:
            log(svc, f"\033[31m{method} {path} → 503 Service Unavailable (injected){RESET}")
            return self._send(503, {"message": f"{LABEL.get(svc, svc)} is temporarily unavailable"})

        handler = getattr(self, "svc_" + svc, None)
        if not handler:
            return self._send(404, {"message": "unknown service"})
        code, payload = handler(method, path, q, body)
        return self._send(code, payload)

    # ── GoHighLevel ─────────────────────────────────────────────────
    def svc_ghl(self, m, p, q, b):
        if m == "POST" and p == "/contacts/upsert":
            cid = sid("ghl_", b["email"])
            new = cid not in state["contacts"]
            state["contacts"][cid] = {**state["contacts"].get(cid, {}), **b, "id": cid}
            log("ghl", f"contact {'created' if new else 'updated'}  {b['email']}  ({cid})")
            return 200, {"new": new, "contact": {"id": cid, "email": b["email"], "tags": state["tags"].get(cid, [])}}
        if m == "POST" and (mt := re.fullmatch(r"/contacts/([^/]+)/tags", p)):
            tags = state["tags"].setdefault(mt[1], [])
            tags += [t for t in b["tags"] if t not in tags]
            log("ghl", f"tagged {', '.join(repr(t) for t in b['tags'])}  → tags now {tags}")
            return 201, {"tags": tags}
        if m == "PUT" and (mt := re.fullmatch(r"/contacts/([^/]+)", p)):
            state["contacts"].setdefault(mt[1], {})["customFields"] = b.get("customFields")
            log("ghl", f"custom field saved  {b.get('customFields')}")
            return 200, {"contact": {"id": mt[1]}}
        if m == "GET" and p.startswith("/locations/"):
            return 200, {"location": {"id": p.split("/")[-1]}}
        return 404, {"message": "not found"}

    # ── Klaviyo ─────────────────────────────────────────────────────
    def svc_klaviyo(self, m, p, q, b):
        if m == "POST" and p == "/api/profile-import":
            a = b["data"]["attributes"]
            pid = sid("kl_", a["email"])
            state["klaviyo_profiles"][pid] = a
            props = a.get("properties", {})
            log("klaviyo", f"profile upserted  {a['email']}  stage={props.get('journey_stage')}  "
                           f"zoom_join_url={'✓' if props.get('zoom_join_url') else '—'}")
            return 200, {"data": {"type": "profile", "id": pid, "attributes": a}}
        if m == "POST" and p == "/api/profile-subscription-bulk-create-jobs":
            lst = b["data"]["relationships"]["list"]["data"]["id"]
            for prof in b["data"]["attributes"]["profiles"]["data"]:
                state["klaviyo_lists"].setdefault(lst, []).append(prof["attributes"]["email"])
                log("klaviyo", f"subscribed to list {lst}  → {BOLD}nurture flow triggered{RESET}")
            return 202, None
        if m == "POST" and p == "/api/events":
            a = b["data"]["attributes"]
            name = a["metric"]["data"]["attributes"]["name"]
            email = a["profile"]["data"]["attributes"]["email"]
            if any(e["unique_id"] == a.get("unique_id") for e in state["klaviyo_events"]):
                log("klaviyo", f"event '{name}' for {email} deduplicated (unique_id seen)")
                return 202, None
            state["klaviyo_events"].append({"metric": name, "email": email, **a})
            extra = f"  attended={a['properties'].get('attended')}" if "attended" in a["properties"] else ""
            log("klaviyo", f"event {BOLD}'{name}'{RESET}  {email}{extra}  → flow triggered")
            return 202, None
        if m == "GET" and p == "/api/accounts":
            return 200, {"data": [{"type": "account", "id": "MOCK"}]}
        return 404, {"errors": [{"detail": "not found"}]}

    # ── Zoom ────────────────────────────────────────────────────────
    def svc_zoom(self, m, p, q, b):
        if p == "/oauth/token":
            return 200, {"access_token": "mock-zoom-token", "token_type": "bearer", "expires_in": 3600}
        if (mt := re.fullmatch(r"/v2/webinars/(\d+)/registrants", p)):
            regs = state["registrants"].setdefault(mt[1], {})
            if m == "POST":
                rid = sid("zr_", b["email"])
                regs[b["email"]] = {"id": rid, "email": b["email"], "first_name": b.get("first_name"),
                                    "last_name": b.get("last_name")}
                url = f"https://zoom.us/w/{mt[1]}?tk={rid}"
                log("zoom", f"registered for webinar {mt[1]}  {b['email']}  → confirmation + calendar invite sent")
                return 201, {"id": int(mt[1]), "registrant_id": rid, "join_url": url, "topic": "Live Masterclass"}
            log("zoom", f"listed {len(regs)} registrant(s) for webinar {mt[1]}")
            return 200, {"total_records": len(regs), "registrants": list(regs.values())}
        if m == "GET" and (mt := re.fullmatch(r"/v2/past_webinars/(\d+)/participants", p)):
            # Anyone whose email contains "missed" is treated as a no-show.
            ps = [{"user_email": r["email"], "name": r["first_name"]}
                  for r in state["registrants"].get(mt[1], {}).values() if "missed" not in r["email"]]
            log("zoom", f"attendance report: {len(ps)} attended webinar {mt[1]}")
            return 200, {"total_records": len(ps), "participants": ps}
        return 404, {"code": 3001, "message": "not found"}

    # ── WordPress + LearnDash ───────────────────────────────────────
    def svc_wp(self, m, p, q, b):
        users = state["wp_users"]
        if p == "/wp-json/wp/v2/users" and m == "GET":
            hits = [u for u in users.values() if q.get("search", "").lower() in u["email"]]
            log("wp", f"user lookup {q.get('search')} → {'found #' + str(hits[0]['id']) if hits else 'no account yet'}")
            return 200, hits
        if p == "/wp-json/wp/v2/users" and m == "POST":
            uid = 100 + len(users) + 1
            users[b["email"]] = {"id": uid, "email": b["email"], "name": b.get("first_name", ""), "roles": b.get("roles")}
            log("wp", f"student account created #{uid}  {b['email']}")
            return 201, users[b["email"]]
        if p == "/wp-json/wp/v2/users/me":
            return 200, {"id": 1, "name": "n8n-bot"}
        if m == "POST" and (mt := re.fullmatch(r"/wp-json/ldlms/v2/sfwd-courses/(\d+)/users", p)):
            for uid in b["user_ids"]:
                state["enrollments"].append({"course": int(mt[1]), "user": uid})
            log("wp", f"{BOLD}LearnDash: course {mt[1]} unlocked{RESET} for user #{b['user_ids'][0]}")
            return 200, [{"course_id": int(mt[1]), "user_id": u, "enrolled": True} for u in b["user_ids"]]
        if m == "POST" and p == "/wp-json/wp/v2/posts":
            pid = 900 + len(state["posts"]) + 1
            post = {"id": pid, "link": f"https://your-academy.com/replays/{b['slug']}/", **b}
            state["posts"].append(post)
            log("wp", f"replay page published → {post['link']}")
            return 201, post
        return 404, {"code": "rest_no_route"}

    # ── Slack incoming webhook ──────────────────────────────────────
    def svc_slack(self, m, p, q, b):
        state["alerts"].append(b.get("text"))
        LOG.append({"t": datetime.now().strftime("%H:%M:%S"), "svc": "slack", "label": "Slack", "msg": b.get("text") or ""})
        print(f"\n{COLORS['slack']}{BOLD}┌─ Slack #automation-alerts ─────────────────────────────{RESET}")
        for line in (b.get("text") or "").splitlines():
            print(f"{COLORS['slack']}│{RESET} {line}")
        print(f"{COLORS['slack']}{BOLD}└────────────────────────────────────────────────────────{RESET}\n", flush=True)
        return 200, {"ok": True}


if __name__ == "__main__":
    print(f"{BOLD}Student-journey mock APIs{RESET} on http://localhost:{PORT}  "
          f"(ghl · klaviyo · zoom · wp · slack)\n", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
