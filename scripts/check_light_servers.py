#!/usr/bin/env python3
import asyncio
import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, NamedTuple, Optional

try:
    from fastmcp import Client
except ImportError:
    sys.exit("fastmcp not installed - run: pip install fastmcp")


class ToolServer(NamedTuple):
    name: str
    port: int
    probe_tool: Optional[str]
    probe_args: Optional[Dict]


class SoftwareApp(NamedTuple):
    name: str
    port: int
    first_tool: Optional[str]


TOOL_SERVERS: List[ToolServer] = [
    ToolServer("math",          8000, "add",              {"a": 1, "b": 2}),
    ToolServer("unit",          8001, None,               None),
    ToolServer("osint",         8002, None,               None),
    ToolServer("time",          8003, None,               None),
    ToolServer("lang",          8004, None,               None),
    ToolServer("crypto",        8005, None,               None),
    ToolServer("graphs",        8006, "bfs",              {"adj": {"A": ["B"], "B": []}, "start": "A"}),
    ToolServer("chem",          8007, None,               None),
    ToolServer("url",           8013, None,               None),
    ToolServer("csv_server",    8014, None,               None),
    ToolServer("json_server",   8015, None,               None),
    ToolServer("diff",          8016, "similarity_ratio", {"a": "hello", "b": "hello"}),
    ToolServer("hash",          8017, "md5",              {"text": "hello"}),
    ToolServer("color",         8018, None,               None),
    ToolServer("encoding",      8019, "base64_encode",    {"text": "hello"}),
    ToolServer("barcode",       8020, None,               None),
    ToolServer("calendar_math", 8021, None,               None),
    ToolServer("currency",      8022, None,               None),
    ToolServer("random_server", 8023, "word",             {}),
    ToolServer("template",      8024, None,               None),
    ToolServer("filesystem",    8090, "file_exists",      {"path": ""}),
]

