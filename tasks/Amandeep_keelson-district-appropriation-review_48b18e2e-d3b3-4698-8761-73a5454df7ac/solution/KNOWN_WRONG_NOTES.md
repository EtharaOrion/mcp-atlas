# Why there is no page_gross_reported control
#
# solve.sh's REACHABLE WRONG TOTALS table lists 309,380 first: "summed every
# dollar figure printed on the six pages and stopped". It is a real misreading a
# person makes, and it is deliberately NOT a control here.
#
# rewarddefinition requires every known-wrong to score strictly above the no-op,
# because a control that ties the floor tests what the `empty` variant already
# tests. This misreading cannot satisfy that by construction: the task IS the
# classification, so a run that applies none of it earns nothing. Measured
# 2026-09-05 rather than assumed -- implemented as three keying corrections with
# no classifications, it made four real writes and lifted completion_rate from
# 0.148148 to 0.240741, and still scored traj_tests 0.0, rubric 0.0, reward 0.0.
# An earlier implementation that filed nothing at all scored the same.
#
# So it is the no-op rung wearing a control's name. Filing it as a known-wrong
# would enter the same test twice under two names and make the ordering check
# unsatisfiable for a reason that says nothing about the reward.
#
# The remaining eight controls land between 0.0715 and 0.1758 against a no-op of
# 0.0 and an oracle of 0.5009, which is the separation the instrument is for.
