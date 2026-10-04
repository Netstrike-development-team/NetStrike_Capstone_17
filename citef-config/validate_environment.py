#!/usr/bin/env python3
"""Validate the approved, non-secret CITEF manifest and render inventory."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


REQUIRED_HOSTS = {"CTRL01", "DC01", "FIN-WS01", "SPLUNK01"}
KNOWN_ASSETS = REQUIRED_HOSTS | {"FILE01", "IDP01", "HELPDESK01", "CLOUD01"}
PROJECT_SERVICES = {"IDP01", "HELPDESK01", "CLOUD01"}
SECRET_KEY = re.compile(r"(password|token|secret|private.?key|credential)", re.I)
RFC1918 = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


class ManifestError(ValueError):
    """Raised when the environment manifest is incomplete or unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _schema_errors(manifest: object) -> list[str]:
    """Return readable structural errors from the checked-in JSON Schema."""
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        raise ManifestError(
            "jsonschema is required; install citef-config/requirements-validator.txt "
            "from the approved offline wheelhouse"
        ) from exc

    schema_path = Path(__file__).with_name("environment.schema.json")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load manifest schema {schema_path}: {exc}") from exc

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = []
    for error in validator.iter_errors(manifest):
        location = ".".join(str(part) for part in error.absolute_path) or "manifest"
        errors.append(f"{location}: {error.message}")
    return sorted(errors)


