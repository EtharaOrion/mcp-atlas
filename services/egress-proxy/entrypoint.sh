#!/bin/sh
# Squid runs as the unprivileged 'proxy' user and so cannot write to the
# container's stdout directly. It logs to a file instead; this tail is what puts
# denials into `docker logs egress-proxy`, which is where an operator debugging a
# blocked run will look first.
set -e

mkdir -p /var/log/squid /var/run/squid
: > /var/log/squid/access.log
chown -R proxy:proxy /var/log/squid /var/run/squid

tail -F /var/log/squid/access.log 2>/dev/null &

exec /usr/local/bin/entrypoint.sh "$@"
