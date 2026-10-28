"""VixSrc API -> embed -> signed HLS, following its observed player code.

Only literal data is parsed. Remote JavaScript, ads and analytics are not run.
"""
import ast
import base64
import binascii
import html
import json
import re
import urllib.parse
from resolver import Resolver, ResolverError, UA, add_params, origin

VIX = 'https://vixsrc.to'


class Literal:
    """Restricted JS literal reader: dict/list/string/number/bool/null only."""
    token = re.compile(r'''\s*(?:(//[^\n]*(?:\n|$)|/\*.*?\*/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|([A-Za-z_$][\w$]*)|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([{}\[\]:,]))''', re.S)

    def __init__(self, text):
        self.text, self.pos = text, 0

    def next(self):
        while True:
            match = self.token.match(self.text, self.pos)
            if not match:
                raise ResolverError('VixSrc: configurazione player non riconosciuta')
            self.pos = match.end()
            if not match[1]:
                return next(g for g in match.groups()[1:] if g is not None)

    @staticmethod
    def string(token):
        if token.startswith('"'):
            return json.loads(token)
        # Input is exactly one quoted token, not an expression.
        return ast.literal_eval(token.replace('\\/', '/'))

    def value(self, first=None, depth=0):
        if depth > 20:
            raise ResolverError('VixSrc: configurazione troppo annidata')
        token = first if first is not None else self.next()
        if token in ('{', '['):
            result = {} if token == '{' else []
            end = '}' if token == '{' else ']'
            current = self.next()
            if current == end:
                return result
            while True:
                if token == '{':
                    key = self.string(current) if current.startswith(('"', "'")) else current
                    if not isinstance(key, str) or self.next() != ':':
                        raise ResolverError('VixSrc: proprietà player non valida')
                    result[key] = self.value(depth=depth + 1)
                else:
                    result.append(self.value(current, depth + 1))
                current = self.next()
                if current == end:
                    return result
                if current != ',':
                    raise ResolverError('VixSrc: separatore player non valido')
                current = self.next()
                if current == end:
                    return result
        if token.startswith(('"', "'")):
            return self.string(token)
        if token in ('true', 'false', 'null'):
            return {'true': True, 'false': False, 'null': None}[token]
        if re.fullmatch(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', token):
            return json.loads(token)
        raise ResolverError('VixSrc: valore dinamico non supportato nella configurazione')


def assignment(text, name, optional=False):
    match = re.search(r'window\s*\.\s*' + re.escape(name) + r'\s*=\s*', text)
    if not match:
        if optional:
            return None
        raise ResolverError('VixSrc: configurazione %s assente nel player' % name)
    try:
        return Literal(text[match.end():]).value()
    except (ValueError, SyntaxError):
        raise ResolverError('VixSrc: dati player non validi')


def playlist_urls(text, player, language='it'):
    master = assignment(text, 'masterPlaylist')
    if not isinstance(master, dict) or not isinstance(master.get('url'), str) or not isinstance(master.get('params'), dict):
        raise ResolverError('VixSrc: masterPlaylist non valida')
    params = {k: str(v) for k, v in master['params'].items() if isinstance(k, str) and isinstance(v, (str, int, float)) and v}
    # vixsrc player always adds h=1 and lang. Preserve its optional CDN choice.
    params.update(h='1', lang=language)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(player).query)
    if query.get('cdn'):
        params['cdn'] = query['cdn'][0]
    streams = assignment(text, 'streams', optional=True) or []
    urls = [master['url']]
    if isinstance(streams, list):
        streams = sorted([s for s in streams if isinstance(s, dict)], key=lambda s: not s.get('active'))
        urls.extend(s['url'] for s in streams if isinstance(s.get('url'), str))
    result = []
    for candidate in urls:
        url = urllib.parse.urljoin(player, candidate)
        if origin(url) != origin(player):
            raise ResolverError('VixSrc: playlist firmata su dominio inatteso')
        url = add_params(url, **params)
        if url not in result:
            result.append(url)
    return result


