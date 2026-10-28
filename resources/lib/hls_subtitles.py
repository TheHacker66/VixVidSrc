"""Load HLS WebVTT renditions as standalone WebVTT files for Kodi."""
import re
import time
import urllib.parse

MAX_SEGMENTS = 64
MAX_BYTES = 16 * 1024 * 1024
TIME = r'(?:\d+:)?\d{2}:\d{2}[.]\d{3}'
TIMING = re.compile(r'^(' + TIME + r')\s+-->\s+(' + TIME + r')(.*)$')


def attributes(value):
    return {m[1]: m[2][1:-1] if m[2].startswith('"') else m[2]
            for m in re.finditer(r'([A-Z0-9-]+)=("[^"\r\n]*"|[^,\r\n]*)', value)}


def tracks(manifest, base_url):
    result = []
    for line in manifest.splitlines():
        if not line.startswith('#EXT-X-MEDIA:'):
            continue
        attr = attributes(line.split(':', 1)[1])
        if attr.get('TYPE') != 'SUBTITLES' or not attr.get('URI'):
            continue
        label = attr.get('NAME') or attr.get('LANGUAGE') or 'Sottotitoli'
        raw_code = attr.get('LANGUAGE', 'und').lower()
        forced = attr.get('FORCED') == 'YES' or 'forced' in label.lower() or 'forced' in raw_code
        code = next((p for p in re.split('[-_]', raw_code) if p != 'forced'), 'und')
        result.append({'url': urllib.parse.urljoin(base_url, attr['URI']), 'code': code,
                       'label': label, 'hls': True, 'forced': forced,
                       'cc': '[cc]' in label.lower() or 'sdh' in label.lower()})
    return result


def seconds(value):
    parts = value.strip().split(':')
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError('Timestamp WebVTT non valido')


def timestamp(value):
    ms = max(0, round(value * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    secs, ms = divmod(ms, 1000)
    return '%02d:%02d:%02d.%03d' % (hours, minutes, secs, ms)


def cues(text):
    result = []
    # WebVTT blocks are separated by blank lines. Ignore header/STYLE/NOTE.
    for block in re.split(r'\n[ \t]*\n', text.replace('\r', '').strip()):
        lines = block.splitlines()
        if not lines or lines[0].startswith(('NOTE', 'STYLE', 'REGION', 'WEBVTT')):
            continue
        index = 0 if TIMING.match(lines[0]) else 1
        if index >= len(lines):
            continue
        match = TIMING.match(lines[index])
        if match and len(lines) > index + 1:
            start, end = seconds(match[1]), seconds(match[2])
            if end > start:
                result.append((start, end, match[3], '\n'.join(lines[index + 1:])))
    return result


def download(url, get):
    """Fetch one rendition, joining bounded VOD segments without SRT conversion."""
    deadline = time.monotonic() + 30
    raw = get(url)
    text = raw.decode('utf-8-sig')
    init_url = None
    if not text.lstrip().startswith('#EXTM3U'):
        segments = [(url, 0.0, False, raw)]
    else:
        segments, current, duration, discontinuity = [], 0.0, 0.0, False
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('#EXT-X-KEY:') and attributes(line.split(':', 1)[1]).get('METHOD') != 'NONE':
                raise ValueError('Sottotitoli HLS cifrati non supportati')
            if line.startswith('#EXT-X-BYTERANGE:'):
                raise ValueError('Sottotitoli HLS byte-range non supportati')
            if line.startswith('#EXT-X-MAP:'):
                attr = attributes(line.split(':', 1)[1])
                if attr.get('BYTERANGE'):
                    raise ValueError('Sottotitoli HLS byte-range non supportati')
                init_url = urllib.parse.urljoin(url, attr['URI']) if attr.get('URI') else None
            elif line.startswith('#EXTINF:'):
                duration = float(line.split(':', 1)[1].split(',')[0])
                if duration < 0:
                    raise ValueError('Durata segmento non valida')
            elif line == '#EXT-X-DISCONTINUITY':
                discontinuity = True
            elif line and not line.startswith('#'):
                segments.append((urllib.parse.urljoin(url, line), current, discontinuity, None))
                current += duration
                duration, discontinuity = 0.0, False
        if not segments or len(segments) > MAX_SEGMENTS:
            raise ValueError('Numero segmenti sottotitoli HLS non supportato')
    initialization = get(init_url).decode('utf-8-sig') if init_url else ''
    collected, base_pts, total_bytes, styles = [], None, len(raw) + len(initialization.encode('utf-8')), []
    for segment, timeline, discontinuity, content in segments:
        if time.monotonic() > deadline:
            raise ValueError('Tempo limite sottotitoli HLS superato')
        content = content if content is not None else get(segment)
        total_bytes += len(content)
        if total_bytes > MAX_BYTES:
            raise ValueError('Sottotitoli HLS troppo grandi')
        text = initialization + '\n' + content.decode('utf-8-sig')
        if '<html' in text.lower() or not text.lstrip().startswith('WEBVTT'):
            raise ValueError('Risposta non WebVTT al posto dei sottotitoli')
        parsed = cues(text)
        if len(segments) == 1 and 'X-TIMESTAMP-MAP' not in text and parsed:
            return text.lstrip()  # Preserve the original WebVTT, including styling.
        offset = 0.0
        mapping = re.search(r'X-TIMESTAMP-MAP=([^\r\n]+)', text)
        if mapping:
            fields = dict(part.strip().split(':', 1) for part in mapping[1].split(',') if ':' in part)
            try:
                pts, local = int(fields['MPEGTS']) / 90000.0, seconds(fields['LOCAL'])
            except (KeyError, ValueError):
                raise ValueError('Mappa timestamp WebVTT non valida')
            if base_pts is None or discontinuity:
                base_pts = pts - timeline
            wrap = (2 ** 33) / 90000.0
            pts += round((base_pts + timeline - pts) / wrap) * wrap
            offset = pts - base_pts - local
        for block in re.split(r'\n[ \t]*\n', text.replace('\r', '').strip()):
            if block.startswith(('STYLE\n', 'REGION\n')) and block not in styles:
                styles.append(block)
        for start, end, settings, body in parsed:
            start, end = start + offset, end + offset
            if end > 0:
                if offset:
                    body = re.sub(r'<(' + TIME + ')>', lambda m: '<' + timestamp(seconds(m[1]) + offset) + '>', body)
                collected.append((round(max(start, 0), 3), round(end, 3), settings, body))
    unique = sorted(set(collected))
    if not unique:
        raise ValueError('Traccia WebVTT senza sottotitoli utilizzabili')
    blocks = styles + ['%d\n%s --> %s%s\n%s' % (i, timestamp(start), timestamp(end), settings, body)
                       for i, (start, end, settings, body) in enumerate(unique, 1)]
    return 'WEBVTT\n\n' + '\n\n'.join(blocks) + '\n'