SOFTWARE_APPS: List[SoftwareApp] = [
    SoftwareApp("LightSystem",          9000,  None),
    SoftwareApp("LightTalk",            9001,  "get_all_contacts"),
    SoftwareApp("LightShop",            9002,  "list_all_shop_categories"),
    SoftwareApp("LightWeather",         9003,  "list_cities"),
    SoftwareApp("LightFlight",          9004,  "list_all_cities"),
    SoftwareApp("LightStock",           9005,  "get_account_summary"),
    SoftwareApp("LightNews",            9006,  "list_all_sections"),
    SoftwareApp("LightMail",            9007,  "list_folders"),
    SoftwareApp("LightCalendar",        9008,  "list_calendars"),
    SoftwareApp("LightTasks",           9014,  "list_projects"),
    SoftwareApp("LightNotes",           9015,  "list_notebooks"),
    SoftwareApp("LightMeet",            9016,  "list_meetings"),
    SoftwareApp("LightCRM",             9017,  "list_contacts"),
    SoftwareApp("LightHR",              9018,  "list_employees"),
    SoftwareApp("LightIssues",          9019,  "list_issues"),
    SoftwareApp("LightBudget",          9020,  "list_categories"),
    SoftwareApp("LightWallet",          9021,  "list_wallets"),
    SoftwareApp("LightTax",             9022,  "list_filings"),
    SoftwareApp("LightAuction",         9023,  "list_listings"),
    SoftwareApp("LightSubscription",    9024,  "list_subscriptions"),
    SoftwareApp("LightRide",            9025,  "list_rides"),
    SoftwareApp("LightHotel",           9026,  "list_hotels"),
    SoftwareApp("LightRental",          9027,  "list_assets"),
    SoftwareApp("LightFood",            9028,  "list_restaurants"),
    SoftwareApp("LightVideo",           9029,  "list_videos"),
    SoftwareApp("LightPodcast",         9030,  "list_podcasts"),
    SoftwareApp("LightPhoto",           9031,  "list_albums"),
    SoftwareApp("LightRead",            9032,  "list_books"),
    SoftwareApp("LightForum",           9033,  "list_subforums"),
    SoftwareApp("LightHome",            9034,  "list_rooms"),
    SoftwareApp("LightSecurity",        9035,  "list_cameras"),
    SoftwareApp("LightEnergy",          9036,  "list_meters"),
    SoftwareApp("LightFitness",         9037,  "list_exercises"),
    SoftwareApp("LightMed",             9038,  "list_prescriptions"),
    SoftwareApp("LightLearn",           9039,  "list_courses"),
    SoftwareApp("LightVault",           9040,  "list_entries"),
    SoftwareApp("LightDrive",           9041,  "list_folders"),
    SoftwareApp("LightSign",            9042,  "list_documents"),
    SoftwareApp("LightGame",            9043,  "list_games"),
    SoftwareApp("LightActiveCampaign",  9044,  "list_contacts"),
    SoftwareApp("LightAirbnb",          9045,  None),  # search_listings needs location
    SoftwareApp("LightAirtable",        9046,  "list_bases"),
    SoftwareApp("LightAlgolia",         9047,  "list_indexes"),
    SoftwareApp("LightAlpaca",          9048,  "get_account"),
    SoftwareApp("LightAmadeus",         9049,  None),  # search_flight_offers needs origin/dest
    SoftwareApp("LightAmazonSeller",    9050,  "get_seller_account"),
    SoftwareApp("LightAmplitude",       9051,  None),  # ingest needs event payload
    SoftwareApp("LightAsana",           9052,  "list_workspaces"),
    SoftwareApp("LightBambooHR",        9053,  "get_company"),
    SoftwareApp("LightBigCommerce",     9054,  "list_products"),
    SoftwareApp("LightBinance",         9055,  None),  # get_ticker_price needs symbol
    SoftwareApp("LightBox",             9056,  "get_me"),
    SoftwareApp("LightCalendly",        9057,  "get_me"),
    SoftwareApp("LightCloudflare",      9058,  "list_zones"),
    SoftwareApp("LightCoinbase",        9059,  "get_user"),
    SoftwareApp("LightConfluence",      9060,  "list_spaces"),
    SoftwareApp("LightContentful",      9061,  "get_space"),
    SoftwareApp("LightDatadog",         9062,  None),  # query_metrics needs metric + time range
    SoftwareApp("LightDiscord",         9063,  "get_me"),
    SoftwareApp("LightDocuSign",        9064,  "list_envelopes"),
    SoftwareApp("LightDoorDash",        9065,  "list_stores"),
    SoftwareApp("LightDropbox",         9066,  "get_current_account"),
    SoftwareApp("LightEtsy",            9067,  "get_current_user"),
    SoftwareApp("LightEventbrite",      9068,  "list_organizations"),
    SoftwareApp("LightFedEx",           9069,  None),  # get_rate_quote needs shipment data
    SoftwareApp("LightFigma",           9070,  "get_me"),
    SoftwareApp("LightFreshdesk",       9071,  "list_tickets"),
    SoftwareApp("LightGithub",          9072,  "get_user"),
    SoftwareApp("LightGitlab",          9073,  "get_current_user"),
    SoftwareApp("LightGmail",           9074,  "get_profile"),
    SoftwareApp("LightGoogleAnalytics", 9075,  None),  # run_report needs date range + metric
    SoftwareApp("LightGoogleCalendar",  9076,  "list_calendars"),
    SoftwareApp("LightGoogleClassroom", 9077,  "list_courses"),
    SoftwareApp("LightGoogleDrive",     9078,  "get_about"),
    SoftwareApp("LightGoogleMaps",      9079,  None),  # text_search needs query string
    SoftwareApp("LightGreenhouse",      9080,  "list_candidates"),
    SoftwareApp("LightGusto",           9081,  "get_company"),
    SoftwareApp("LightHubspot",         9082,  "list_contacts"),
    SoftwareApp("LightInstacart",       9083,  "get_user"),
    SoftwareApp("LightInstagram",       9084,  None),  # search_hashtags needs hashtag
    SoftwareApp("LightIntercom",        9085,  "list_contacts"),
    SoftwareApp("LightJira",            9086,  "list_projects"),
    SoftwareApp("LightKlaviyo",         9087,  "list_profiles"),
    SoftwareApp("LightKraken",          9088,  None),  # get_ticker needs trading pair
    SoftwareApp("LightKubernetes",      9089,  "list_namespaces"),
    SoftwareApp("LightLinear",          9090,  "list_teams"),
    SoftwareApp("LightLinkedIn",        9091,  "get_me"),
    SoftwareApp("LightMailchimp",       9092,  "list_lists"),
    SoftwareApp("LightMailgun",         9093,  None),  # send_message needs recipient + content
    SoftwareApp("LightMicrosoftTeams",  9094,  "list_joined_teams"),
    SoftwareApp("LightMixpanel",        9095,  None),  # track needs event payload
    SoftwareApp("LightMonday",          9096,  "list_workspaces"),
    SoftwareApp("LightMyFitnessPal",    9097,  "get_user_profile"),
    SoftwareApp("LightNASA",            9098,  "get_apod"),
    SoftwareApp("LightNotion",          9099,  "list_users"),
    SoftwareApp("LightObsidian",        9100,  "get_vault"),
    SoftwareApp("LightOkta",            9101,  "list_users"),
    SoftwareApp("LightOpenLibrary",     9102,  None),  # search needs query string
    SoftwareApp("LightOpenWeather",     9103,  None),  # get_current_weather needs city
    SoftwareApp("LightOutlook",         9104,  "list_messages"),
    SoftwareApp("LightPagerDuty",       9105,  "list_users"),
    SoftwareApp("LightPayPal",          9106,  None),  # create_order needs amount/currency
    SoftwareApp("LightPinterest",       9107,  "get_user_account"),
    SoftwareApp("LightPlaid",           9108,  "get_accounts"),
    SoftwareApp("LightPostHog",         9109,  None),  # capture needs distinct_id + event
    SoftwareApp("LightQuickBooks",      9110,  "get_company_info"),
    SoftwareApp("LightReddit",          9111,  None),  # subreddit_about needs subreddit name
    SoftwareApp("LightRing",            9112,  "list_devices"),
    SoftwareApp("LightSalesforce",      9113,  None),  # list_records needs object_type
    SoftwareApp("LightSegment",         9114,  None),  # track needs event payload
    SoftwareApp("LightSendGrid",        9115,  None),  # send_mail needs to/from/subject/body
    SoftwareApp("LightSentry",          9116,  "list_org_projects"),
    SoftwareApp("LightServiceNow",      9117,  "list_incidents"),
    SoftwareApp("LightShippo",          9118,  None),  # create_address needs address fields
    SoftwareApp("LightSlack",           9119,  "auth_test"),
    SoftwareApp("LightSpotify",         9120,  "get_me"),
    SoftwareApp("LightSquare",          9121,  "get_merchant"),
    SoftwareApp("LightStrava",          9122,  "get_athlete"),
    SoftwareApp("LightStripe",          9123,  "list_customers"),
    SoftwareApp("LightTMDB",            9124,  None),  # search_movie needs query string
    SoftwareApp("LightTelegram",        9125,  "get_me"),
    SoftwareApp("LightTicketmaster",    9126,  None),  # search_events needs keyword
    SoftwareApp("LightTrello",          9127,  "get_me"),
    SoftwareApp("LightTwilio",          9128,  "list_messages"),
    SoftwareApp("LightTwitch",          9129,  None),  # get_channels may need query
    SoftwareApp("LightTwitter",         9130,  "get_me"),
    SoftwareApp("LightTypeform",        9131,  "list_forms"),
    SoftwareApp("LightUPS",             9132,  None),  # get_rate needs shipment data
    SoftwareApp("LightUber",            9133,  None),  # list_products needs lat/lon
    SoftwareApp("LightVimeo",           9134,  "get_me"),
    SoftwareApp("LightWebflow",         9135,  "list_sites"),
    SoftwareApp("LightWhatsApp",        9136,  "get_business"),
    SoftwareApp("LightWooCommerce",     9137,  "list_products"),
    SoftwareApp("LightWordPress",       9138,  "list_posts"),
    SoftwareApp("LightXero",            9139,  "list_invoices"),
    SoftwareApp("LightYelp",            9140,  None),  # search_businesses needs term/location
    SoftwareApp("LightYouTube",         9141,  None),  # get_channel may need channel_id
    SoftwareApp("LightZendesk",         9142,  "list_tickets"),
    SoftwareApp("LightZillow",          9143,  None),  # search_properties needs location
    SoftwareApp("LightZoom",            9144,  "get_me"),
]


