# The only container in a task project with a route off the compose bridge.
# See squid.conf for why this exists rather than a Harbor network_mode.
FROM ubuntu/squid:latest

COPY squid.conf /etc/squid/squid.conf
COPY entrypoint.sh /usr/local/bin/egress-entrypoint.sh

RUN chmod +x /usr/local/bin/egress-entrypoint.sh

# Fail the build, not the run, on a malformed ACL. A squid that exits at
# container start looks exactly like a network outage from inside main, and
# costs an agent phase to diagnose.
RUN squid -k parse -f /etc/squid/squid.conf

EXPOSE 3128

ENTRYPOINT ["/usr/local/bin/egress-entrypoint.sh"]
CMD ["-f", "/etc/squid/squid.conf", "-NYC"]
