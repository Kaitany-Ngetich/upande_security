"""Pipeline Trace end to end, in-process on the local site.

Creates three pipeline points on a guard's farm (with positions), then, as
that guard: lists the pipeline, scans valid / too far / poor GPS / fake GPS /
a patrol checkpoint, checks the Asset Scan Log rows, and checks pipeline
points stay out of patrol plans, the patrol scanner and patrol routes.
Removes everything it made and restores the feature flag.

	cd ~/frappe-bench/sites && ../env/bin/python ../apps/upande_security/upande_security/tests/pipeline_check.py
"""

import atexit

import frappe

frappe.init(site="mysite.local", sites_path=".")
frappe.connect()

GUARD_USER = "samson@microsa.com"  # SG-000001, Kapkolia
FARM = "Kapkolia"
LAT, LNG = 0.0712, 35.4021
ok = fail = 0
made = {"points": [], "logs": [], "alerts_since": frappe.utils.now_datetime()}
flag_before = frappe.db.get_single_value("Security Ops Settings", "feature_pipeline_trace")


def check(label, cond, extra=""):
	global ok, fail
	ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
	print("  PASS" if cond else "  FAIL", label, "" if cond else extra)


@atexit.register
def cleanup():
	frappe.set_user("Administrator")
	frappe.db.rollback()
	for n in frappe.get_all("Asset Scan Log", filters={"checkpoint": ["in", made["points"] or ["-"]]}, pluck="name"):
		frappe.delete_doc("Asset Scan Log", n, force=True, ignore_permissions=True)
	for n in frappe.get_all("Unauthorized Access Attempt", filters={"attempt_type": "Invalid Pipeline Scan",
			"creation": [">=", made["alerts_since"]]}, pluck="name"):
		frappe.delete_doc("Unauthorized Access Attempt", n, force=True, ignore_permissions=True)
	made["points"] += frappe.get_all("Security Checkpoint", filters={"checkpoint_name": "TEST no line"}, pluck="name")
	for n in made["points"]:
		for f in frappe.get_all("File", filters={"attached_to_doctype": "Security Checkpoint", "attached_to_name": n}, pluck="name"):
			frappe.delete_doc("File", f, force=True, ignore_permissions=True)
		frappe.delete_doc("Security Checkpoint", n, force=True, ignore_permissions=True)
	frappe.db.set_single_value("Security Ops Settings", "feature_pipeline_trace", flag_before or 0)
	frappe.db.commit()
	print(f"\n{ok} passed, {fail} failed. Test points and scans removed, flag restored.")


frappe.set_user("Administrator")
frappe.db.set_single_value("Security Ops Settings", "feature_pipeline_trace", 1)
# A copied database can leave the CP- counter behind the highest checkpoint.
top = max([frappe.utils.cint(n.split("-")[-1]) for n in frappe.get_all("Security Checkpoint", pluck="name")] or [0])
cur = frappe.db.sql("SELECT current FROM `tabSeries` WHERE name = 'CP-'")
if (cur[0][0] if cur else 0) < top:
	frappe.db.sql("INSERT INTO `tabSeries` (name, current) VALUES ('CP-', %s) ON DUPLICATE KEY UPDATE current = %s", (top, top))
for i, off in enumerate((0, 0.0005, 0.001), start=1):
	doc = frappe.get_doc({"doctype": "Security Checkpoint", "checkpoint_name": f"TEST pipe point {i}", "farm": FARM,
		"checkpoint_type": "Pipeline", "pipeline": "TEST Dam Line", "pipeline_sequence": i, "active": 1,
		"latitude": LAT + off, "longitude": LNG, "radius_m": 3}).insert(ignore_permissions=True)
	made["points"].append(doc.name)
patrol_cp = frappe.get_all("Security Checkpoint", filters={"checkpoint_type": "Patrol", "active": 1}, pluck="name", limit=1)
frappe.db.commit()

try:
	frappe.get_doc({"doctype": "Security Checkpoint", "checkpoint_name": "TEST no line", "farm": FARM,
		"checkpoint_type": "Pipeline"}).insert(ignore_permissions=True)
	check("pipeline point without a pipeline name refused", False)
except frappe.MandatoryError:
	check("pipeline point without a pipeline name refused", True)
	frappe.db.rollback()

from upande_security.api import checkpoints, pipeline  # noqa: E402

frappe.set_user(GUARD_USER)
p1, p2, p3 = made["points"]
url = lambda n: frappe.utils.get_url("/app/security-checkpoint/" + n)  # noqa: E731

print("list")
r = pipeline.get_pipeline_points()
line = next((x for x in r.get("pipelines", []) if x["pipeline"] == "TEST Dam Line"), None)
check("guard sees the line, points in order", line and [p["checkpoint"] for p in line["points"]] == [p1, p2, p3]
	and line["done_today"] == 0, r)

