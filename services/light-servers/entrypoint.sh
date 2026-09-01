#!/bin/bash
set -e

export PYTHONPATH=/app:${PYTHONPATH}
export WORKSPACE_ROOT=${WORKSPACE_ROOT:-/workspace}
export COMPLEXMCP_SEED=${COMPLEXMCP_SEED:-42}

mkdir -p "$WORKSPACE_ROOT"

# Corpus-additions boot gate (invariant I2). Every ambiguity in the additions
# layer fails HERE, before a single server binds a port -- a failure raised
# later, inside a login call, would become a tool error the agent swallows
# while the run continues against the wrong world. Exits non-zero and names
# the offending app and key. No-op when COMPLEXMCP_CORPUS_ADDITIONS is unset.
python -m software.utils.corpus_boot

PIDS=()

cleanup() {
    for PID in "${PIDS[@]}"; do
        kill "$PID" 2>/dev/null || true
    done
    wait
    exit 0
}

trap cleanup INT TERM

declare -A SERVER_CMDS
SERVER_CMDS["math"]="fastmcp run /app/servers/math/app.py --transport http --host 0.0.0.0 --port 8000"
SERVER_CMDS["unit"]="python3 -m servers.unit.app --host 0.0.0.0 --port 8001"
SERVER_CMDS["osint"]="fastmcp run /app/servers/osint/app.py --transport http --host 0.0.0.0 --port 8002"
SERVER_CMDS["time"]="fastmcp run /app/servers/time/app.py --transport http --host 0.0.0.0 --port 8003"
SERVER_CMDS["lang"]="fastmcp run /app/servers/lang/app.py --transport http --host 0.0.0.0 --port 8004"
SERVER_CMDS["crypto"]="fastmcp run /app/servers/crypto/app.py --transport http --host 0.0.0.0 --port 8005"
SERVER_CMDS["graphs"]="fastmcp run /app/servers/graphs/app.py --transport http --host 0.0.0.0 --port 8006"
SERVER_CMDS["chem"]="fastmcp run /app/servers/chem/app.py --transport http --host 0.0.0.0 --port 8007"
SERVER_CMDS["url"]="fastmcp run /app/servers/url/app.py --transport http --host 0.0.0.0 --port 8013"
SERVER_CMDS["csv_server"]="fastmcp run /app/servers/csv_server/app.py --transport http --host 0.0.0.0 --port 8014"
SERVER_CMDS["json_server"]="fastmcp run /app/servers/json_server/app.py --transport http --host 0.0.0.0 --port 8015"
SERVER_CMDS["diff"]="fastmcp run /app/servers/diff/app.py --transport http --host 0.0.0.0 --port 8016"
SERVER_CMDS["hash"]="fastmcp run /app/servers/hash/app.py --transport http --host 0.0.0.0 --port 8017"
SERVER_CMDS["color"]="fastmcp run /app/servers/color/app.py --transport http --host 0.0.0.0 --port 8018"
SERVER_CMDS["encoding"]="fastmcp run /app/servers/encoding/app.py --transport http --host 0.0.0.0 --port 8019"
SERVER_CMDS["barcode"]="fastmcp run /app/servers/barcode/app.py --transport http --host 0.0.0.0 --port 8020"
SERVER_CMDS["calendar_math"]="fastmcp run /app/servers/calendar_math/app.py --transport http --host 0.0.0.0 --port 8021"
SERVER_CMDS["currency"]="fastmcp run /app/servers/currency/app.py --transport http --host 0.0.0.0 --port 8022"
SERVER_CMDS["random_server"]="fastmcp run /app/servers/random_server/app.py --transport http --host 0.0.0.0 --port 8023"
SERVER_CMDS["template"]="fastmcp run /app/servers/template/app.py --transport http --host 0.0.0.0 --port 8024"
SERVER_CMDS["filesystem"]="fastmcp run /app/filesystem_server.py --transport http --host 0.0.0.0 --port 8090"
SERVER_CMDS["LightSystem"]="fastmcp run /app/software/LightSystem/app.py --transport http --host 0.0.0.0 --port 9000"
SERVER_CMDS["LightTalk"]="fastmcp run /app/software/LightTalk/app.py --transport http --host 0.0.0.0 --port 9001"
SERVER_CMDS["LightShop"]="fastmcp run /app/software/LightShop/app.py --transport http --host 0.0.0.0 --port 9002"
SERVER_CMDS["LightWeather"]="fastmcp run /app/software/LightWeather/app.py --transport http --host 0.0.0.0 --port 9003"
SERVER_CMDS["LightFlight"]="fastmcp run /app/software/LightFlight/app.py --transport http --host 0.0.0.0 --port 9004"
SERVER_CMDS["LightStock"]="fastmcp run /app/software/LightStock/app.py --transport http --host 0.0.0.0 --port 9005"
SERVER_CMDS["LightNews"]="fastmcp run /app/software/LightNews/app.py --transport http --host 0.0.0.0 --port 9006"
SERVER_CMDS["LightMail"]="fastmcp run /app/software/LightMail/app.py --transport http --host 0.0.0.0 --port 9007"
SERVER_CMDS["LightCalendar"]="fastmcp run /app/software/LightCalendar/app.py --transport http --host 0.0.0.0 --port 9008"
SERVER_CMDS["LightTasks"]="fastmcp run /app/software/LightTasks/app.py --transport http --host 0.0.0.0 --port 9014"
SERVER_CMDS["LightNotes"]="fastmcp run /app/software/LightNotes/app.py --transport http --host 0.0.0.0 --port 9015"
SERVER_CMDS["LightMeet"]="fastmcp run /app/software/LightMeet/app.py --transport http --host 0.0.0.0 --port 9016"
SERVER_CMDS["LightCRM"]="fastmcp run /app/software/LightCRM/app.py --transport http --host 0.0.0.0 --port 9017"
SERVER_CMDS["LightHR"]="fastmcp run /app/software/LightHR/app.py --transport http --host 0.0.0.0 --port 9018"
SERVER_CMDS["LightIssues"]="fastmcp run /app/software/LightIssues/app.py --transport http --host 0.0.0.0 --port 9019"
SERVER_CMDS["LightBudget"]="fastmcp run /app/software/LightBudget/app.py --transport http --host 0.0.0.0 --port 9020"
SERVER_CMDS["LightWallet"]="fastmcp run /app/software/LightWallet/app.py --transport http --host 0.0.0.0 --port 9021"
SERVER_CMDS["LightTax"]="fastmcp run /app/software/LightTax/app.py --transport http --host 0.0.0.0 --port 9022"
SERVER_CMDS["LightAuction"]="fastmcp run /app/software/LightAuction/app.py --transport http --host 0.0.0.0 --port 9023"
SERVER_CMDS["LightSubscription"]="fastmcp run /app/software/LightSubscription/app.py --transport http --host 0.0.0.0 --port 9024"
SERVER_CMDS["LightRide"]="fastmcp run /app/software/LightRide/app.py --transport http --host 0.0.0.0 --port 9025"
SERVER_CMDS["LightHotel"]="fastmcp run /app/software/LightHotel/app.py --transport http --host 0.0.0.0 --port 9026"
SERVER_CMDS["LightRental"]="fastmcp run /app/software/LightRental/app.py --transport http --host 0.0.0.0 --port 9027"
SERVER_CMDS["LightFood"]="fastmcp run /app/software/LightFood/app.py --transport http --host 0.0.0.0 --port 9028"
SERVER_CMDS["LightVideo"]="fastmcp run /app/software/LightVideo/app.py --transport http --host 0.0.0.0 --port 9029"
SERVER_CMDS["LightPodcast"]="fastmcp run /app/software/LightPodcast/app.py --transport http --host 0.0.0.0 --port 9030"
SERVER_CMDS["LightPhoto"]="fastmcp run /app/software/LightPhoto/app.py --transport http --host 0.0.0.0 --port 9031"
SERVER_CMDS["LightRead"]="fastmcp run /app/software/LightRead/app.py --transport http --host 0.0.0.0 --port 9032"
SERVER_CMDS["LightForum"]="fastmcp run /app/software/LightForum/app.py --transport http --host 0.0.0.0 --port 9033"
SERVER_CMDS["LightHome"]="fastmcp run /app/software/LightHome/app.py --transport http --host 0.0.0.0 --port 9034"
SERVER_CMDS["LightSecurity"]="fastmcp run /app/software/LightSecurity/app.py --transport http --host 0.0.0.0 --port 9035"
SERVER_CMDS["LightEnergy"]="fastmcp run /app/software/LightEnergy/app.py --transport http --host 0.0.0.0 --port 9036"
SERVER_CMDS["LightFitness"]="fastmcp run /app/software/LightFitness/app.py --transport http --host 0.0.0.0 --port 9037"
SERVER_CMDS["LightMed"]="fastmcp run /app/software/LightMed/app.py --transport http --host 0.0.0.0 --port 9038"
SERVER_CMDS["LightLearn"]="fastmcp run /app/software/LightLearn/app.py --transport http --host 0.0.0.0 --port 9039"
SERVER_CMDS["LightVault"]="fastmcp run /app/software/LightVault/app.py --transport http --host 0.0.0.0 --port 9040"
SERVER_CMDS["LightDrive"]="fastmcp run /app/software/LightDrive/app.py --transport http --host 0.0.0.0 --port 9041"
SERVER_CMDS["LightSign"]="fastmcp run /app/software/LightSign/app.py --transport http --host 0.0.0.0 --port 9042"
SERVER_CMDS["LightGame"]="fastmcp run /app/software/LightGame/app.py --transport http --host 0.0.0.0 --port 9043"
SERVER_CMDS["LightActiveCampaign"]="fastmcp run /app/software/LightActiveCampaign/app.py --transport http --host 0.0.0.0 --port 9044"
SERVER_CMDS["LightAirbnb"]="fastmcp run /app/software/LightAirbnb/app.py --transport http --host 0.0.0.0 --port 9045"
SERVER_CMDS["LightAirtable"]="fastmcp run /app/software/LightAirtable/app.py --transport http --host 0.0.0.0 --port 9046"
SERVER_CMDS["LightAlgolia"]="fastmcp run /app/software/LightAlgolia/app.py --transport http --host 0.0.0.0 --port 9047"
SERVER_CMDS["LightAlpaca"]="fastmcp run /app/software/LightAlpaca/app.py --transport http --host 0.0.0.0 --port 9048"
SERVER_CMDS["LightAmadeus"]="fastmcp run /app/software/LightAmadeus/app.py --transport http --host 0.0.0.0 --port 9049"
SERVER_CMDS["LightAmazonSeller"]="fastmcp run /app/software/LightAmazonSeller/app.py --transport http --host 0.0.0.0 --port 9050"
SERVER_CMDS["LightAmplitude"]="fastmcp run /app/software/LightAmplitude/app.py --transport http --host 0.0.0.0 --port 9051"
SERVER_CMDS["LightAsana"]="fastmcp run /app/software/LightAsana/app.py --transport http --host 0.0.0.0 --port 9052"
SERVER_CMDS["LightBambooHR"]="fastmcp run /app/software/LightBambooHR/app.py --transport http --host 0.0.0.0 --port 9053"
SERVER_CMDS["LightBigCommerce"]="fastmcp run /app/software/LightBigCommerce/app.py --transport http --host 0.0.0.0 --port 9054"
SERVER_CMDS["LightBinance"]="fastmcp run /app/software/LightBinance/app.py --transport http --host 0.0.0.0 --port 9055"
SERVER_CMDS["LightBox"]="fastmcp run /app/software/LightBox/app.py --transport http --host 0.0.0.0 --port 9056"
SERVER_CMDS["LightCalendly"]="fastmcp run /app/software/LightCalendly/app.py --transport http --host 0.0.0.0 --port 9057"
SERVER_CMDS["LightCloudflare"]="fastmcp run /app/software/LightCloudflare/app.py --transport http --host 0.0.0.0 --port 9058"
SERVER_CMDS["LightCoinbase"]="fastmcp run /app/software/LightCoinbase/app.py --transport http --host 0.0.0.0 --port 9059"
SERVER_CMDS["LightConfluence"]="fastmcp run /app/software/LightConfluence/app.py --transport http --host 0.0.0.0 --port 9060"
SERVER_CMDS["LightContentful"]="fastmcp run /app/software/LightContentful/app.py --transport http --host 0.0.0.0 --port 9061"
SERVER_CMDS["LightDatadog"]="fastmcp run /app/software/LightDatadog/app.py --transport http --host 0.0.0.0 --port 9062"
SERVER_CMDS["LightDiscord"]="fastmcp run /app/software/LightDiscord/app.py --transport http --host 0.0.0.0 --port 9063"
SERVER_CMDS["LightDocuSign"]="fastmcp run /app/software/LightDocuSign/app.py --transport http --host 0.0.0.0 --port 9064"
SERVER_CMDS["LightDoorDash"]="fastmcp run /app/software/LightDoorDash/app.py --transport http --host 0.0.0.0 --port 9065"
SERVER_CMDS["LightDropbox"]="fastmcp run /app/software/LightDropbox/app.py --transport http --host 0.0.0.0 --port 9066"
SERVER_CMDS["LightEtsy"]="fastmcp run /app/software/LightEtsy/app.py --transport http --host 0.0.0.0 --port 9067"
SERVER_CMDS["LightEventbrite"]="fastmcp run /app/software/LightEventbrite/app.py --transport http --host 0.0.0.0 --port 9068"
SERVER_CMDS["LightFedEx"]="fastmcp run /app/software/LightFedEx/app.py --transport http --host 0.0.0.0 --port 9069"
SERVER_CMDS["LightFigma"]="fastmcp run /app/software/LightFigma/app.py --transport http --host 0.0.0.0 --port 9070"
SERVER_CMDS["LightFreshdesk"]="fastmcp run /app/software/LightFreshdesk/app.py --transport http --host 0.0.0.0 --port 9071"
SERVER_CMDS["LightGithub"]="fastmcp run /app/software/LightGithub/app.py --transport http --host 0.0.0.0 --port 9072"
SERVER_CMDS["LightGitlab"]="fastmcp run /app/software/LightGitlab/app.py --transport http --host 0.0.0.0 --port 9073"
SERVER_CMDS["LightGmail"]="fastmcp run /app/software/LightGmail/app.py --transport http --host 0.0.0.0 --port 9074"
SERVER_CMDS["LightGoogleAnalytics"]="fastmcp run /app/software/LightGoogleAnalytics/app.py --transport http --host 0.0.0.0 --port 9075"
SERVER_CMDS["LightGoogleCalendar"]="fastmcp run /app/software/LightGoogleCalendar/app.py --transport http --host 0.0.0.0 --port 9076"
SERVER_CMDS["LightGoogleClassroom"]="fastmcp run /app/software/LightGoogleClassroom/app.py --transport http --host 0.0.0.0 --port 9077"
SERVER_CMDS["LightGoogleDrive"]="fastmcp run /app/software/LightGoogleDrive/app.py --transport http --host 0.0.0.0 --port 9078"
SERVER_CMDS["LightGoogleMaps"]="fastmcp run /app/software/LightGoogleMaps/app.py --transport http --host 0.0.0.0 --port 9079"
SERVER_CMDS["LightGreenhouse"]="fastmcp run /app/software/LightGreenhouse/app.py --transport http --host 0.0.0.0 --port 9080"
SERVER_CMDS["LightGusto"]="fastmcp run /app/software/LightGusto/app.py --transport http --host 0.0.0.0 --port 9081"
SERVER_CMDS["LightHubspot"]="fastmcp run /app/software/LightHubspot/app.py --transport http --host 0.0.0.0 --port 9082"
SERVER_CMDS["LightInstacart"]="fastmcp run /app/software/LightInstacart/app.py --transport http --host 0.0.0.0 --port 9083"
SERVER_CMDS["LightInstagram"]="fastmcp run /app/software/LightInstagram/app.py --transport http --host 0.0.0.0 --port 9084"
SERVER_CMDS["LightIntercom"]="fastmcp run /app/software/LightIntercom/app.py --transport http --host 0.0.0.0 --port 9085"
SERVER_CMDS["LightJira"]="fastmcp run /app/software/LightJira/app.py --transport http --host 0.0.0.0 --port 9086"
SERVER_CMDS["LightKlaviyo"]="fastmcp run /app/software/LightKlaviyo/app.py --transport http --host 0.0.0.0 --port 9087"
SERVER_CMDS["LightKraken"]="fastmcp run /app/software/LightKraken/app.py --transport http --host 0.0.0.0 --port 9088"
SERVER_CMDS["LightKubernetes"]="fastmcp run /app/software/LightKubernetes/app.py --transport http --host 0.0.0.0 --port 9089"
SERVER_CMDS["LightLinear"]="fastmcp run /app/software/LightLinear/app.py --transport http --host 0.0.0.0 --port 9090"
SERVER_CMDS["LightLinkedIn"]="fastmcp run /app/software/LightLinkedIn/app.py --transport http --host 0.0.0.0 --port 9091"
SERVER_CMDS["LightMailchimp"]="fastmcp run /app/software/LightMailchimp/app.py --transport http --host 0.0.0.0 --port 9092"
SERVER_CMDS["LightMailgun"]="fastmcp run /app/software/LightMailgun/app.py --transport http --host 0.0.0.0 --port 9093"
SERVER_CMDS["LightMicrosoftTeams"]="fastmcp run /app/software/LightMicrosoftTeams/app.py --transport http --host 0.0.0.0 --port 9094"
SERVER_CMDS["LightMixpanel"]="fastmcp run /app/software/LightMixpanel/app.py --transport http --host 0.0.0.0 --port 9095"
SERVER_CMDS["LightMonday"]="fastmcp run /app/software/LightMonday/app.py --transport http --host 0.0.0.0 --port 9096"
SERVER_CMDS["LightMyFitnessPal"]="fastmcp run /app/software/LightMyFitnessPal/app.py --transport http --host 0.0.0.0 --port 9097"
SERVER_CMDS["LightNASA"]="fastmcp run /app/software/LightNASA/app.py --transport http --host 0.0.0.0 --port 9098"
SERVER_CMDS["LightNotion"]="fastmcp run /app/software/LightNotion/app.py --transport http --host 0.0.0.0 --port 9099"
SERVER_CMDS["LightObsidian"]="fastmcp run /app/software/LightObsidian/app.py --transport http --host 0.0.0.0 --port 9100"
SERVER_CMDS["LightOkta"]="fastmcp run /app/software/LightOkta/app.py --transport http --host 0.0.0.0 --port 9101"
SERVER_CMDS["LightOpenLibrary"]="fastmcp run /app/software/LightOpenLibrary/app.py --transport http --host 0.0.0.0 --port 9102"
SERVER_CMDS["LightOpenWeather"]="fastmcp run /app/software/LightOpenWeather/app.py --transport http --host 0.0.0.0 --port 9103"
SERVER_CMDS["LightOutlook"]="fastmcp run /app/software/LightOutlook/app.py --transport http --host 0.0.0.0 --port 9104"
SERVER_CMDS["LightPagerDuty"]="fastmcp run /app/software/LightPagerDuty/app.py --transport http --host 0.0.0.0 --port 9105"
SERVER_CMDS["LightPayPal"]="fastmcp run /app/software/LightPayPal/app.py --transport http --host 0.0.0.0 --port 9106"
SERVER_CMDS["LightPinterest"]="fastmcp run /app/software/LightPinterest/app.py --transport http --host 0.0.0.0 --port 9107"
SERVER_CMDS["LightPlaid"]="fastmcp run /app/software/LightPlaid/app.py --transport http --host 0.0.0.0 --port 9108"
SERVER_CMDS["LightPostHog"]="fastmcp run /app/software/LightPostHog/app.py --transport http --host 0.0.0.0 --port 9109"
SERVER_CMDS["LightQuickBooks"]="fastmcp run /app/software/LightQuickBooks/app.py --transport http --host 0.0.0.0 --port 9110"
SERVER_CMDS["LightReddit"]="fastmcp run /app/software/LightReddit/app.py --transport http --host 0.0.0.0 --port 9111"
SERVER_CMDS["LightRing"]="fastmcp run /app/software/LightRing/app.py --transport http --host 0.0.0.0 --port 9112"
SERVER_CMDS["LightSalesforce"]="fastmcp run /app/software/LightSalesforce/app.py --transport http --host 0.0.0.0 --port 9113"
SERVER_CMDS["LightSegment"]="fastmcp run /app/software/LightSegment/app.py --transport http --host 0.0.0.0 --port 9114"
SERVER_CMDS["LightSendGrid"]="fastmcp run /app/software/LightSendGrid/app.py --transport http --host 0.0.0.0 --port 9115"
SERVER_CMDS["LightSentry"]="fastmcp run /app/software/LightSentry/app.py --transport http --host 0.0.0.0 --port 9116"
SERVER_CMDS["LightServiceNow"]="fastmcp run /app/software/LightServiceNow/app.py --transport http --host 0.0.0.0 --port 9117"
SERVER_CMDS["LightShippo"]="fastmcp run /app/software/LightShippo/app.py --transport http --host 0.0.0.0 --port 9118"
SERVER_CMDS["LightSlack"]="fastmcp run /app/software/LightSlack/app.py --transport http --host 0.0.0.0 --port 9119"
SERVER_CMDS["LightSpotify"]="fastmcp run /app/software/LightSpotify/app.py --transport http --host 0.0.0.0 --port 9120"
SERVER_CMDS["LightSquare"]="fastmcp run /app/software/LightSquare/app.py --transport http --host 0.0.0.0 --port 9121"
SERVER_CMDS["LightStrava"]="fastmcp run /app/software/LightStrava/app.py --transport http --host 0.0.0.0 --port 9122"
SERVER_CMDS["LightStripe"]="fastmcp run /app/software/LightStripe/app.py --transport http --host 0.0.0.0 --port 9123"
SERVER_CMDS["LightTMDB"]="fastmcp run /app/software/LightTMDB/app.py --transport http --host 0.0.0.0 --port 9124"
SERVER_CMDS["LightTelegram"]="fastmcp run /app/software/LightTelegram/app.py --transport http --host 0.0.0.0 --port 9125"
SERVER_CMDS["LightTicketmaster"]="fastmcp run /app/software/LightTicketmaster/app.py --transport http --host 0.0.0.0 --port 9126"
SERVER_CMDS["LightTrello"]="fastmcp run /app/software/LightTrello/app.py --transport http --host 0.0.0.0 --port 9127"
SERVER_CMDS["LightTwilio"]="fastmcp run /app/software/LightTwilio/app.py --transport http --host 0.0.0.0 --port 9128"
SERVER_CMDS["LightTwitch"]="fastmcp run /app/software/LightTwitch/app.py --transport http --host 0.0.0.0 --port 9129"
SERVER_CMDS["LightTwitter"]="fastmcp run /app/software/LightTwitter/app.py --transport http --host 0.0.0.0 --port 9130"
SERVER_CMDS["LightTypeform"]="fastmcp run /app/software/LightTypeform/app.py --transport http --host 0.0.0.0 --port 9131"
SERVER_CMDS["LightUPS"]="fastmcp run /app/software/LightUPS/app.py --transport http --host 0.0.0.0 --port 9132"
SERVER_CMDS["LightUber"]="fastmcp run /app/software/LightUber/app.py --transport http --host 0.0.0.0 --port 9133"
SERVER_CMDS["LightVimeo"]="fastmcp run /app/software/LightVimeo/app.py --transport http --host 0.0.0.0 --port 9134"
SERVER_CMDS["LightWebflow"]="fastmcp run /app/software/LightWebflow/app.py --transport http --host 0.0.0.0 --port 9135"
SERVER_CMDS["LightWhatsApp"]="fastmcp run /app/software/LightWhatsApp/app.py --transport http --host 0.0.0.0 --port 9136"
SERVER_CMDS["LightWooCommerce"]="fastmcp run /app/software/LightWooCommerce/app.py --transport http --host 0.0.0.0 --port 9137"
SERVER_CMDS["LightWordPress"]="fastmcp run /app/software/LightWordPress/app.py --transport http --host 0.0.0.0 --port 9138"
SERVER_CMDS["LightXero"]="fastmcp run /app/software/LightXero/app.py --transport http --host 0.0.0.0 --port 9139"
SERVER_CMDS["LightYelp"]="fastmcp run /app/software/LightYelp/app.py --transport http --host 0.0.0.0 --port 9140"
SERVER_CMDS["LightYouTube"]="fastmcp run /app/software/LightYouTube/app.py --transport http --host 0.0.0.0 --port 9141"
SERVER_CMDS["LightZendesk"]="fastmcp run /app/software/LightZendesk/app.py --transport http --host 0.0.0.0 --port 9142"
SERVER_CMDS["LightZillow"]="fastmcp run /app/software/LightZillow/app.py --transport http --host 0.0.0.0 --port 9143"
SERVER_CMDS["LightZoom"]="fastmcp run /app/software/LightZoom/app.py --transport http --host 0.0.0.0 --port 9144"

if [ -z "${ENABLED_SERVERS:-}" ]; then
    echo "Starting all ${#SERVER_CMDS[@]} servers..."
    for name in "${!SERVER_CMDS[@]}"; do
        eval "${SERVER_CMDS[$name]}" &
        PIDS+=($!)
    done
else
    echo "Starting servers: ${ENABLED_SERVERS}"
    IFS=',' read -ra SERVERS <<< "$ENABLED_SERVERS"
    for name in "${SERVERS[@]}"; do
        name="${name// /}"
        cmd="${SERVER_CMDS[$name]:-}"
        if [ -z "$cmd" ]; then
            echo "WARNING: Unknown server '$name', skipping"
            continue
        fi
        echo "Starting $name..."
        eval "$cmd" &
        PIDS+=($!)
    done
fi

echo "Servers started. Waiting..."
wait
