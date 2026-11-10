# PICU Handoff 6.52

Built from the supplied Version 6.51 package.

Today's latest HEPLMW prints in HEME under DVT Prophylaxis. Older results print
in the lower coagulation area. Today uses the Eastern calendar date, not a
rolling 24-hour interval. The result is not duplicated.

A latest total bilirubin explicitly flagged high adds Hyperbilirubinemia to the
compact Problems line. The original laboratory data and diagnoses are unchanged.

See ANTIXA_BILIRUBIN_UPDATE.md for behavior and installation. UPDATE_FILES.txt
lists the four changed application modules. No new dependencies are needed.
Existing app login, password-free patient clearing, protected Admin settings,
medication categories, SBS behavior and ventilator handling remain unchanged.

No live deployment, credentials or patient archive were accessed. Tests and the
new preview use synthetic data. Current verification is in TEST_REPORT.md and
DELIVERY_VERIFICATION.txt. Historical update notes describe earlier releases.
