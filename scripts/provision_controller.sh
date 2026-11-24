#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: $0 <netstrike-bundle.tar.gz> <controller-ip> <environment.json> <secrets.yml> <deployment-version> <exercise-run-id> [work-dir]" >&2
  exit 2
}

[[ $# -ge 6 && $# -le 7 ]] || usage

bundle_archive=$(realpath "$1")
controller_ip=$2
environment_file=$(realpath "$3")
secrets_file=$(realpath "$4")
deployment_version=$5
exercise_run_id=$6
work_dir=${7:-"$PWD/offline-controller-bundle"}

for file in "$bundle_archive" "$environment_file" "$secrets_file"; do
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

cp "$environment_file" source/citef-config/environment.json
install -m 600 "$secrets_file" source/citef-config/secrets.yml

cd source/citef-config

"$python" validate_environment.py validate --config environment.json
manifest_controller_ip=$("$python" -c \
  'import json, sys; print(next(asset["address"] for asset in json.load(open(sys.argv[1], encoding="utf-8"))["assets"] if asset["name"] == "CTRL01"))' \
  environment.json)
[[ "$controller_ip" == "$manifest_controller_ip" ]] || {
  echo "Controller IP $controller_ip does not match the approved CTRL01 address $manifest_controller_ip." >&2
  exit 1
}

"$ansible_playbook" \
  -i "${controller_ip}," \
  playbooks/controller_service.yml \
  --extra-vars "deployment_version=$deployment_version" \
  --extra-vars "exercise_run_id=$exercise_run_id" \
  --extra-vars "@secrets.yml" \
  --extra-vars "controller_offline_bundle_root=$bundle_root"
