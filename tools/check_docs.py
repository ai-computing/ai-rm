#!/usr/bin/env python3
"""Check local Markdown links, image descriptions and SVG XML (stdlib only)."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class ImagesAndLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img':
            if not attrs.get('alt', '').strip():
                self.errors.append('HTML image needs descriptive alt text')
            self.links.append(attrs.get('src', ''))
        elif tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])


def main():
    errors = []
    pages = [ROOT / 'README.md', ROOT / 'README.ko.md', ROOT / 'CONTRIBUTING.md']
    pages += sorted((ROOT / 'docs').rglob('*.md'))
    pages += sorted((ROOT / 'deploy').glob('README*.md'))
    for page in pages:
        content = page.read_text(encoding='utf-8')
        content = re.sub(r'^```.*?^```\s*$', '', content, flags=re.M | re.S)
        parser = ImagesAndLinks()
        parser.feed(content)
        links = list(parser.links)
        errors += [(page, e) for e in parser.errors]
        for match in re.finditer(r'(!?)\[([^\]]*)\]\(([^\s)]+)(?:\s+"[^"]*")?\)', content):
            marker, label, target = match.groups()
            links.append(target.strip('<>'))
            if marker and not label.strip():
                errors.append((page, 'Markdown image needs descriptive alt text'))
        for target in links:
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = (page.parent / unquote(parsed.path)).resolve()
            if not resolved.is_relative_to(ROOT):
                errors.append((page, 'Link leaves the repository: ' + target))
            elif not resolved.exists():
                errors.append((page, 'Missing local target: ' + target))
    svgs = sorted((ROOT / 'docs' / 'assets').glob('*.svg'))
    ns = {'s': 'http://www.w3.org/2000/svg'}
    for svg in svgs:
        try:
            root = ET.parse(svg).getroot()
            if root.find('s:title', ns) is None or root.find('s:desc', ns) is None:
                errors.append((svg, 'SVG needs title and description'))
            if root.findall('.//s:script', ns):
                errors.append((svg, 'SVG must not contain scripts'))
        except ET.ParseError as exc:
            errors.append((svg, str(exc)))
    for path, error in errors:
        print('%s: %s' % (path.relative_to(ROOT).as_posix(), error))
    print('Checked %d Markdown pages and %d SVGs: %s' % (len(pages), len(svgs), 'PASS' if not errors else 'FAIL'))
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
