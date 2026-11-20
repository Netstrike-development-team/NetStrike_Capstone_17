"""Upload guard and explicit archive for trusted, quiescent CI-generated evidence.

Only the fixed disposable-root marker may be hidden. This is a file-shape guard,
not a secret scrubber, rehearsal verifier or protection against concurrent edits.
Default inspection is read-only; --archive creates one new output, never overwriting.
No application imports/dependencies are needed, including on failed CI runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import tarfile
from pathlib import Path


ROOT_MARKER = ".netstrike-disposable-root"
ROOT_CONTENT = b"NETSTRIKE DISPOSABLE IMPACT ROOT v1\n"
MAX_ENTRIES = 5000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


def inspect_upload(directory: Path | str) -> dict:
    """Refuse unexpected hidden entries, links, special files and oversized trees."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("evidence root must be a real directory")
    stack = [root]
    entries = files = markers = total_bytes = 0
    while stack:
        parent = stack.pop()
        for entry in sorted(parent.iterdir()):
            entries += 1
            if entries > MAX_ENTRIES:
                raise ValueError("evidence entry limit exceeded")
            info = entry.lstat()
            parts = entry.relative_to(root).parts
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("evidence links are not uploadable")
            hidden = any(part.startswith(".") for part in parts)
            marker = (
                len(parts) == 3
                and not parts[0].startswith(".")
                and parts[1] == "disposable"
                and parts[2] == ROOT_MARKER
            )
            if hidden and not marker:
                raise ValueError("unexpected hidden evidence entry")
            if stat.S_ISDIR(info.st_mode):
                if marker:
                    raise ValueError("disposable marker must be a regular file")
                stack.append(entry)
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("evidence must contain regular unlinked files")
            if info.st_size > MAX_FILE_BYTES:
                raise ValueError("evidence file limit exceeded")
            total_bytes += info.st_size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("evidence byte limit exceeded")
            if marker:
                if info.st_size != len(ROOT_CONTENT) or entry.read_bytes() != ROOT_CONTENT:
                    raise ValueError("disposable marker content is not approved")
                markers += 1
            files += 1
    if not files:
        raise ValueError("evidence directory contains no files")
    return {
        "upload_safe": True,
        "entries_checked": entries,
        "files_checked": files,
        "hidden_root_markers": markers,
        "total_bytes": total_bytes,
    }


def package_upload(directory: Path | str, destination: Path | str) -> dict:
    """Preserve all approved files and empty directories without platform xattrs."""
    root = Path(directory).absolute()
    output = Path(destination).absolute()
    if output.is_relative_to(root):
        raise ValueError("archive must be outside the generated evidence directory")
    result = inspect_upload(root)
    # x:gz refuses an existing file/link. No deletion of failed/partial outputs.
    with tarfile.open(output, "x:gz") as archive:
        archive.add(root, arcname=".", recursive=False)
        for entry in sorted(root.rglob("*")):
            archive.add(entry, arcname=entry.relative_to(root).as_posix(), recursive=False)
    result["archive_created"] = True
    result["archive_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--archive", type=Path, help="Explicit new tar.gz outside the input")
    args = parser.parse_args(argv)
    try:
        result = (package_upload(args.directory, args.archive) if args.archive
                  else inspect_upload(args.directory))
    except (OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "unable to inspect evidence"
        print(json.dumps({"upload_safe": False, "error": message}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
