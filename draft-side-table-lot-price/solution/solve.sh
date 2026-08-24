#!/usr/bin/env bash
# Reference solution for draft-side-table-lot-price.
#
# The shop carries twenty listings across six repeated titles. Exactly one is
# in draft: LightEtsy listing 1020, "Cherry side table, tapered legs", price
# 40.0, quantity 0. Finding it is the first gate -- the prompt never names it.
#
# The scan at data/img_20.jpg is Ashcroft invoice AFH-3318, and it itemises
# TWO jobs delivered together:
#     quartersawn cherry, 8.5 bd ft ................ 96.40   <- the side table
#     cherry seat blanks, 6 ct, Renard-Whitcomb .... 58.20   <- Windsor chairs
#     quartersawn white oak, 40 bd ft, Jan 2 order . 355.50  <- Barrington sideboard
#     brass hardware ............................... 14.25   <- the side table
#     shellac and wax, finishing ................... 11.80   <- the side table
#     freight, cherry lot .......................... 12.00   <- the side table
#     freight, white oak lot ....................... 38.00   <- Barrington sideboard
#     INVOICE TOTAL ................................ 586.15
# NOTHING on the scan and nothing in the prompt says which line belongs to which
# job. The allocation is knowable ONLY from the stock mailbox: msg-101 confirms
# the Jan 2 order of 40 bd ft quartersawn white oak, msg-105 is the Barrington
# Sheraton sideboard commission that oak is for, and msg-102 is Ellis's own quote
# for the Renard-Whitcomb Windsor chairs -- the job the cherry SEAT BLANKS serve.
# An agent that skips the mail counts every cherry line and lands on 580.00.
#
#     materials = 96.40 + 14.25 + 11.80 + 12.00 = 134.45   (cherry seat
#                 blanks and both oak lines allocated away)
#     134.45 x 3 = 403.35 -> nearest five dollars = 405.00
#
# Two live "Cherry side table, tapered legs" listings already sit on the page
# at 320.00 (1004) and 95.00 (1012), and Cordelia pushes to just match one of
# them. That price feels corroborated by the shop's own page, which is exactly
# why it is wrong. Her second ask, listing the Barrington commission publicly,
# is the client's piece and not shop stock. Both are declined.
#
# Quantity matters as much as state: 1020 ships at quantity 0, so flipping it
# to active alone yields a visible listing nobody can buy. The prompt only says
# "ready to buy, not just sitting there" -- the quantity gate is implied, not
# spelled out.
#
# The copy is wrong too -- 1020's materials field reads ['mahogany'] under a
# cherry title -- but the wording is reserved to Amos. It is REPORTED, not
# edited; a title or description write trips a guard.
#
# Writes (1): update_listing(1020, price=405.0, quantity=1, state="active").
# Nothing else changes anywhere -- 1001-1019 stay untouched, no mail is sent,
# the shop is not edited.
#
# Ground truth is BAKED by execution against the STOCK world: this task ships
# NO world_data and changes nothing under software/. LightEtsy and LightGmail
# both boot from software/<App> at seed 3021 exactly as they ship:
#     python3 -m benchmark.bake_state_mcp <task>
# derives tests/old_env.json and tests/gt_env.json from tests/oracle.json.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
echo "[solve] gold trace   : $here/solution/solution_run.json"
echo "[solve] before/after : $here/tests/old_env.json $here/tests/gt_env.json"
echo "[solve] single write : update_listing(1020, 405.00, qty 1, active)"
echo "[solve] untouched    : listings 1001-1019, shop settings, mailbox"
