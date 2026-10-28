"""Experimental resolver following the user-provided player JavaScript.

No saved tokens, embedded keys, browser challenge bypass, or remote JS execution.
"""
import base64
import html
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) Gecko/20100101 Firefox/159.0'
BASE = 'https://vidsrc.sh'


class ResolverError(Exception):
    pass


def wasm_helper(node_path='node', payload=None, self_test=False):
    executable = shutil.which(node_path)
    if not executable:
        raise ResolverError('Node.js non trovato: impostare il percorso nelle impostazioni')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    args = [executable, '--max-old-space-size=128', os.path.join(os.path.dirname(__file__), 'decrypt.js')]
    if self_test:
        args.append('--self-test')
    try:
        proc = subprocess.run(args, input=json.dumps(payload or {}).encode('utf-8'),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, creationflags=flags)
    except subprocess.TimeoutExpired:
        raise ResolverError('Tempo limite WASM superato (20 secondi)')
    except OSError:
        raise ResolverError('Impossibile avviare Node.js: controllare percorso, permessi e architettura')
    if proc.returncode:
        try:
            details = json.loads(proc.stderr)
            if not isinstance(details, dict):
                details = {}
        except (ValueError, UnicodeError):
            details = {}
        # Whitelist diagnostic symbols; no remote payload or raw stderr.
        fields = []
        for key in ('phase', 'category', 'error', 'node', 'arch', 'platform'):
            value = str(details.get(key, ''))
            if value and re.fullmatch(r'[a-zA-Z0-9_.-]{1,60}', value):
                fields.append('%s=%s' % (key, value))
        detail = '; '.join(fields) or 'Node terminato prima della diagnostica; eseguire Test Node/WASM'
        raise ResolverError('WASM fallito: exit=%s; %s' % (proc.returncode, detail))
    try:
        result = json.loads(proc.stdout)
    except (ValueError, UnicodeError):
        raise ResolverError('Risultato helper WASM non valido')
    if self_test:
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise ResolverError('Test Node/WASM non riuscito')
        return result
    if not isinstance(result, list):
        raise ResolverError('Lista flussi WASM non valida')
    return result


def origin(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ResolverError('URL HTTPS non valido')
    return p.scheme + '://' + p.netloc


def config_from_html(text, name='CONFIG'):
    if name not in ('CONFIG', 'CFG'):
        raise ValueError('Nome configurazione non valido')
    key = re.escape(name)
    m = re.search(r'''window\s*(?:\.\s*%s|\[\s*["']%s["']\s*\])\s*=\s*''' % (key, key), text)
    if not m:
        raise ResolverError('CONFIG assente: pagina modificata o verifica browser richiesta')
    try:
        value, _ = json.JSONDecoder().raw_decode(text[m.end():].lstrip())
    except (ValueError, TypeError):
        raise ResolverError('CONFIG non è JSON valido')
    if not isinstance(value, dict):
        raise ResolverError('CONFIG inattesa')
    return value


def redact_diagnostic(text):
    # Best-effort redaction for known credentials; inspect before sharing.
    text = re.sub(r'''(?i)(["']?(?:apiToken|api_token|token|authorization|cookie)["']?\s*[:=]\s*)(["'])(.*?)\2''',
                  lambda m: m[1] + m[2] + '[REDACTED]' + m[2], text)
    text = re.sub(r'(?i)([?&](?:vs|api_token|token)=)[^\s"\'<> &]+', r'\1[REDACTED]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?', '[REDACTED]', text)
    return text


def add_params(url, **params):
    p = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    q = [(k, v) for k, v in q if k not in params]
    q.extend((k, str(v)) for k, v in params.items())
    return urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(q)))


def apply_token(url, token):
    if not token:
        return url
    if '__TOKEN__' in url:
        return url.replace('__TOKEN__', urllib.parse.quote(token, safe=''))
    return add_params(url, token=token)


def parse_token(text):
    text = text.strip()
    try:
        value = json.loads(text)
    except ValueError:
        return text
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for k in ('token', 'data', 'string', 'result'):
            if isinstance(value.get(k), str) and value[k]:
                return value[k]
    return ''


