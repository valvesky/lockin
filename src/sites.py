#!/usr/bin/python3 -I
"""Social media block: a marked section of /etc/hosts.

Lock-In imports this module to read the block. A root-owned copy installed by
site-block-setup is the only thing that writes it, through a passwordless sudo
rule limited to `block` and `unblock`. As root this trusts nothing but the
domain names on stdin, which must be plain lowercase hostnames.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

HOSTS = "/etc/hosts"
HELPER = "/usr/local/libexec/lockin-sites"
BEGIN = b"# BEGIN LOCK-IN"
END = b"# END LOCK-IN"

# A hosts file matches exact names, so list the subdomains people actually land
# on. music.youtube.com stays reachable on purpose: background music is not a feed.
DEFAULT_SITES = (
    "x.com", "www.x.com", "mobile.x.com",
    "twitter.com", "www.twitter.com", "mobile.twitter.com",
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com", "m.reddit.com", "redd.it",
    "pinterest.com", "www.pinterest.com", "pin.it",
    "pt.pinterest.com", "br.pinterest.com", "uk.pinterest.com", "de.pinterest.com",
    "fr.pinterest.com", "es.pinterest.com", "it.pinterest.com", "nl.pinterest.com",
    "pinterest.co.uk", "www.pinterest.co.uk", "pinterest.pt", "www.pinterest.pt",
    "facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "fb.com", "www.fb.com",
    "instagram.com", "www.instagram.com",
    "tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com",
    "threads.com", "www.threads.com", "threads.net", "www.threads.net",
    "bsky.app",
    "linkedin.com", "www.linkedin.com",
    "snapchat.com", "www.snapchat.com", "web.snapchat.com",
    "tumblr.com", "www.tumblr.com",
    "twitch.tv", "www.twitch.tv", "m.twitch.tv",
    "9gag.com",
    "mastodon.social",
)

DOMAIN = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
MAX_SITES = 512


class Invalid(ValueError):
    pass


def validate(domains):
    domains = list(dict.fromkeys(domains))
    if not domains or len(domains) > MAX_SITES or not all(
            isinstance(d, str) and DOMAIN.fullmatch(d) for d in domains):
        raise Invalid("invalid_sites")
    return domains


def opens(line):
    line = line.rstrip(b"\r\n")
    return line == BEGIN or line.startswith(BEGIN + b" ")


def strip(data):
    """Remove Lock-In's section, leaving every other byte as it was."""
    kept, inside = [], False
    for line in data.splitlines(keepends=True):
        bare = line.rstrip(b"\r\n")
        if opens(line):
            inside = True
        elif inside and bare == END:
            inside = False
        elif not inside:
            kept.append(line)
    return b"".join(kept)


def render(data, domains=None):
    """The hosts file with Lock-In's section replaced, or removed when domains is None."""
    result = strip(data)
    if domains is None:
        return result
    if result and not result.endswith(b"\n"):
        result += b"\n"
    block = [BEGIN + b" (focus session; removed automatically)"]
    for domain in validate(domains):
        # Both families: an IPv4-only entry lets an AAAA answer through.
        block += [b"0.0.0.0 " + domain.encode(), b":: " + domain.encode()]
    return result + b"\n".join(block + [END]) + b"\n"


OPENED = re.compile(rb"^" + re.escape(BEGIN) + rb"(?:[ \r]|$)", re.MULTILINE)


def blocked(data):
    return OPENED.search(data) is not None


def write(path, domains):
    if os.path.islink(path):
        raise Invalid("hosts_is_symlink")
    with open(path, "rb") as source:
        mode = os.fstat(source.fileno()).st_mode & 0o7777
        data = source.read()
    updated = render(data, domains)
    if updated == data:
        return
    fd, name = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".hosts-lockin-")
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), mode)
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    except BaseException:
        if os.path.exists(name):
            os.unlink(name)
        raise


def main(argv):
    if len(argv) != 2 or argv[1] not in ("block", "unblock"):
        print("usage: lockin-sites block|unblock  (block reads one domain per line on stdin)", file=sys.stderr)
        return 2
    try:
        domains = None
        if argv[1] == "block":
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise Invalid("invalid_sites")
            domains = validate(raw.decode("ascii").split())
        write(HOSTS, domains)
    except (Invalid, UnicodeDecodeError, OSError) as exc:
        print(f"lockin-sites: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
