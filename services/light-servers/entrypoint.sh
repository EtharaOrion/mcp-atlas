#!/bin/bash
set -e

export PYTHONPATH=/app:${PYTHONPATH}
export WORKSPACE_ROOT=${WORKSPACE_ROOT:-/workspace}
export COMPLEXMCP_SEED=${COMPLEXMCP_SEED:-42}

mkdir -p "$WORKSPACE_ROOT"

PIDS=()

cleanup() {
    echo "Shutting down all servers..."
    for PID in "${PIDS[@]}"; do
        kill "$PID" 2>/dev/null || true
    done
    wait
    exit 0
}

trap cleanup INT TERM

fastmcp run /app/servers/math/app.py --transport http --host 0.0.0.0 --port 8000 &
PIDS+=($!)
python3 -m servers.unit.app --host 0.0.0.0 --port 8001 &
PIDS+=($!)
fastmcp run /app/servers/osint/app.py --transport http --host 0.0.0.0 --port 8002 &
PIDS+=($!)
fastmcp run /app/servers/time/app.py --transport http --host 0.0.0.0 --port 8003 &
PIDS+=($!)
fastmcp run /app/servers/lang/app.py --transport http --host 0.0.0.0 --port 8004 &
PIDS+=($!)
fastmcp run /app/servers/crypto/app.py --transport http --host 0.0.0.0 --port 8005 &
PIDS+=($!)
fastmcp run /app/servers/graphs/app.py --transport http --host 0.0.0.0 --port 8006 &
PIDS+=($!)
fastmcp run /app/servers/chem/app.py --transport http --host 0.0.0.0 --port 8007 &
PIDS+=($!)
fastmcp run /app/servers/url/app.py --transport http --host 0.0.0.0 --port 8013 &
PIDS+=($!)
fastmcp run /app/servers/csv_server/app.py --transport http --host 0.0.0.0 --port 8014 &
PIDS+=($!)
fastmcp run /app/servers/json_server/app.py --transport http --host 0.0.0.0 --port 8015 &
PIDS+=($!)
fastmcp run /app/servers/diff/app.py --transport http --host 0.0.0.0 --port 8016 &
PIDS+=($!)
fastmcp run /app/servers/hash/app.py --transport http --host 0.0.0.0 --port 8017 &
PIDS+=($!)
fastmcp run /app/servers/color/app.py --transport http --host 0.0.0.0 --port 8018 &
PIDS+=($!)
fastmcp run /app/servers/encoding/app.py --transport http --host 0.0.0.0 --port 8019 &
PIDS+=($!)
fastmcp run /app/servers/barcode/app.py --transport http --host 0.0.0.0 --port 8020 &
PIDS+=($!)
fastmcp run /app/servers/calendar_math/app.py --transport http --host 0.0.0.0 --port 8021 &
PIDS+=($!)
fastmcp run /app/servers/currency/app.py --transport http --host 0.0.0.0 --port 8022 &
PIDS+=($!)
fastmcp run /app/servers/random_server/app.py --transport http --host 0.0.0.0 --port 8023 &
PIDS+=($!)
fastmcp run /app/servers/template/app.py --transport http --host 0.0.0.0 --port 8024 &
PIDS+=($!)

fastmcp run /app/filesystem_server.py --transport http --host 0.0.0.0 --port 8090 &
PIDS+=($!)