class Resolver:
    def __init__(self, node_path='node', progress=None, diagnostic=None):
        self.node = node_path
        self.progress = progress or (lambda message: None)
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        self.player = ''
        self.last_response = {}
        self.diagnostic = diagnostic
        self.subtitle_context = {}

    def request(self, url, referer=BASE + '/', accept='*/*', limit=8 * 1024 * 1024):
        origin(url)
        headers = {'User-Agent': UA, 'Accept': accept, 'Referer': referer}
        if accept == 'application/json':
            headers['Origin'] = origin(referer)
        req = urllib.request.Request(url, headers=headers)
        try:
            with self.http.open(req, timeout=20) as r:
                origin(r.geturl())
                self.last_response = {'host': urllib.parse.urlsplit(r.geturl()).hostname,
                                      'status': r.status, 'content_type': r.headers.get_content_type(),
                                      'final_url': r.geturl()}
                data = r.read(limit + 1)
                if len(data) > limit:
                    raise ResolverError('Risposta troppo grande')
                return data
        except urllib.error.HTTPError as e:
            raise ResolverError('HTTP %s da %s; accesso negato, token scaduto o verifica browser' % (e.code, urllib.parse.urlsplit(url).hostname))
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ResolverError('Errore di rete da %s' % urllib.parse.urlsplit(url).hostname)

    def get_json(self, url, referer):
        try:
            return json.loads(self.request(url, referer, 'application/json'))
        except ValueError:
            raise ResolverError('Risposta API non JSON')

    def player_config(self, referer, stage):
        return self._player_config(referer, stage, set())

    def _player_config(self, referer, stage, visited):
        if self.player in visited or len(visited) >= 3:
            raise ResolverError('Ciclo o troppi passaggi tra landing e player')
        visited.add(self.player)
        self.last_response = {}
        raw = self.request(self.player, referer,
                           'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8')
        text = raw.decode('utf-8-sig', 'replace')
        self.player = self.last_response.get('final_url', self.player)
        try:
            return config_from_html(text)
        except ResolverError as error:
            # The landing creates its iframe only on Play, so no static iframe
            # tag exists. Follow only its explicit same-origin CFG.playerUrl.
            try:
                landing = config_from_html(text, 'CFG')
            except ResolverError:
                landing = {}
            target = landing.get('playerUrl')
            if isinstance(target, str) and target:
                target = urllib.parse.urljoin(self.player, target)
                if origin(target) != origin(self.player):
                    raise ResolverError('CFG.playerUrl punta a un dominio diverso: caricamento interrotto')
                parent = self.player
                self.player = target
                self.progress('Caricamento player dalla pagina iniziale')
                return self._player_config(origin(parent) + '/', stage + ' > player', visited)
            low = text.lower()
            checks = [tag for tag, marker in (
                ('turnstile', 'challenges.cloudflare.com/turnstile'),
                ('cf-challenge', 'cf-chl-'), ('challenge-platform', '/cdn-cgi/challenge-platform/'),
                ('captcha', 'g-recaptcha'), ('access-denied', 'access denied')) if marker in low]
            # Report structural facts only: never include raw HTML, query strings,
            # page titles, cookies, tokens or user IP addresses in diagnostics.
            meta = self.last_response
            detail = ('Fase=%s; host=%s; HTTP=%s; tipo=%s; byte=%d; iframe=%d; '
                      'CONFIG=%s; segnali=%s') % (
                          stage, meta.get('host', urllib.parse.urlsplit(self.player).hostname),
                          meta.get('status', '?'), meta.get('content_type', '?'), len(raw),
                          len(re.findall(r'<iframe\b', low)),
                          'parola presente' if 'config' in low else 'parola assente', ','.join(checks) or 'nessuno')
            if self.diagnostic:
                try:
                    self.diagnostic(detail + '\n\n' + redact_diagnostic(text))
                    detail += '\nRisposta salvata: usa Esporta diagnostica nel menu addon.'
                except OSError:
                    detail += '\nImpossibile salvare la risposta diagnostica.'
            raise ResolverError('%s\n%s' % (error, detail))

    def streams(self, payload):
        data = payload.get('data')
        if not isinstance(data, dict):
            raise ResolverError('Risposta API priva di data')
        streams = data.get('stream_urls')
        if isinstance(streams, list):
            return streams
        vs = payload.get('vs') or {}
        if not isinstance(streams, str) or not isinstance(vs, dict):
            raise ResolverError('Flussi o metadati WASM assenti')
        if vs.get('wasm_url'):
            raw_wasm = self.request(vs['wasm_url'], self.player)
        elif vs.get('wasm'):
            try:
                raw_wasm = base64.b64decode(vs['wasm'], validate=True)
            except (ValueError, TypeError):
                raise ResolverError('Modulo WASM inline non valido (Base64)')
        else:
            raise ResolverError('Modulo WASM assente')
        if not raw_wasm.startswith(b'\x00asm\x01\x00\x00\x00'):
            raise ResolverError('Risposta del server non è un modulo WASM valido (byte=%d)' % len(raw_wasm))
        wasm = base64.b64encode(raw_wasm).decode('ascii')
        return wasm_helper(self.node, {'wasm': wasm, 'encrypted': streams})

    def resolve(self, media_type, media_id, season=1, episode=1):
        if media_type not in ('movie', 'tv') or not re.fullmatch(r'(?:tt\d+|\d+)', media_id):
            raise ResolverError('Tipo o ID non valido')
        if int(season) < 1 or int(episode) < 1:
            raise ResolverError('Stagione ed episodio devono essere positivi')
        self.progress('Richiesta player')
        args = {'type': media_type, 'id': media_id}
        if media_type == 'tv':
            args.update(season=season, episode=episode)
        entry = BASE + '/vs_src.php?' + urllib.parse.urlencode(args)
        info = self.get_json(entry, BASE + '/')
        if not isinstance(info, dict) or not isinstance(info.get('src'), str):
            raise ResolverError('Risposta vs_src senza src')
        self.player = html.unescape(urllib.parse.urljoin(BASE, info['src']))
        origin(self.player)
        self.progress('Lettura configurazione player')
        config = self.player_config(BASE + '/', 'player iniziale')
        if config.get('turnstile'):
            raise ResolverError('Il servizio richiede una verifica browser; il prototipo si arresta')
        # Match the player's refresh behavior; always use the newly issued token.
        if config.get('apiTokenRefresh'):
            config = self.player_config(self.player, 'rinnovo token')
        if config.get('turnstile'):
            raise ResolverError('Il servizio richiede una verifica browser; il prototipo si arresta')
        if media_type == 'tv':
            api = config.get('streamBase')
            if not api:
                raise ResolverError('streamBase assente')
            api = add_params(api, season=season, episode=episode, stream_urls='')
        else:
            api = config.get('api')
            if not api:
                raise ResolverError('CONFIG.api assente per il film')
        if config.get('apiToken'):
            api = add_params(api, api_token=config['apiToken'])
        self.progress('Richiesta e decifratura flussi')
        payload = self.get_json(api, origin(self.player) + '/')
        if not isinstance(payload, dict) or str(payload.get('status_code', payload.get('status', '200'))) != '200':
            raise ResolverError('API: contenuto non disponibile o token rifiutato')
        self.subtitle_context = {
            'data': payload.get('data') or {}, 'default_subs': payload.get('default_subs') or [],
            'config': config, 'player': self.player,
            'cache': urllib.parse.urljoin(self.player, config.get('cacheBase') or '/embed/iframe_player/cache.php'),
            'media_key': '%s:%s:%s:%s' % (media_type, media_id, season, episode)}
        streams = [s for s in self.streams(payload) if isinstance(s, str) and s]
        for raw in streams:
            self.progress('Verifica playlist')
            try:
                host = origin(raw)
                try:
                    token = parse_token(self.request(host + '/generate.php', origin(self.player) + '/').decode('utf-8'))
                except ResolverError:
                    token = ''  # Optional in the original player too.
                url = apply_token(raw, token)
                content = self.request(url, origin(self.player) + '/', limit=2 * 1024 * 1024)
                if not content.lstrip(b'\xef\xbb\xbf \r\n\t').startswith(b'#EXTM3U'):
                    continue
                return url, {'User-Agent': UA, 'Referer': origin(self.player) + '/'}, payload['data'].get('title', media_id)
            except ResolverError:
                continue
        raise ResolverError('Nessuna playlist HLS valida; accesso negato o sorgenti non disponibili')
