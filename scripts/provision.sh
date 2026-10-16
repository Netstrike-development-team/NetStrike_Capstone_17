#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: $0 <netstrike-bundle.tar.gz> <offline-bundles.tar.gz> <environment.json> <secrets.yml> <deployment-id> [external-ntp] [work-dir]" >&2
  exit 2
}

[[ $# -ge 5 && $# -le 7 ]] || usage

bundle_archive=$(realpath "$1")
offline_archive=$(realpath "$2")
environment_file=$(realpath "$3")
secrets_file=$(realpath "$4")
deployment_id=$5
external_ntp=${6:-false}
work_dir=${7:-"$PWD/offline-bundle"}

case "$external_ntp" in
  true|false) ;;
  *) echo "external-ntp must be true or false" >&2; exit 2 ;;
esac

for file in "$bundle_archive" "$offline_archive" "$environment_file" "$secrets_file"; do
  [[ -f "$file" ]] || { echo "File not found: $file" >&2; exit 1; }
done

mkdir -p "$work_dir"
work_dir=$(realpath "$work_dir")

tar -xzf "$bundle_archive" -C "$work_dir"

bundle_root="$work_dir/netstrike-offline-bundle"
[[ -d "$bundle_root" ]] || {
  echo "Expected bundle directory not found: $bundle_root" >&2
  exit 1
}

cd "$bundle_root"

sha256sum -c SHA256SUMS
tar -xzf runtime/python-runtime.tar.gz

python="$bundle_root/python/bin/python3.11"
ansible_galaxy="$bundle_root/python/bin/ansible-galaxy"
ansible_playbook="$bundle_root/python/bin/ansible-playbook"

"$python" -m pip install \
  --no-index \
  --find-links=destinations/CTRL01/wheelhouse \
  --require-hashes \
  -r destinations/CTRL01/requirements.lock

"$ansible_galaxy" collection install \
  --offline \
  --collections-path source/citef-config/collections \
  ansible/collections/*.tar.gz

tar -xzf "$offline_archive" -C source/

cp "$environment_file" source/citef-config/environment.json
cp "$secrets_file" source/citef-config/secrets.yml

cd source/citef-config

"$python" validate_environment.py inventory > inventory.ini

"$ansible_playbook" \
  -i inventory.ini \
  playbooks/provision.yml \
  --extra-vars "deployment_id=$deployment_id" \
  --extra-vars "@secrets.yml" \
  --extra-vars "controller_offline_bundle_root=$bundle_root" \
  --extra-vars "external_ntp=$external_ntp"
