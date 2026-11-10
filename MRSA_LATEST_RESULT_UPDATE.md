# PICU Handoff 6.59: latest MRSA result

MRSA Screen now reads both MRSADNA and MRSANPADM. It compares all included
results from both codes and displays the newest laboratory collection date,
using the collection time when provided. The upload date, handoff-save time,
code name and position in the pasted text do not override the lab date.

The label stays bold. The chosen result and original collection date stay
visible. A newer negative result replaces an older positive result. Pending
results keep their supplied wording. If tied dates lack enough time information,
the existing Epic row order is used without inventing a collection time.

Source rows remain unchanged. Both codes remain available in the lab editor,
with a single combined MRSA Screen in demographics and no duplicate lab card.

From 6.58, replace app.py, labs.py and mrsa.py together, or upload the full
application folder. Keep app.py at the repository root and restart Streamlit.
Existing saved rows for either component work immediately. Add MRSANPADM to
your pasted G laboratory block when that result is not already supplied.
No new dependency, encryption key or archive migration is needed.