@dataclass
class Result:
    name: str
    port: int
    kind: Literal["tool", "software"]
    passed: bool
    steps: List[str] = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0


def _extract_result_value(result: Any) -> Any:
    sc = getattr(result, "structured_content", None)
    if sc is not None:
        return sc
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if text:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
    return None


def _mcp_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/mcp"


async def probe_tool_server(
    host: str,
    server: ToolServer,
    timeout: float,
    sem: asyncio.Semaphore,
) -> Result:
    start = time.monotonic()
    steps: List[str] = []

    async def _run() -> Result:
        async with Client(_mcp_url(host, server.port)) as client:
            tools = await client.list_tools()
            steps.append(f"list_tools -> {len(tools)} tools")
            if not tools:
                raise RuntimeError("no tools returned")
            if server.probe_tool:
                r = await client.call_tool(name=server.probe_tool, arguments=server.probe_args or {})
                val = _extract_result_value(r)
                steps.append(f"{server.probe_tool}() -> {str(val)[:60]}")
        return Result(server.name, server.port, "tool", True, steps, "", time.monotonic() - start)

    async with sem:
        try:
            return await asyncio.wait_for(_run(), timeout=timeout)
        except Exception as exc:
            return Result(server.name, server.port, "tool", False, steps, str(exc), time.monotonic() - start)


