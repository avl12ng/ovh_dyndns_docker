#!/usr/bin/env python3
"""OVH Dynamic DNS updater.

On every run this script performs the following steps:

  1. Resolve the machine's current public IPv4 address using one or more
     HTTP "what is my IP" services (with fallback).
  2. Read the A record currently stored in the OVH DNS zone for the
     configured FQDN.
  3. Compare both values:
       - identical  -> do nothing (the DNS record is already up to date).
       - different  -> call the OVH API to update the record, then refresh
         the zone so the change is applied.

The script is designed to be run once per container start (one-shot mode).
It can also loop at a fixed interval when RUN_INTERVAL is set to a positive
number of seconds.

All configuration is provided through environment variables (see .env.example).
"""

from __future__ import annotations

import ipaddress
import logging
import os
import sys
import time
import urllib.request

import ovh


# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
log = logging.getLogger("ovh-dyndns")


# --------------------------------------------------------------------------- #
# Configuration helpers
# --------------------------------------------------------------------------- #
def get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Read an environment variable, optionally enforcing its presence."""
    value = os.environ.get(name, default)
    if required and (value is None or value.strip() == ""):
        log.error("Missing required environment variable: %s", name)
        sys.exit(2)
    return value


def str_to_bool(value: str | None, default: bool = False) -> bool:
    """Convert a textual flag (true/1/yes/on) into a boolean."""
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------- #
# Public IP resolution
# --------------------------------------------------------------------------- #
# Default list of endpoints that return the caller's public IPv4 as plain text.
DEFAULT_IP_LOOKUP_URLS = (
    "https://api.ipify.org,"
    "https://ipv4.icanhazip.com,"
    "https://ifconfig.me/ip"
)


def get_public_ip(lookup_urls: list[str], timeout: int = 10) -> str:
    """Return the current public IPv4 address.

    Each URL is tried in order until one returns a valid IPv4 address.
    An exception is raised if every endpoint fails.
    """
    last_error: Exception | None = None
    for url in lookup_urls:
        url = url.strip()
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ovh-dyndns/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                candidate = resp.read().decode("utf-8").strip()
            # Validate that the response is a proper IPv4 address.
            ip = ipaddress.ip_address(candidate)
            if ip.version != 4:
                raise ValueError(f"{url} returned a non-IPv4 address: {candidate}")
            log.debug("Public IP %s resolved via %s", candidate, url)
            return str(ip)
        except Exception as exc:  # noqa: BLE001 - we want to try the next endpoint
            last_error = exc
            log.warning("IP lookup failed via %s: %s", url, exc)

    raise RuntimeError(f"Could not resolve public IPv4 address. Last error: {last_error}")


# --------------------------------------------------------------------------- #
# FQDN / zone handling
# --------------------------------------------------------------------------- #
def derive_subdomain(fqdn: str, zone: str) -> str:
    """Derive the OVH sub-domain part from an FQDN and its DNS zone.

    Examples:
        derive_subdomain("ext.mondomaine.fr", "mondomaine.fr") -> "ext"
        derive_subdomain("a.b.mondomaine.fr", "mondomaine.fr") -> "a.b"
        derive_subdomain("mondomaine.fr",     "mondomaine.fr") -> ""   (zone apex)
    """
    fqdn = fqdn.strip().rstrip(".").lower()
    zone = zone.strip().rstrip(".").lower()

    if fqdn == zone:
        return ""  # Root of the zone (apex record).
    suffix = "." + zone
    if fqdn.endswith(suffix):
        return fqdn[: -len(suffix)]

    log.error("RECORD_FQDN '%s' does not belong to DNS_ZONE '%s'.", fqdn, zone)
    sys.exit(2)


# --------------------------------------------------------------------------- #
# OVH API operations
# --------------------------------------------------------------------------- #
def build_ovh_client() -> ovh.Client:
    """Instantiate the OVH API client from environment variables."""
    return ovh.Client(
        endpoint=get_env("OVH_ENDPOINT", "ovh-eu"),
        application_key=get_env("OVH_APPLICATION_KEY", required=True),
        application_secret=get_env("OVH_APPLICATION_SECRET", required=True),
        consumer_key=get_env("OVH_CONSUMER_KEY", required=True),
    )


def find_record_id(client: ovh.Client, zone: str, subdomain: str) -> int | None:
    """Return the id of the A record for the given sub-domain, or None."""
    record_ids = client.get(
        f"/domain/zone/{zone}/record",
        fieldType="A",
        subDomain=subdomain,
    )
    if not record_ids:
        return None
    if len(record_ids) > 1:
        log.warning(
            "Multiple A records found for sub-domain '%s' in zone '%s'; "
            "the first one (id=%s) will be used.",
            subdomain or "@",
            zone,
            record_ids[0],
        )
    return record_ids[0]


def get_record_target(client: ovh.Client, zone: str, record_id: int) -> str:
    """Return the current IP target stored in the given A record."""
    record = client.get(f"/domain/zone/{zone}/record/{record_id}")
    return str(record.get("target", "")).strip()


def update_record(client: ovh.Client, zone: str, record_id: int, new_ip: str) -> None:
    """Update the target of an existing A record and refresh the zone."""
    client.put(f"/domain/zone/{zone}/record/{record_id}", target=new_ip)
    client.post(f"/domain/zone/{zone}/refresh")


def create_record(
    client: ovh.Client, zone: str, subdomain: str, new_ip: str, ttl: int
) -> None:
    """Create a new A record for the sub-domain and refresh the zone."""
    client.post(
        f"/domain/zone/{zone}/record",
        fieldType="A",
        subDomain=subdomain,
        target=new_ip,
        ttl=ttl,
    )
    client.post(f"/domain/zone/{zone}/refresh")


# --------------------------------------------------------------------------- #
# Core reconciliation logic
# --------------------------------------------------------------------------- #
def reconcile() -> int:
    """Perform a single check/update cycle. Returns a process exit code."""
    # --- Read configuration -------------------------------------------------
    dns_zone = get_env("DNS_ZONE", required=True).strip().rstrip(".")
    record_fqdn = get_env("RECORD_FQDN", required=True).strip().rstrip(".")
    record_ttl = int(get_env("RECORD_TTL", "60"))
    create_if_missing = str_to_bool(get_env("CREATE_IF_MISSING", "true"), default=True)
    lookup_urls = get_env("IP_LOOKUP_URLS", DEFAULT_IP_LOOKUP_URLS).split(",")

    subdomain = derive_subdomain(record_fqdn, dns_zone)
    display_name = record_fqdn if subdomain else f"{dns_zone} (apex)"

    # --- Resolve the current public IP -------------------------------------
    public_ip = get_public_ip(lookup_urls)
    log.info("Current public IPv4 address: %s", public_ip)

    # --- Query the OVH DNS zone --------------------------------------------
    client = build_ovh_client()
    record_id = find_record_id(client, dns_zone, subdomain)

    if record_id is None:
        # No A record exists yet for this FQDN.
        if create_if_missing:
            log.info("No existing A record for %s; creating it -> %s", display_name, public_ip)
            create_record(client, dns_zone, subdomain, public_ip, record_ttl)
            log.info("A record created and zone refreshed.")
            return 0
        log.error(
            "No A record found for %s and CREATE_IF_MISSING is disabled.", display_name
        )
        return 1

    current_target = get_record_target(client, dns_zone, record_id)
    log.info("DNS A record for %s currently points to: %s", display_name, current_target)

    # --- Compare and act ----------------------------------------------------
    if current_target == public_ip:
        log.info("No change required: DNS already matches the public IP.")
        return 0

    log.info("IP mismatch detected: %s -> %s. Updating OVH record...", current_target, public_ip)
    update_record(client, dns_zone, record_id, public_ip)
    log.info("A record updated to %s and zone refreshed.", public_ip)
    return 0


def main() -> None:
    """Entry point. Runs once, or loops when RUN_INTERVAL is set."""
    run_interval = int(get_env("RUN_INTERVAL", "0"))

    if run_interval <= 0:
        # One-shot mode: run once on container start, then exit.
        sys.exit(reconcile())

    # Loop mode: keep the container alive and re-check periodically.
    log.info("Running in loop mode, interval = %s seconds.", run_interval)
    while True:
        try:
            reconcile()
        except Exception as exc:  # noqa: BLE001 - keep the loop alive on transient errors
            log.error("Reconciliation failed: %s", exc)
        time.sleep(run_interval)


if __name__ == "__main__":
    main()
