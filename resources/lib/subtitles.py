"""Subtitle tracks and search following the observed VidSrc subtitles.js flow.

Conversion is local: Kodi consumes SRT/VTT/ASS without the browser's VTT proxy.
"""
import gzip
import hashlib
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile

LIMIT = 4 * 1024 * 1024
LANGS = {'it': 'ita', 'en': 'eng', 'fr': 'fre', 'de': 'ger', 'es': 'spa', 'pt': 'por',
         'ru': 'rus', 'ja': 'jpn', 'ko': 'kor', 'zh': 'chi', 'ar': 'ara', 'nl': 'dut',
         'el': 'ell', 'pl': 'pol', 'tr': 'tur', 'uk': 'ukr', 'cs': 'cze', 'ro': 'rum',
         'sv': 'swe', 'da': 'dan', 'fi': 'fin', 'no': 'nor', 'he': 'heb', 'hi': 'hin',
         'hu': 'hun', 'id': 'ind', 'th': 'tha', 'vi': 'vie', 'sk': 'slo', 'hr': 'hrv',
         'sr': 'scc', 'bg': 'bul', 'fa': 'per', 'bn': 'ben', 'ta': 'tam', 'te': 'tel'}
ALIASES = {'italian': 'ita', 'italiano': 'ita', 'english': 'eng', 'french': 'fre',
           'fra': 'fre', 'deu': 'ger', 'zho': 'chi', 'ces': 'cze', 'ron': 'rum', 'nld': 'dut'}


def language(value):
    value = str(value or '').strip().lower()
    if value in ALIASES:
        return ALIASES[value]
    value = value.split('-')[0].split('_')[0]
    return LANGS.get(value, value if re.fullmatch('[a-z]{3}', value) else 'und')


def languages(value):
    result = []
    for code in str(value or 'it,en').split(','):
        code = language(code)
        if code != 'und' and code not in result:
            result.append(code)
    return result[:3] or ['ita', 'eng']


def secure_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme == 'http':
        url = urllib.parse.urlunsplit(p._replace(scheme='https'))
        p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('URL sottotitolo non valido')
    return url