def _reject_secret_fields(value: object, path: str = "manifest") -> None:
    """Give a direct error for credentials, even though unknown keys also fail schema."""
    if isinstance(value, dict):
        for key, nested in value.items():
            _require(
                not SECRET_KEY.search(str(key)),
                f"{path}.{key} must not contain credentials or secrets",
            )
            _reject_secret_fields(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_fields(nested, f"{path}[{index}]")


def _private_network(value: str, field: str) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise ManifestError(f"{field} must be a valid IPv4 network in CIDR notation") from exc
    _require(isinstance(network, ipaddress.IPv4Network), f"{field} must be IPv4")
    _require(
        any(network.subnet_of(private) for private in RFC1918),
        f"{field} must use an RFC 1918 private range",
    )
    return network


def _private_address(value: str, field: str) -> ipaddress.IPv4Address:
    address = ipaddress.ip_address(value)
    _require(isinstance(address, ipaddress.IPv4Address), f"{field} must be IPv4")
    _require(
        any(address in private for private in RFC1918),
        f"{field} must use an RFC 1918 private address",
    )
    return address


def _reverse_dns_zone(network: ipaddress.IPv4Network) -> str:
    labels = network.network_address.reverse_pointer.split(".")
    unused_labels = (32 - network.prefixlen) // 8
    return ".".join(labels[unused_labels:])


def _safe_relative_path(value: str, field: str) -> PurePosixPath:
    path = PurePosixPath(value)
    _require(
        not path.is_absolute() and "\\" not in value and ".." not in path.parts,
        f"{field} must be a safe relative path",
    )
    return path


def _internal_url(value: str, field: str, domain: str) -> str:
    try:
        parsed = urlparse(value)
        host = parsed.hostname
    except ValueError as exc:
        raise ManifestError(f"{field} must contain a valid host") from exc
    _require(
        parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and host is not None,
        f"{field} must not contain credentials, query values, or fragments",
    )
    host = host.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        _require(
            host == domain or host.endswith(f".{domain}"),
            f"{field} must use an approved internal host in {domain}",
        )
    else:
        _require(
            isinstance(address, ipaddress.IPv4Address)
            and any(address in private for private in RFC1918),
            f"{field} must use an RFC 1918 private address",
        )
    return host


def _url_port(value: str, field: str) -> int | None:
    try:
        return urlparse(value).port
    except ValueError as exc:
        raise ManifestError(f"{field} must contain a valid port") from exc


def _validate_cross_fields(manifest: dict) -> None:
    """Enforce relationships that JSON Schema cannot express clearly."""
    network = manifest["network"]
    domain = network["domain_dns_name"].lower().rstrip(".")
    exercise = _private_network(network["exercise_cidr"], "network.exercise_cidr")
    management = _private_network(network["management_cidr"], "network.management_cidr")
    _require(exercise.prefixlen == 24, "network.exercise_cidr must be /24 until subnet-specific reverse DNS support is configured")
    _require(not exercise.overlaps(management), "exercise and management networks must not overlap")
    _require(
        network["reverse_dns_zone"] == _reverse_dns_zone(exercise),
        "network.reverse_dns_zone must match the reverse zone for network.exercise_cidr",
    )

    for field in ("dns_servers", "ntp_servers"):
        for index, value in enumerate(network[field]):
            address = _private_address(value, f"network.{field}[{index}]")
            approved = next((item for item in (exercise, management) if address in item), None)
            _require(approved is not None, f"network.{field}[{index}] must be inside an approved network")
            _require(
                address not in (approved.network_address, approved.broadcast_address),
                f"network.{field}[{index}] cannot be a network or broadcast address",
            )

    hosts: dict[str, dict] = {}
    addresses: set[ipaddress.IPv4Address] = set()
    logical_to_host: dict[str, str] = {}
    for index, host in enumerate(manifest["assets"]):
        field = f"assets[{index}]"
        name = host["name"]
        _require(name not in hosts, f"duplicate host name: {name}")
        address = _private_address(host["address"], f"{field}.address")
        _require(address in exercise, f"{field}.address must be inside network.exercise_cidr")
        _require(
            address not in (exercise.network_address, exercise.broadcast_address),
            f"{field}.address cannot be the network or broadcast address",
        )
        _require(address not in addresses, f"duplicate host address: {address}")
        addresses.add(address)
        _require(
            host["dns_name"].lower().rstrip(".") == f"{name.lower()}.{domain}",
            f"{field}.dns_name must be {name.lower()}.{domain}",
        )
        expected_connection = "ssh" if host["os_family"] == "linux" else "winrm"
        _require(
            host["connection"] == expected_connection,
            f"{field}.connection must be {expected_connection} for {host['os_family']}",
        )
        if expected_connection == "winrm":
            _require(host["port"] == 5986, f"{field}.port must be 5986 so WinRM uses HTTPS")
        for asset in host["logical_assets"]:
            _require(asset not in logical_to_host, f"logical asset {asset} is mapped more than once")
            logical_to_host[asset] = name
        hosts[name] = host

    _require(REQUIRED_HOSTS.issubset(hosts), "assets must include CTRL01, DC01, FIN-WS01, and SPLUNK01")
    dc_address = hosts["DC01"]["address"]
    _require(dc_address in network["dns_servers"], "network.dns_servers must include the planned DC01 DNS service address")
    _require(dc_address in network["ntp_servers"], "network.ntp_servers must include the planned DC01 time service address")
    for name in REQUIRED_HOSTS:
        _require(name in hosts[name]["logical_assets"], f"logical asset {name} must map to its dedicated host")
    _require(
        set(logical_to_host) == KNOWN_ASSETS,
        f"logical_assets must map exactly {', '.join(sorted(KNOWN_ASSETS))}",
    )
    for asset in PROJECT_SERVICES:
        _require(logical_to_host[asset] == "CTRL01", f"logical asset {asset} must be hosted on CTRL01")
    _require(logical_to_host["FILE01"] in ("CTRL01", "FILE01"), "FILE01 may be consolidated on CTRL01 or assigned to its own host")
    if logical_to_host["FILE01"] == "FILE01":
        _require(hosts["FILE01"]["os_family"] == "linux", "a dedicated FILE01 must use Linux")

    identity = manifest["identity_baseline"]
    _require(
        identity["domain_dns_name"].lower().rstrip(".") == domain,
        "identity_baseline.domain_dns_name must match network.domain_dns_name",
    )
    search_base = ",".join(f"OU={ou}" for ou in reversed(identity["organizational_units"]))
    search_base += "," + ",".join(f"DC={part}" for part in domain.split("."))
    _require(
        identity["search_base_dn"].lower() == search_base.lower(),
        "identity_baseline.search_base_dn must match its OU path and domain",
    )
    group_names = set(identity["groups"])
    user_names: set[str] = set()
    for user in identity["users"]:
        name = user["sam_account_name"]
        _require(name not in user_names, f"duplicate baseline identity: {name}")
        user_names.add(name)
        unknown_groups = set(user["member_of"]) - group_names - {"Domain Users"}
        _require(not unknown_groups, f"baseline identity {name} references groups not in identity_baseline.groups")

    for index, fixture in enumerate(manifest["fixtures"]):
        path = PurePosixPath(fixture["path"])
        _require(path.is_absolute() and ".." not in path.parts, f"fixtures[{index}].path must be an absolute, traversal-free Linux path")

    splunk = manifest["splunk"]
    _require(splunk["forwarder_receiver"]["host"].lower() == hosts["SPLUNK01"]["dns_name"].lower(),
             "splunk.forwarder_receiver.host must match the approved SPLUNK01 DNS name")
    _internal_url(splunk["rest_url"], "splunk.rest_url", domain)
    source_ids: set[str] = set()
    for source in splunk["required_sources"]:
        _require(source["id"] not in source_ids, f"duplicate Splunk source id: {source['id']}")
        source_ids.add(source["id"])

    artifacts = manifest["offline_artifacts"]
    _safe_relative_path(artifacts["directory"], "offline_artifacts.directory")
    artifact_specs = [
        (artifacts["controller_source"], "offline_artifacts.controller_source.file"),
        (artifacts["python_runtime"]["archive"], "offline_artifacts.python_runtime.archive.file"),
        (artifacts["python_runtime"]["requirements_lock"], "offline_artifacts.python_runtime.requirements_lock.file"),
        (artifacts["universal_forwarder"]["linux_deb"], "offline_artifacts.universal_forwarder.linux_deb.file"),
        (artifacts["universal_forwarder"]["windows_msi"], "offline_artifacts.universal_forwarder.windows_msi.file"),
        (artifacts["universal_forwarder"]["receiver_ca"], "offline_artifacts.universal_forwarder.receiver_ca.file"),
        (artifacts["sysmon"]["executable"], "offline_artifacts.sysmon.executable.file"),
        (artifacts["sysmon"]["config"], "offline_artifacts.sysmon.config.file"),
    ]
    controller = manifest["controller"]
    artifact_specs.extend(
        (
            (controller["tls_certificate"], "controller.tls_certificate.file"),
            (controller["tls_ca"], "controller.tls_ca.file"),
        )
    )
    for artifact, field in artifact_specs:
        _safe_relative_path(artifact["file"], field)

    runtime = _safe_relative_path(
        artifacts["python_runtime"]["archive"]["file"],
        "offline_artifacts.python_runtime.archive.file",
    )
    lock = _safe_relative_path(
        artifacts["python_runtime"]["requirements_lock"]["file"],
        "offline_artifacts.python_runtime.requirements_lock.file",
    )
    bundle_root = runtime.parent.parent
    _require(
        runtime.name == "python-runtime.tar.gz" and runtime.parent.name == "runtime",
        "offline_artifacts.python_runtime.archive.file must identify runtime/python-runtime.tar.gz",
    )
    _require(
        lock.name == "requirements.lock"
        and lock.parent.name == "CTRL01"
        and lock.parent.parent.name == "destinations"
        and lock.parent.parent.parent == bundle_root,
        "offline_artifacts.python_runtime.requirements_lock.file must identify the CTRL01 lock in the same bundle",
    )

    readiness_host = _internal_url(controller["readiness_url"], "controller.readiness_url", domain)
    _require(readiness_host == hosts["CTRL01"]["dns_name"].lower(), "controller.readiness_url must use the approved CTRL01 DNS name")
    listen_port = controller["listen_port"]
    _require(_url_port(controller["readiness_url"], "controller.readiness_url") == listen_port,
             "controller.readiness_url port must match controller.listen_port")
    for index, origin in enumerate(controller["sso_allowed_origins"]):
        origin_host = _internal_url(origin, f"controller.sso_allowed_origins[{index}]", domain)
        _require(origin_host == hosts["CTRL01"]["dns_name"].lower(),
                 f"controller.sso_allowed_origins[{index}] must use the approved CTRL01 DNS name")
        _require(_url_port(origin, f"controller.sso_allowed_origins[{index}]") == listen_port,
                 f"controller.sso_allowed_origins[{index}] port must match controller.listen_port")

    _require(
        set(manifest["snapshots"]["snapshot_ids"]) == set(hosts),
        "snapshots.snapshot_ids must name every physical host exactly once",
    )


def validate_manifest(manifest: object) -> dict:
    """Validate schema first, then cross-field safety rules."""
    _reject_secret_fields(manifest)
    errors = _schema_errors(manifest)
    if errors:
        raise ManifestError("Manifest schema validation failed:\n- " + "\n- ".join(errors))
    _validate_cross_fields(manifest)
    return manifest


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON in {path}: {exc}") from exc
    return validate_manifest(manifest)


def _inventory_host(host: dict) -> str:
    assets = ",".join(host["logical_assets"])
    services = ",".join(host["required_services"])
    winrm_options = (
        " ansible_winrm_scheme=https ansible_winrm_server_cert_validation=validate"
        if host["connection"] == "winrm"
        else ""
    )
    return (
        f"{host['name'].lower()} ansible_host={host['address']} "
        f"ansible_connection={host['connection']} ansible_port={host['port']} "
        f"expected_os_family={host['os_family']} logical_name={host['name']} "
        f"logical_assets={assets!r} required_services={services!r}{winrm_options}"
    )


def render_inventory(manifest: dict) -> str:
    """Render an INI inventory only after the full manifest passes validation."""
    validate_manifest(manifest)
    file_store = next(host["name"] for host in manifest["assets"] if "FILE01" in host["logical_assets"])
    groups = (
        ("controllers", "CTRL01"),
        ("domain_controllers", "DC01"),
        ("workstations", "FIN-WS01"),
        ("splunk", "SPLUNK01"),
        ("file_store", file_store),
    )
    lines = [
        "# Generated from the approved local environment.json; do not hand-edit.",
        "[linux_hosts]",
        *(_inventory_host(host) for host in manifest["assets"] if host["os_family"] == "linux"),
        "",
        "[windows_hosts]",
        *(_inventory_host(host) for host in manifest["assets"] if host["os_family"] == "windows"),
    ]
    for group, host_name in groups:
        lines.extend(("", f"[{group}]", host_name.lower()))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "inventory"))
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("environment.json"))
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.config)
        if args.action == "inventory":
            sys.stdout.write(render_inventory(manifest))
        else:
            print("Approved CITEF manifest is complete and safe to use.")
    except ManifestError as exc:
        print(f"Environment validation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