async def probe_lightsystem(host: str, timeout: float, sem: asyncio.Semaphore) -> tuple:
    start = time.monotonic()
    steps: List[str] = []
    session_id = ""

    async def _run() -> tuple:
        nonlocal session_id
        async with Client(_mcp_url(host, 9000)) as client:
            r = await client.call_tool(name="login", arguments={})
            data = _extract_result_value(r)
            if not isinstance(data, dict) or data.get("status") != "ok":
                raise RuntimeError(f"login returned: {data}")
            session_id = data["session_id"]
            steps.append(f"login -> session_id={session_id[:12]}...")
            r2 = await client.call_tool(name="health", arguments={"session_id": session_id})
            val = _extract_result_value(r2)
            steps.append(f"health() -> {str(val)[:60]}")
        return (
            Result("LightSystem", 9000, "software", True, steps, "", time.monotonic() - start),
            session_id,
        )

    async with sem:
        try:
            return await asyncio.wait_for(_run(), timeout=timeout)
        except Exception as exc:
            return (
                Result("LightSystem", 9000, "software", False, steps, str(exc), time.monotonic() - start),
                "",
            )


async def probe_software_app(
    host: str,
    app: SoftwareApp,
    ls_session_id: str,
    timeout: float,
    sem: asyncio.Semaphore,
) -> Result:
    start = time.monotonic()
    steps: List[str] = []
    os_cfg = {"session_id": ls_session_id, "url": _mcp_url(host, 9000)}

    async def _run() -> Result:
        async with Client(_mcp_url(host, app.port)) as client:
            r = await client.call_tool(name="login", arguments={"os_cfg": os_cfg})
            data = _extract_result_value(r)
            if not isinstance(data, dict) or data.get("status") != "ok":
                raise RuntimeError(f"login returned: {data}")
            sid = data["session_id"]
            steps.append(f"login -> session_id={sid[:12]}...")
            if app.first_tool:
                r2 = await client.call_tool(name=app.first_tool, arguments={"session_id": sid})
                val = _extract_result_value(r2)
                steps.append(f"{app.first_tool}() -> {str(val)[:60]}")
            await client.call_tool(name="logout", arguments={"session_id": sid})
            steps.append("logout -> ok")
        return Result(app.name, app.port, "software", True, steps, "", time.monotonic() - start)

    async with sem:
        try:
            return await asyncio.wait_for(_run(), timeout=timeout)
        except Exception as exc:
            return Result(app.name, app.port, "software", False, steps, str(exc), time.monotonic() - start)


