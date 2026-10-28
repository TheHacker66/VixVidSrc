"""Small TMDb v3 client. Credentials never appear in plugin URLs or logs."""
import json
import urllib.error
import urllib.parse
import urllib.request


class CatalogError(Exception):
    pass


class TMDb:
    def __init__(self, token='', api_key='', language='it-IT'):
        self.token = token.strip()
        self.api_key = api_key.strip()
        self.language = language.strip() or 'it-IT'

    def get(self, path, **params):
        if not self.token and not self.api_key:
            raise CatalogError('Configura il TMDb API Read Access Token oppure la API Key nelle impostazioni dell’addon.')
        params = dict(params, language=self.language)
        headers = {'Accept': 'application/json', 'User-Agent': 'Kodi-VidSrc-Catalog/0.2.0'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        else:
            params['api_key'] = self.api_key
        url = 'https://api.themoviedb.org/3/' + path.lstrip('/') + '?' + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
                raw = r.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise CatalogError('Risposta TMDb troppo grande.')
                data = json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise CatalogError('Credenziale TMDb non valida. Controlla token o API Key nelle impostazioni.')
            if e.code == 429:
                raise CatalogError('TMDb ha ricevuto troppe richieste. Riprova tra poco.')
            raise CatalogError('TMDb: errore HTTP %d.' % e.code)
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CatalogError('TMDb non raggiungibile. Controlla la connessione.')
        except ValueError:
            raise CatalogError('Risposta TMDb non valida.')
        if not isinstance(data, dict) or data.get('success') is False:
            raise CatalogError('TMDb non ha restituito dati validi.')
        return data


def media_summary(data, kind):
    if kind not in ('movie', 'tv'):
        raise ValueError('Tipo non valido')
    return {'id': int(data['id']), 'media_type': kind,
            'title': data.get('title') or data.get('name') or 'Senza titolo',
            'overview': data.get('overview') or '',
            'date': data.get('release_date') or data.get('first_air_date') or '',
            'poster_path': data.get('poster_path') or '',
            'backdrop_path': data.get('backdrop_path') or '',
            'vote_average': data.get('vote_average') or 0}


def playback_id(data):
    imdb = data.get('imdb_id') or (data.get('external_ids') or {}).get('imdb_id')
    return imdb if imdb else str(int(data['id']))


def image(path, size='w500'):
    return 'https://image.tmdb.org/t/p/' + size + path if path and path.startswith('/') else ''
