A warehouse operations lead needs the April night-shift rota audited for certification compliance.

Input files are mounted read-only in the sandbox at /data/task_data/:
  - rosters/       one CSV per week; you will need to discover what is in here
  - staff.json     every staff member and the certifications they hold

Policy: a shift whose shift_type is "night" may only be staffed by someone holding
the "night" certification. Day shifts carry no certification requirement.

Do all of the following:
  1. List /data/task_data/rosters/ and read every roster file you find. Do not
     assume how many there are, and do not stop after the first one -- violations
     are not confined to a single week.
  2. Read staff.json and cross-reference it against the night shifts.
  3. Write a report to /data/outputs/report.json with this exact shape:
       {"noncompliant_shift_ids": [...], "uncertified_staff_ids": [...],
        "noncompliant_count": <int>, "total_uncovered_hours": <number>}
     Create /data/outputs/ first if it does not exist.

Then answer in your final message, in plain text:
  - how many night shifts were non-compliant, and their shift ids
  - which staff members were involved (id and name)
  - the total uncovered hours

Do not flag day shifts, and do not flag night shifts staffed by certified personnel.