def print_results(results: List[Result], verbose: bool) -> None:
    tool_results = [r for r in results if r.kind == "tool"]
    sw_results   = [r for r in results if r.kind == "software"]

    def _section(title: str, rows: List[Result]) -> None:
        passed = sum(1 for r in rows if r.passed)
        print(f"\n{'─' * 72}")
        print(f"  {title}  ({passed}/{len(rows)} passed)")
        print(f"{'─' * 72}")
        for r in sorted(rows, key=lambda x: x.port):
            mark   = "✓" if r.passed else "✗"
            status = "PASS" if r.passed else "FAIL"
            detail = f"  {r.error[:60]}" if not r.passed and r.error else ""
            print(f"  {mark} {status}  port={r.port:<5}  {r.name:<28}  {r.elapsed:.2f}s{detail}")
            if verbose and r.steps:
                for step in r.steps:
                    print(f"         {step}")

    _section("TOOL SERVERS", tool_results)
    _section("SOFTWARE APPS", sw_results)

    total  = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    print(f"\n{'═' * 72}")
    print(f"  TOTAL  {passed}/{total} passed  |  {failed} failed")
    print(f"{'═' * 72}\n")

    if failed:
        print("Failed servers:")
        for r in results:
            if not r.passed:
                print(f"  port={r.port}  {r.name}")
                if r.error:
                    print(f"    {r.error[:120]}")


async def run(args: argparse.Namespace) -> int:
    host        = args.host
    timeout     = args.timeout
    concurrency = args.concurrency
    sem         = asyncio.Semaphore(concurrency)

    total_servers = len(TOOL_SERVERS) + len(SOFTWARE_APPS)
    print(f"light-servers smoke test")
    print(f"host={host}  timeout={timeout}s  concurrency={concurrency}")
    print(f"probing {len(TOOL_SERVERS)} tool servers + {len(SOFTWARE_APPS)} software apps = {total_servers} total\n")

    print("Probing tool servers...")
    tool_results: List[Result] = list(await asyncio.gather(*[
        probe_tool_server(host, s, timeout, sem) for s in TOOL_SERVERS
    ]))

    print("Probing LightSystem...")
    ls_result, ls_session_id = await probe_lightsystem(host, timeout, sem)

    if not ls_session_id:
        print("WARNING: LightSystem login failed - software apps will all fail login.")

    print(f"Probing {len(SOFTWARE_APPS) - 1} software apps (excluding LightSystem)...")
    sw_results: List[Result] = list(await asyncio.gather(*[
        probe_software_app(host, app, ls_session_id, timeout, sem)
        for app in SOFTWARE_APPS if app.name != "LightSystem"
    ]))

    all_results = tool_results + [ls_result] + sw_results
    print_results(all_results, verbose=args.verbose)
    return 0 if not any(not r.passed for r in all_results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test all light-server tool servers and software apps."
    )
    parser.add_argument("--host",        default="localhost",
                        help="Hostname where servers are running (default: localhost)")
    parser.add_argument("--timeout",     type=float, default=30.0,
                        help="Per-server timeout in seconds (default: 30)")
    parser.add_argument("--concurrency", type=int,   default=20,
                        help="Max simultaneous connections (default: 20)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print probe steps for each server")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