fastmcp run /app/software/LightSystem/app.py --transport http --host 0.0.0.0 --port 9000 &
PIDS+=($!)
fastmcp run /app/software/LightTalk/app.py --transport http --host 0.0.0.0 --port 9001 &
PIDS+=($!)
fastmcp run /app/software/LightShop/app.py --transport http --host 0.0.0.0 --port 9002 &
PIDS+=($!)
fastmcp run /app/software/LightWeather/app.py --transport http --host 0.0.0.0 --port 9003 &
PIDS+=($!)
fastmcp run /app/software/LightFlight/app.py --transport http --host 0.0.0.0 --port 9004 &
PIDS+=($!)
fastmcp run /app/software/LightStock/app.py --transport http --host 0.0.0.0 --port 9005 &
PIDS+=($!)
fastmcp run /app/software/LightNews/app.py --transport http --host 0.0.0.0 --port 9006 &
PIDS+=($!)
fastmcp run /app/software/LightMail/app.py --transport http --host 0.0.0.0 --port 9007 &
PIDS+=($!)
fastmcp run /app/software/LightCalendar/app.py --transport http --host 0.0.0.0 --port 9008 &
PIDS+=($!)
fastmcp run /app/software/LightTasks/app.py --transport http --host 0.0.0.0 --port 9014 &
PIDS+=($!)
fastmcp run /app/software/LightNotes/app.py --transport http --host 0.0.0.0 --port 9015 &
PIDS+=($!)
fastmcp run /app/software/LightMeet/app.py --transport http --host 0.0.0.0 --port 9016 &
PIDS+=($!)
fastmcp run /app/software/LightCRM/app.py --transport http --host 0.0.0.0 --port 9017 &
PIDS+=($!)
fastmcp run /app/software/LightHR/app.py --transport http --host 0.0.0.0 --port 9018 &
PIDS+=($!)
fastmcp run /app/software/LightIssues/app.py --transport http --host 0.0.0.0 --port 9019 &
PIDS+=($!)
fastmcp run /app/software/LightBudget/app.py --transport http --host 0.0.0.0 --port 9020 &
PIDS+=($!)
fastmcp run /app/software/LightWallet/app.py --transport http --host 0.0.0.0 --port 9021 &
PIDS+=($!)
fastmcp run /app/software/LightTax/app.py --transport http --host 0.0.0.0 --port 9022 &
PIDS+=($!)
fastmcp run /app/software/LightAuction/app.py --transport http --host 0.0.0.0 --port 9023 &
PIDS+=($!)
fastmcp run /app/software/LightSubscription/app.py --transport http --host 0.0.0.0 --port 9024 &
PIDS+=($!)
fastmcp run /app/software/LightRide/app.py --transport http --host 0.0.0.0 --port 9025 &
PIDS+=($!)
fastmcp run /app/software/LightHotel/app.py --transport http --host 0.0.0.0 --port 9026 &
PIDS+=($!)
fastmcp run /app/software/LightRental/app.py --transport http --host 0.0.0.0 --port 9027 &
PIDS+=($!)
fastmcp run /app/software/LightFood/app.py --transport http --host 0.0.0.0 --port 9028 &
PIDS+=($!)
fastmcp run /app/software/LightVideo/app.py --transport http --host 0.0.0.0 --port 9029 &
PIDS+=($!)
fastmcp run /app/software/LightPodcast/app.py --transport http --host 0.0.0.0 --port 9030 &
PIDS+=($!)
fastmcp run /app/software/LightPhoto/app.py --transport http --host 0.0.0.0 --port 9031 &
PIDS+=($!)
fastmcp run /app/software/LightRead/app.py --transport http --host 0.0.0.0 --port 9032 &
PIDS+=($!)
fastmcp run /app/software/LightForum/app.py --transport http --host 0.0.0.0 --port 9033 &
PIDS+=($!)
fastmcp run /app/software/LightHome/app.py --transport http --host 0.0.0.0 --port 9034 &
PIDS+=($!)
fastmcp run /app/software/LightSecurity/app.py --transport http --host 0.0.0.0 --port 9035 &
PIDS+=($!)
fastmcp run /app/software/LightEnergy/app.py --transport http --host 0.0.0.0 --port 9036 &
PIDS+=($!)
fastmcp run /app/software/LightFitness/app.py --transport http --host 0.0.0.0 --port 9037 &
PIDS+=($!)
fastmcp run /app/software/LightMed/app.py --transport http --host 0.0.0.0 --port 9038 &
PIDS+=($!)
fastmcp run /app/software/LightLearn/app.py --transport http --host 0.0.0.0 --port 9039 &
PIDS+=($!)
fastmcp run /app/software/LightVault/app.py --transport http --host 0.0.0.0 --port 9040 &
PIDS+=($!)
fastmcp run /app/software/LightDrive/app.py --transport http --host 0.0.0.0 --port 9041 &
PIDS+=($!)
fastmcp run /app/software/LightSign/app.py --transport http --host 0.0.0.0 --port 9042 &
PIDS+=($!)
fastmcp run /app/software/LightGame/app.py --transport http --host 0.0.0.0 --port 9043 &
PIDS+=($!)
fastmcp run /app/software/LightActiveCampaign/app.py --transport http --host 0.0.0.0 --port 9044 &
PIDS+=($!)
fastmcp run /app/software/LightAirbnb/app.py --transport http --host 0.0.0.0 --port 9045 &
PIDS+=($!)
fastmcp run /app/software/LightAirtable/app.py --transport http --host 0.0.0.0 --port 9046 &
PIDS+=($!)
fastmcp run /app/software/LightAlgolia/app.py --transport http --host 0.0.0.0 --port 9047 &
PIDS+=($!)
fastmcp run /app/software/LightAlpaca/app.py --transport http --host 0.0.0.0 --port 9048 &
PIDS+=($!)
fastmcp run /app/software/LightAmadeus/app.py --transport http --host 0.0.0.0 --port 9049 &
PIDS+=($!)
fastmcp run /app/software/LightAmazonSeller/app.py --transport http --host 0.0.0.0 --port 9050 &
PIDS+=($!)
fastmcp run /app/software/LightAmplitude/app.py --transport http --host 0.0.0.0 --port 9051 &
PIDS+=($!)
fastmcp run /app/software/LightAsana/app.py --transport http --host 0.0.0.0 --port 9052 &
PIDS+=($!)
fastmcp run /app/software/LightBambooHR/app.py --transport http --host 0.0.0.0 --port 9053 &
PIDS+=($!)
fastmcp run /app/software/LightBigCommerce/app.py --transport http --host 0.0.0.0 --port 9054 &
PIDS+=($!)
fastmcp run /app/software/LightBinance/app.py --transport http --host 0.0.0.0 --port 9055 &
PIDS+=($!)
fastmcp run /app/software/LightBox/app.py --transport http --host 0.0.0.0 --port 9056 &
PIDS+=($!)
fastmcp run /app/software/LightCalendly/app.py --transport http --host 0.0.0.0 --port 9057 &
PIDS+=($!)
fastmcp run /app/software/LightCloudflare/app.py --transport http --host 0.0.0.0 --port 9058 &
PIDS+=($!)
fastmcp run /app/software/LightCoinbase/app.py --transport http --host 0.0.0.0 --port 9059 &
PIDS+=($!)
fastmcp run /app/software/LightConfluence/app.py --transport http --host 0.0.0.0 --port 9060 &
PIDS+=($!)
fastmcp run /app/software/LightContentful/app.py --transport http --host 0.0.0.0 --port 9061 &
PIDS+=($!)
fastmcp run /app/software/LightDatadog/app.py --transport http --host 0.0.0.0 --port 9062 &
PIDS+=($!)
fastmcp run /app/software/LightDiscord/app.py --transport http --host 0.0.0.0 --port 9063 &
PIDS+=($!)
fastmcp run /app/software/LightDocuSign/app.py --transport http --host 0.0.0.0 --port 9064 &
PIDS+=($!)
fastmcp run /app/software/LightDoorDash/app.py --transport http --host 0.0.0.0 --port 9065 &
PIDS+=($!)
fastmcp run /app/software/LightDropbox/app.py --transport http --host 0.0.0.0 --port 9066 &
PIDS+=($!)
fastmcp run /app/software/LightEtsy/app.py --transport http --host 0.0.0.0 --port 9067 &
PIDS+=($!)
fastmcp run /app/software/LightEventbrite/app.py --transport http --host 0.0.0.0 --port 9068 &
PIDS+=($!)
fastmcp run /app/software/LightFedEx/app.py --transport http --host 0.0.0.0 --port 9069 &
PIDS+=($!)
fastmcp run /app/software/LightFigma/app.py --transport http --host 0.0.0.0 --port 9070 &
PIDS+=($!)
fastmcp run /app/software/LightFreshdesk/app.py --transport http --host 0.0.0.0 --port 9071 &
PIDS+=($!)
fastmcp run /app/software/LightGithub/app.py --transport http --host 0.0.0.0 --port 9072 &
PIDS+=($!)
fastmcp run /app/software/LightGitlab/app.py --transport http --host 0.0.0.0 --port 9073 &
PIDS+=($!)
fastmcp run /app/software/LightGmail/app.py --transport http --host 0.0.0.0 --port 9074 &
PIDS+=($!)
fastmcp run /app/software/LightGoogleAnalytics/app.py --transport http --host 0.0.0.0 --port 9075 &
PIDS+=($!)
fastmcp run /app/software/LightGoogleCalendar/app.py --transport http --host 0.0.0.0 --port 9076 &
PIDS+=($!)
fastmcp run /app/software/LightGoogleClassroom/app.py --transport http --host 0.0.0.0 --port 9077 &
PIDS+=($!)
fastmcp run /app/software/LightGoogleDrive/app.py --transport http --host 0.0.0.0 --port 9078 &
PIDS+=($!)
fastmcp run /app/software/LightGoogleMaps/app.py --transport http --host 0.0.0.0 --port 9079 &
PIDS+=($!)
fastmcp run /app/software/LightGreenhouse/app.py --transport http --host 0.0.0.0 --port 9080 &
PIDS+=($!)
fastmcp run /app/software/LightGusto/app.py --transport http --host 0.0.0.0 --port 9081 &
PIDS+=($!)
fastmcp run /app/software/LightHubspot/app.py --transport http --host 0.0.0.0 --port 9082 &
PIDS+=($!)
fastmcp run /app/software/LightInstacart/app.py --transport http --host 0.0.0.0 --port 9083 &
PIDS+=($!)
fastmcp run /app/software/LightInstagram/app.py --transport http --host 0.0.0.0 --port 9084 &
PIDS+=($!)
fastmcp run /app/software/LightIntercom/app.py --transport http --host 0.0.0.0 --port 9085 &
PIDS+=($!)
fastmcp run /app/software/LightJira/app.py --transport http --host 0.0.0.0 --port 9086 &
PIDS+=($!)
fastmcp run /app/software/LightKlaviyo/app.py --transport http --host 0.0.0.0 --port 9087 &
PIDS+=($!)
fastmcp run /app/software/LightKraken/app.py --transport http --host 0.0.0.0 --port 9088 &
PIDS+=($!)
fastmcp run /app/software/LightKubernetes/app.py --transport http --host 0.0.0.0 --port 9089 &
PIDS+=($!)
fastmcp run /app/software/LightLinear/app.py --transport http --host 0.0.0.0 --port 9090 &
PIDS+=($!)
fastmcp run /app/software/LightLinkedIn/app.py --transport http --host 0.0.0.0 --port 9091 &
PIDS+=($!)
fastmcp run /app/software/LightMailchimp/app.py --transport http --host 0.0.0.0 --port 9092 &
PIDS+=($!)
fastmcp run /app/software/LightMailgun/app.py --transport http --host 0.0.0.0 --port 9093 &
PIDS+=($!)
fastmcp run /app/software/LightMicrosoftTeams/app.py --transport http --host 0.0.0.0 --port 9094 &
PIDS+=($!)
fastmcp run /app/software/LightMixpanel/app.py --transport http --host 0.0.0.0 --port 9095 &
PIDS+=($!)
fastmcp run /app/software/LightMonday/app.py --transport http --host 0.0.0.0 --port 9096 &
PIDS+=($!)
fastmcp run /app/software/LightMyFitnessPal/app.py --transport http --host 0.0.0.0 --port 9097 &
PIDS+=($!)
fastmcp run /app/software/LightNASA/app.py --transport http --host 0.0.0.0 --port 9098 &
PIDS+=($!)
fastmcp run /app/software/LightNotion/app.py --transport http --host 0.0.0.0 --port 9099 &
PIDS+=($!)
fastmcp run /app/software/LightObsidian/app.py --transport http --host 0.0.0.0 --port 9100 &
PIDS+=($!)
fastmcp run /app/software/LightOkta/app.py --transport http --host 0.0.0.0 --port 9101 &
PIDS+=($!)
fastmcp run /app/software/LightOpenLibrary/app.py --transport http --host 0.0.0.0 --port 9102 &
PIDS+=($!)
fastmcp run /app/software/LightOpenWeather/app.py --transport http --host 0.0.0.0 --port 9103 &
PIDS+=($!)
fastmcp run /app/software/LightOutlook/app.py --transport http --host 0.0.0.0 --port 9104 &
PIDS+=($!)
fastmcp run /app/software/LightPagerDuty/app.py --transport http --host 0.0.0.0 --port 9105 &
PIDS+=($!)
fastmcp run /app/software/LightPayPal/app.py --transport http --host 0.0.0.0 --port 9106 &
PIDS+=($!)
fastmcp run /app/software/LightPinterest/app.py --transport http --host 0.0.0.0 --port 9107 &
PIDS+=($!)
fastmcp run /app/software/LightPlaid/app.py --transport http --host 0.0.0.0 --port 9108 &
PIDS+=($!)
fastmcp run /app/software/LightPostHog/app.py --transport http --host 0.0.0.0 --port 9109 &
PIDS+=($!)
fastmcp run /app/software/LightQuickBooks/app.py --transport http --host 0.0.0.0 --port 9110 &
PIDS+=($!)
fastmcp run /app/software/LightReddit/app.py --transport http --host 0.0.0.0 --port 9111 &
PIDS+=($!)
fastmcp run /app/software/LightRing/app.py --transport http --host 0.0.0.0 --port 9112 &
PIDS+=($!)
fastmcp run /app/software/LightSalesforce/app.py --transport http --host 0.0.0.0 --port 9113 &
PIDS+=($!)
fastmcp run /app/software/LightSegment/app.py --transport http --host 0.0.0.0 --port 9114 &
PIDS+=($!)
fastmcp run /app/software/LightSendGrid/app.py --transport http --host 0.0.0.0 --port 9115 &
PIDS+=($!)
fastmcp run /app/software/LightSentry/app.py --transport http --host 0.0.0.0 --port 9116 &
PIDS+=($!)
fastmcp run /app/software/LightServiceNow/app.py --transport http --host 0.0.0.0 --port 9117 &
PIDS+=($!)
fastmcp run /app/software/LightShippo/app.py --transport http --host 0.0.0.0 --port 9118 &
PIDS+=($!)
fastmcp run /app/software/LightSlack/app.py --transport http --host 0.0.0.0 --port 9119 &
PIDS+=($!)
fastmcp run /app/software/LightSpotify/app.py --transport http --host 0.0.0.0 --port 9120 &
PIDS+=($!)
fastmcp run /app/software/LightSquare/app.py --transport http --host 0.0.0.0 --port 9121 &
PIDS+=($!)
fastmcp run /app/software/LightStrava/app.py --transport http --host 0.0.0.0 --port 9122 &
PIDS+=($!)
fastmcp run /app/software/LightStripe/app.py --transport http --host 0.0.0.0 --port 9123 &
PIDS+=($!)
fastmcp run /app/software/LightTMDB/app.py --transport http --host 0.0.0.0 --port 9124 &
PIDS+=($!)
fastmcp run /app/software/LightTelegram/app.py --transport http --host 0.0.0.0 --port 9125 &
PIDS+=($!)
fastmcp run /app/software/LightTicketmaster/app.py --transport http --host 0.0.0.0 --port 9126 &
PIDS+=($!)
fastmcp run /app/software/LightTrello/app.py --transport http --host 0.0.0.0 --port 9127 &
PIDS+=($!)
fastmcp run /app/software/LightTwilio/app.py --transport http --host 0.0.0.0 --port 9128 &
PIDS+=($!)
fastmcp run /app/software/LightTwitch/app.py --transport http --host 0.0.0.0 --port 9129 &
PIDS+=($!)
fastmcp run /app/software/LightTwitter/app.py --transport http --host 0.0.0.0 --port 9130 &
PIDS+=($!)
fastmcp run /app/software/LightTypeform/app.py --transport http --host 0.0.0.0 --port 9131 &
PIDS+=($!)
fastmcp run /app/software/LightUPS/app.py --transport http --host 0.0.0.0 --port 9132 &
PIDS+=($!)
fastmcp run /app/software/LightUber/app.py --transport http --host 0.0.0.0 --port 9133 &
PIDS+=($!)
fastmcp run /app/software/LightVimeo/app.py --transport http --host 0.0.0.0 --port 9134 &
PIDS+=($!)
fastmcp run /app/software/LightWebflow/app.py --transport http --host 0.0.0.0 --port 9135 &
PIDS+=($!)
fastmcp run /app/software/LightWhatsApp/app.py --transport http --host 0.0.0.0 --port 9136 &
PIDS+=($!)
fastmcp run /app/software/LightWooCommerce/app.py --transport http --host 0.0.0.0 --port 9137 &
PIDS+=($!)
fastmcp run /app/software/LightWordPress/app.py --transport http --host 0.0.0.0 --port 9138 &
PIDS+=($!)
fastmcp run /app/software/LightXero/app.py --transport http --host 0.0.0.0 --port 9139 &
PIDS+=($!)
fastmcp run /app/software/LightYelp/app.py --transport http --host 0.0.0.0 --port 9140 &
PIDS+=($!)
fastmcp run /app/software/LightYouTube/app.py --transport http --host 0.0.0.0 --port 9141 &
PIDS+=($!)
fastmcp run /app/software/LightZendesk/app.py --transport http --host 0.0.0.0 --port 9142 &
PIDS+=($!)
fastmcp run /app/software/LightZillow/app.py --transport http --host 0.0.0.0 --port 9143 &
PIDS+=($!)
fastmcp run /app/software/LightZoom/app.py --transport http --host 0.0.0.0 --port 9144 &
PIDS+=($!)

echo "All 161 servers started. Waiting..."
wait