def manifest_has_subtitles(text):
    return any(line.startswith('#EXT-X-MEDIA:') and re.search(r'(?:^|,)TYPE=SUBTITLES(?:,|$)', line.split(':', 1)[1]) for line in text.splitlines())


class VixResolver(Resolver):
    def __init__(self, progress=None, diagnostic=None, audio_language='it'):
        super().__init__(progress=progress, diagnostic=diagnostic)
        self.audio_language = audio_language if re.fullmatch(r'[a-z]{2}', audio_language or '') else 'it'

    def resolve(self, media_type, media_id, season=1, episode=1):
        if media_type not in ('movie', 'tv') or not re.fullmatch(r'(?:tt\d+|\d+)', str(media_id)):
            raise ResolverError('VixSrc: tipo o ID non valido')
        season, episode = int(season), int(episode)
        if media_type == 'tv' and (season < 1 or episode < 1):
            raise ResolverError('VixSrc: stagione ed episodio devono essere positivi')
        route = '/movie/' + str(media_id) if media_type == 'movie' else '/tv/%s/%d/%d' % (media_id, season, episode)
        self.progress('VixSrc: richiesta player')
        landing = add_params(VIX + route, lang=self.audio_language)
        # The site's Next.js page calls this exact same-origin endpoint.
        response = self.get_json(add_params(VIX + '/api' + route, lang=self.audio_language), landing)
        if not isinstance(response, dict) or not isinstance(response.get('src'), str) or not response['src']:
            raise ResolverError('VixSrc: titolo non disponibile o risposta senza player')
        self.player = html.unescape(urllib.parse.urljoin(VIX, response['src']))
        if origin(self.player) != VIX:
            raise ResolverError('VixSrc: player su dominio inatteso')
        self.progress('VixSrc: lettura configurazione')
        raw = self.request(self.player, VIX + '/', 'text/html')
        self.player = self.last_response.get('final_url', self.player)
        if origin(self.player) != VIX:
            raise ResolverError('VixSrc: reindirizzamento player inatteso')
        text = raw.decode('utf-8-sig', 'replace')
        try:
            urls = playlist_urls(text, self.player, self.audio_language)
        except ResolverError:
            if self.diagnostic:
                # Do not export HTML signed URLs, asset parameters or tokens.
                try:
                    self.diagnostic('Fonte=VixSrc; fase=configurazione; byte=%d; masterPlaylist=%s' % (len(raw), 'parola presente' if 'masterPlaylist' in text else 'assente'))
                except OSError:
                    pass
            raise
        title = str(media_id)
        encoded = urllib.parse.parse_qs(urllib.parse.urlsplit(self.player).query).get('t', [''])[0]
        if encoded:
            try:
                title = base64.b64decode(encoded).decode('utf-8')[:250] or title
            except (ValueError, UnicodeError, binascii.Error):
                pass
        video = assignment(text, 'video', optional=True) or {}
        filename = (video.get('filename') or '') if isinstance(video, dict) else ''
        for url in urls:
            self.progress('VixSrc: verifica playlist')
            try:
                raw_manifest = self.request(url, VIX + '/', limit=2 * 1024 * 1024)
            except ResolverError:
                continue
            manifest = raw_manifest.decode('utf-8-sig', 'replace').lstrip()
            if not manifest.startswith('#EXTM3U'):
                continue
            imdb = str(media_id) if str(media_id).startswith('tt') else ''
            self.subtitle_context = {
                'player': self.player, 'media_key': 'vix:%s:%s:%d:%d' % (media_type, media_id, season, episode),
                'data': {'title': title, 'imdb_id': imdb, 'file_name': filename},
                'config': {'imdb': imdb, 'season': season if media_type == 'tv' else None,
                           'episode': episode if media_type == 'tv' else None},
                'default_subs': [], 'native_subtitles': manifest_has_subtitles(manifest)}
            headers = {'User-Agent': UA, 'Referer': VIX + '/', 'Origin': VIX}
            return url, headers, title
        raise ResolverError('VixSrc: nessuna playlist HLS disponibile; prova VidSrc')
