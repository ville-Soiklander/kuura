"""
Scan text files for forbidden product names without storing the names.

WHY hashes: the repository is public and must not contain the forbidden names
anywhere, including in this checker. Names are therefore stored only as SHA-256
hashes of their normalised form (lowercase letters and digits, no separators).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

# Words are runs of ASCII letters and digits; every other character separates words.
_WORD = re.compile(r"[A-Za-z0-9]+")
# Files larger than this are skipped: they are generated or binary data, not prose.
_MAX_BYTES = 2_000_000
# Bytes inspected to decide whether a file is binary.
_SNIFF_BYTES = 8192
# Hash list next to this script: one 64 character hex digest per line, '#' starts a comment.
HASH_FILE = Path(__file__).with_name("forbidden_terms.sha256")


def load_hashes(path: Path) -> set[str]:
    """
    Read the hash list.

    Args:
        path: File with one hex digest per line; blank lines and lines starting
            with '#' are ignored.

    Returns:
        Set of lowercase digests.

    Raises:
        FileNotFoundError: if the file does not exist.
    """
    hashes = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            # Strip whitespace from both ends.
            line = line.strip()
            # Skip blank lines and comment lines.
            if line and not line.startswith("#"):
                # Lowercase the digest to normalize.
                hashes.add(line.lower())
    return hashes


def line_hits(line: str, hashes: set[str]) -> bool:
    """
    Check one line of text against the hash set.

    Args:
        line: A single line of text.
        hashes: Set of forbidden digests.

    Returns:
        True if any single word, or any two adjacent words joined without a
        separator, lowercased and hashed with SHA-256, is in `hashes`.
    """
    # Extract all words (runs of ASCII letters and digits).
    words = _WORD.findall(line)

    # Check each single word.
    for word in words:
        # Lowercase and hash the word.
        lowered = word.lower()
        digest = hashlib.sha256(lowered.encode("utf-8")).hexdigest()
        if digest in hashes:
            return True

    # Check each pair of adjacent words joined without separator.
    for i in range(len(words) - 1):
        # Concatenate two adjacent words and lowercase.
        pair = (words[i] + words[i + 1]).lower()
        digest = hashlib.sha256(pair.encode("utf-8")).hexdigest()
        if digest in hashes:
            return True

    return False


def scan_text(text: str, hashes: set[str]) -> list[int]:
    """
    Find the lines of a text that contain a forbidden name.

    Args:
        text: Whole file content.
        hashes: Set of forbidden digests.

    Returns:
        Ascending 1-based line numbers for which line_hits is True.
    """
    hits = []
    # Use enumerate with start=1 to get 1-based line numbers.
    for line_num, line in enumerate(text.splitlines(), start=1):
        if line_hits(line, hashes):
            hits.append(line_num)
    return hits


def is_text_file(path: Path) -> bool:
    """
    Decide from the content whether a file should be scanned.

    Args:
        path: File to inspect.

    Returns:
        False if the file is larger than _MAX_BYTES or the first _SNIFF_BYTES
        bytes contain a NUL byte; otherwise True.
    """
    try:
        # Check file size: if too large, it is likely generated or binary.
        stat = path.stat()
        if stat.st_size > _MAX_BYTES:
            return False

        # Read the first _SNIFF_BYTES to detect NUL bytes (binary indicator).
        with open(path, "rb") as f:
            sniff = f.read(_SNIFF_BYTES)

        # If there is a NUL byte, treat as binary.
        if b"\x00" in sniff:
            return False

        return True
    except OSError:
        # If the file cannot be read (missing, permission denied, etc), return False.
        return False


def tracked_files(root: Path) -> list[Path]:
    """
    List the files tracked by git under a directory.

    Args:
        root: Repository root.

    Returns:
        Absolute paths of tracked files.

    Raises:
        RuntimeError: if git cannot be run or exits with a non-zero status.
    """
    try:
        # Use git ls-files with -z to get NUL-terminated output.
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=False,
            text=False,
        )
    except FileNotFoundError as e:
        # git command not found.
        raise RuntimeError("git ls-files failed") from e

    # Check exit code.
    if result.returncode != 0:
        raise RuntimeError("git ls-files failed")

    # Split by NUL byte and filter out empty entries.
    files = []
    for entry in result.stdout.split(b"\x00"):
        if entry:
            # Decode the path and make it absolute.
            path = root / entry.decode("utf-8", errors="replace")
            files.append(path.resolve())

    return files


def main(argv: list[str] | None = None) -> int:
    """
    Entry point.

    Args:
        argv: File paths to scan; when empty, scan every tracked file of the
            repository that contains this script's parent directory.

    Returns:
        0 when nothing is found, 1 when at least one hit is found, 2 when the
        hash file is missing or git fails.
    """
    if argv is None:
        argv = sys.argv[1:]

    # Load the hash set from the hash file.
    try:
        hashes = load_hashes(HASH_FILE)
    except FileNotFoundError:
        print("forbidden_terms.sha256 not found", file=sys.stderr)
        return 2

    # Determine which files to scan.
    if argv:
        # Scan the given file paths.
        files = [Path(arg) for arg in argv]
    else:
        # Scan all tracked files of the repository.
        try:
            repo_root = HASH_FILE.parent
            files = tracked_files(repo_root)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 2

    # Scan each file and collect hits.
    hit_count = 0
    for file_path in files:
        # Skip files that are not text.
        if not is_text_file(file_path):
            continue

        try:
            # Read the file with error replacement for robustness.
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            # If the file cannot be read, skip it.
            continue

        # Scan the text for forbidden terms.
        line_numbers = scan_text(text, hashes)
        for line_num in line_numbers:
            print(f"{file_path}:{line_num}: forbidden term")
            hit_count += 1

    # Return 1 if any hits were found, else 0.
    return 1 if hit_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