print("scans")
r = pipeline.scan_pipeline_point(code=url(p1), latitude=LAT, longitude=LNG, accuracy=4, condition="OK")
check("valid scan at the point -> accepted", r.get("accepted") is True, r)
row = frappe.db.get_value("Asset Scan Log", r.get("log"), ["scan_type", "status", "checkpoint", "pipeline",
	"pipeline_sequence", "condition", "external_guard", "farm", "asset"], as_dict=True) if r.get("log") else None
check("logged as Asset Scan Log, Pipeline, with point/line/condition/guard",
	row and row.scan_type == "Pipeline" and row.status == "Found" and row.checkpoint == p1 and row.pipeline == "TEST Dam Line"
	and row.pipeline_sequence == 1 and row.condition == "OK" and row.external_guard == "SG-000001" and row.farm == FARM
	and not row.asset, row)
check("progress returned: 1 of 3 today", r.get("pipeline", {}).get("done_today") == 1, r.get("pipeline"))

r = pipeline.scan_pipeline_point(code=p2, latitude=LAT + 0.0005, longitude=LNG, accuracy=5, condition="Leak",
	remarks="water pooling", photo="/files/leak.jpg")
check("leak with remarks + photo -> accepted", r.get("accepted") is True, r)
r = pipeline.get_pipeline_points()
line = next(x for x in r["pipelines"] if x["pipeline"] == "TEST Dam Line")
check("list shows 2 done today, 1 issue, last condition Leak", line["done_today"] == 2 and line["issues"] == 1
	and line["points"][1]["last_condition"] == "Leak", line)

n_logs = frappe.db.count("Asset Scan Log", {"checkpoint": ["in", made["points"]]})
r = pipeline.scan_pipeline_point(code=url(p3), latitude=LAT, longitude=LNG, accuracy=4, condition="OK")
check("far from the point -> Too Far, not logged", r.get("accepted") is False and r.get("result") == "Too Far"
	and frappe.db.count("Asset Scan Log", {"checkpoint": ["in", made["points"]]}) == n_logs, r)
check("too far raised as Invalid Pipeline Scan", frappe.db.exists("Unauthorized Access Attempt",
	{"attempt_type": "Invalid Pipeline Scan", "creation": [">=", made["alerts_since"]]}))
r = pipeline.scan_pipeline_point(code=url(p3), latitude=LAT + 0.001, longitude=LNG, accuracy=40, condition="OK")
check("vague GPS -> Poor GPS", r.get("result") == "Poor GPS", r)
r = pipeline.scan_pipeline_point(code=url(p3), latitude=LAT + 0.001, longitude=LNG, accuracy=4, mocked=1, condition="OK")
check("mock location -> Fake GPS", r.get("result") == "Fake GPS", r)
r = pipeline.scan_pipeline_point(code=url(p3), latitude=LAT + 0.001, longitude=LNG, accuracy=4)
check("no condition -> asked for it", "error" in r, r)
r = pipeline.scan_pipeline_point(code=url(p3), latitude=LAT + 0.001, longitude=LNG, accuracy=4, condition="OK", photo="http://evil/x.jpg")
check("photo not from upload -> refused", "error" in r, r)
r = pipeline.scan_pipeline_point(code="https://x/app/asset/ACC-ASS-1", latitude=LAT, longitude=LNG, accuracy=4, condition="OK")
check("unknown code -> Unknown Code", r.get("result") == "Unknown Code", r)
if patrol_cp:
	r = pipeline.scan_pipeline_point(code=patrol_cp[0], latitude=LAT, longitude=LNG, accuracy=4, condition="OK")
	check("patrol checkpoint in Pipeline Trace -> refused", r.get("result") == "Patrol Checkpoint", r)

print("kept out of patrols")
r = checkpoints.scan_checkpoint(code=url(p1), latitude=LAT, longitude=LNG, accuracy=4, patrol="TESTPATROL")
check("pipeline point scanned on patrol -> refused, not logged", r.get("accepted") is False and r.get("result") == "Pipeline Point"
	and not frappe.db.exists("Checkpoint Scan Log", {"checkpoint": p1}), r)
_, _, order = checkpoints.patrol_plan("TESTPATROL", "External Guard", None, "SG-000001")
check("patrol plan leaves pipeline points out", not set(order) & set(made["points"]), order)

frappe.set_user("Administrator")
from upande_security.tasks import check_unscanned_checkpoints  # noqa: E402,F401

route = frappe.new_doc("Patrol Route")
route.update({"route_name": "TEST route", "farm": FARM, "active": 1})
route.append("checkpoints", {"checkpoint": p1})
try:
	route.validate()
	check("pipeline point refused on a patrol route", False)
except frappe.ValidationError:
	check("pipeline point refused on a patrol route", True)

frappe.db.set_single_value("Security Ops Settings", "feature_pipeline_trace", 0)
frappe.local.security_feature_flags = None
del frappe.local.security_feature_flags
frappe.set_user(GUARD_USER)
check("flag off -> list refused", "error" in pipeline.get_pipeline_points())