def fetch(url, headers=None):
    req = urllib.request.Request(secure_url(url), headers=dict({'User-Agent': 'Kodi-VidSrc/0.3.0', 'Accept': '*/*'}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=8) as r:
        data = r.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Sottotitolo troppo grande')
    return data


def subtitle_text(raw, encoding='utf-8'):
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(LIMIT + 1)
    elif raw.startswith(b'PK\x03\x04'):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = [x for x in archive.infolist() if not x.is_dir() and x.filename.lower().endswith(('.srt', '.vtt', '.ass', '.ssa')) and x.file_size <= LIMIT]
            if not entries:
                raise ValueError('Archivio senza sottotitoli supportati')
            with archive.open(entries[0]) as stream:
                raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Sottotitolo decompresso troppo grande')
    encodings = ['utf-8-sig', encoding or 'utf-8', 'cp1252']
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        encodings.insert(0, 'utf-16')
    text = None
    for enc in encodings:
        try:
            text = raw.decode(enc)
            break
        except (UnicodeError, LookupError):
            continue
    if text is None:
        raise ValueError('Codifica sottotitolo non riconosciuta')
    if '[Script Info]' in text and '[Events]' in text:
        return text, '.ass'
    # Reject HTML error pages even if they contain a timestamp-like string.
    if '<html' in text.lower() or '<!doctype html' in text.lower() or not re.search(r'\d{1,2}:\d{2}(?::\d{2})?[.,]\d+\s+-->\s+', text):
        raise ValueError('Risposta non riconosciuta come sottotitolo')
    return text, '.vtt' if text.lstrip().startswith('WEBVTT') else '.srt'


def score(filename, subtitle):
    source = os.path.basename(filename or '').lower()
    name = (subtitle.get('SubFileName') or subtitle.get('MovieReleaseName') or '').lower()
    score = 0
    token = lambda s: set(re.findall(r'[a-z0-9]{3,}', s))
    words = token(source)
    if words:
        score += 35 * len(words & token(name)) / len(words)
    ep = re.search(r's(\d{1,2})e(\d{1,2})', source)
    other = re.search(r's(\d{1,2})e(\d{1,2})', name)
    if ep and other:
        score += 25 if tuple(map(int, ep.groups())) == tuple(map(int, other.groups())) else -60
    for pattern, weight in ((r'(?:2160|1080|720|480)p', 10), (r'blu-?ray|web-?dl|webrip|hdtv', 25), (r'x26[45]|hevc', 5)):
        a, b = re.search(pattern, source), re.search(pattern, name)
        if a and b and a[0] == b[0]:
            score += weight
    group = re.search(r'[-\[]([a-z0-9]+)\]?\.[a-z0-9]+$', source)
    if group and group[1] in name:
        score += 20
    return score


class Subtitles:
    def __init__(self, context, directory, preferred='it,en', network=fetch):
        self.context, self.directory, self.preferred = context, directory, languages(preferred)
        self.network = network
        self.failures = 0

    def get(self, url, headers=None):
        source = urllib.parse.urlsplit(self.context.get('player', ''))
        request_headers = {}
        if source.scheme == 'https' and source.netloc:
            request_headers['Referer'] = source.scheme + '://' + source.netloc + '/'
        request_headers.update(headers or {})
        return self.network(url, request_headers)

    def tracks(self):
        data, config = self.context.get('data') or {}, self.context.get('config') or {}
        entries = self.context.get('default_subs') or data.get('default_subs') or []
        result = []
        if config.get('subUrl'):
            entries = [{'url': config['subUrl'], 'lang': config.get('subLang'), 'label': config.get('subLabel') or 'Personalizzato'}] + list(entries)
        for sub in entries:
            if not isinstance(sub, dict) or not isinstance(sub.get('url'), str):
                continue
            code = language(sub.get('code') or sub.get('lang'))
            url = urllib.parse.urljoin(self.context.get('player', ''), sub['url'])
            result.append({'url': url, 'lang': code, 'label': sub.get('label') or sub.get('lang') or code, 'encoding': 'utf-8'})
        # Group preferred languages first; keep other default tracks available.
        return sorted(result, key=lambda s: self.preferred.index(s['lang']) if s['lang'] in self.preferred else 10)

    def search(self, lang):
        data, config = self.context.get('data') or {}, self.context.get('config') or {}
        imdb = re.sub(r'^tt', '', str(config.get('imdb') or data.get('imdb_id') or ''), flags=re.I)
        if not imdb.isdigit():
            return []
        url = 'https://rest.opensubtitles.org/search'
        season, episode = config.get('season') or data.get('season'), config.get('episode') or data.get('episode')
        if season and episode:
            url += '/episode-%d/imdbid-%s/season-%d' % (int(episode), imdb, int(season))
        else:
            url += '/imdbid-' + imdb
        url += '/sublanguageid-' + lang
        try:
            # Public client identifier used by the observed VidSrc player.
            rows = json.loads(self.get(url, {'X-User-Agent': 'trailers.to-UA', 'Accept': 'application/json'}))
            if not isinstance(rows, list):
                return []
            rows = [s for s in rows if isinstance(s, dict) and s.get('SubDownloadLink')]
            def downloads(row):
                try: return int(row.get('SubDownloadsCnt') or 0)
                except (ValueError, TypeError): return 0
            rows.sort(key=lambda s: (score(data.get('file_name'), s), downloads(s)), reverse=True)
            return [{'url': s['SubDownloadLink'], 'lang': lang, 'label': s.get('SubFileName') or s.get('MovieReleaseName') or lang,
                     'encoding': s.get('SubEncoding') or 'utf-8', 'opensubtitles': True} for s in rows[:30]]
        except (OSError, ValueError, TypeError):
            self.failures += 1
            return []

    def candidates(self, manual=False):
        result = self.tracks()
        for lang in self.preferred:
            defaults = [s for s in result if s['lang'] == lang]
            if manual or not defaults:
                result.extend(self.search(lang))
        seen = set()
        unique = []
        for sub in result:
            if sub['url'] not in seen:
                unique.append(sub)
                seen.add(sub['url'])
        return unique

    def download(self, sub):
        os.makedirs(self.directory, exist_ok=True)
        key = hashlib.sha256((self.context.get('media_key', '') + sub['url']).encode()).hexdigest()[:24]
        prefix = os.path.join(self.directory, key + '.' + sub['lang'])
        for ext in ('.srt', '.vtt', '.ass'):
            path = prefix + ext
            if os.path.isfile(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
                return path
        url = sub['url']
        # Use VidSrc's existing converted copy when available; otherwise decode
        # the client-downloaded original locally, without POSTing to the server.
        if sub.get('opensubtitles'):
            match = re.search(r'/filead/(\d+)', url, re.I)
            cache = self.context.get('cache')
            if match and cache:
                try:
                    request_url = cache + ('&' if '?' in cache else '?') + 'action=get&file_id=' + match[1]
                    cached = json.loads(self.get(request_url))
                    if cached.get('success') and cached.get('vtt_url'):
                        url = urllib.parse.urljoin(cache, cached['vtt_url'])
                except (OSError, ValueError, TypeError, AttributeError):
                    pass
        try:
            text, ext = subtitle_text(self.get(url), sub.get('encoding'))
        except (OSError, ValueError, EOFError, zipfile.BadZipFile):
            if url == sub['url']:
                raise
            text, ext = subtitle_text(self.get(sub['url']), sub.get('encoding'))
        path = prefix + ext
        temp = path + '.tmp'
        with open(temp, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        os.replace(temp, path)
        return path

    def automatic(self):
        result = []
        for lang in self.preferred:
            defaults = [s for s in self.tracks() if s['lang'] == lang]
            found = False
            for sub in defaults[:3]:
                try:
                    result.append(self.download(sub))
                    found = True
                    break
                except (OSError, ValueError, EOFError, zipfile.BadZipFile):
                    self.failures += 1
            if found:
                continue
            for sub in self.search(lang)[:3]:
                try:
                    result.append(self.download(sub))
                    break
                except (OSError, ValueError, EOFError, zipfile.BadZipFile):
                    self.failures += 1
        return result
