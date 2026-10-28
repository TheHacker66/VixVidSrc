"""Kodi catalog routes. Resolver playback remains handled by default.py."""
import os
import sqlite3
from urllib.parse import urlencode
import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs
from tmdb import TMDb, CatalogError, media_summary, playback_id, image
from catalog_store import Store

LABELS = {'movie': 'Film', 'tv': 'Serie TV', 'multi': 'Film e serie TV', 'all': 'Tutti'}
LISTS = {'movie': [('Popolari', 'popular'), ('Più votati', 'top_rated'), ('Al cinema', 'now_playing'), ('In arrivo', 'upcoming')],
         'tv': [('Popolari', 'popular'), ('Più votate', 'top_rated'), ('In onda', 'on_the_air')]}


class Catalog:
    def __init__(self, addon, base, handle):
        self.addon, self.base, self.handle = addon, base, handle
        self.dialog = xbmcgui.Dialog()
        self.api = TMDb(addon.getSetting('tmdb_token'), addon.getSetting('tmdb_key'), addon.getSetting('tmdb_language'))
        profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        self.store = Store(os.path.join(profile, 'catalogo.sqlite'))
        self.keys = self.store.favorite_keys()

    def url(self, action, **params):
        return self.base + '?' + urlencode(dict(params, action=action))

    def command(self, action, **params):
        return 'RunPlugin(%s)' % self.url(action, **params)

    def item(self, label, action, folder=True, art=None, info=None, context=None, **params):
        li = xbmcgui.ListItem(label=label)
        if art:
            li.setArt({k: v for k, v in art.items() if v})
        if info:
            li.setInfo('video', info)
        if not folder:
            li.setProperty('IsPlayable', 'true' if action == 'play' else 'false')
        menu = list(context or [])
        if action == 'play':
            for source, name in (('vixsrc', 'VixSrc'), ('vidsrc', 'VidSrc')):
                menu.append(('Riproduci con ' + name, 'PlayMedia(%s)' % self.url('play', **dict(params, source=source))))
        if menu:
            li.addContextMenuItems(menu)
        xbmcplugin.addDirectoryItem(self.handle, self.url(action, **params), li, folder)

    def favorite_context(self, kind, media_id):
        exists = (kind, int(media_id)) in self.keys
        return [('Rimuovi dai preferiti' if exists else 'Aggiungi ai preferiti',
                 self.command('cat_fav_remove' if exists else 'cat_fav_add', type=kind, id=media_id))]

    def media(self, summary, mixed=False):
        kind, media_id = summary['media_type'], summary['id']
        title, date = summary['title'], summary['date']
        label = title + (' (%s)' % date[:4] if date else '')
        if mixed:
            label += ' · ' + LABELS[kind]
        info = {'title': title, 'plot': summary['overview'], 'mediatype': 'movie' if kind == 'movie' else 'tvshow', 'rating': float(summary['vote_average'])}
        if date[:4].isdigit():
            info['year'] = int(date[:4])
        self.item(label, 'cat_details', art={'poster': image(summary['poster_path']), 'thumb': image(summary['poster_path']), 'fanart': image(summary['backdrop_path'], 'w1280')},
                  info=info, context=self.favorite_context(kind, media_id), type=kind, id=media_id)

    def end(self, content='files', success=True):
        xbmcplugin.setContent(self.handle, content)
        xbmcplugin.endOfDirectory(self.handle, succeeded=success, cacheToDisc=False)

    def browse(self, q):
        kind, category = q.get('type', 'movie'), q.get('category', 'popular')
        if kind not in LISTS or category not in dict((v, k) for k, v in LISTS[kind]):
            raise CatalogError('Categoria non valida.')
        page = max(1, min(500, int(q.get('page', 1))))
        data = self.api.get(kind + '/' + category, page=page)
        for entry in data.get('results', []):
            self.media(media_summary(entry, kind))
        if page < min(int(data.get('total_pages', 1)), 500):
            self.item('Pagina successiva →', 'cat_browse', type=kind, category=category, page=page + 1)
        self.end('movies' if kind == 'movie' else 'tvshows')

    def search(self, q):
        kind = q.get('type', 'multi')
        if kind not in ('movie', 'tv', 'multi'):
            raise CatalogError('Tipo ricerca non valido.')
        query = q.get('query') or self.dialog.input('Cerca ' + LABELS[kind].lower())
        query = ' '.join(query.split()).strip()[:250]
        if not query:
            self.end()
            return
        page = max(1, min(500, int(q.get('page', 1))))
        data = self.api.get('search/' + kind, query=query, page=page, include_adult='false')
        self.store.remember(kind, query)
        count = 0
        for entry in data.get('results', []):
            media_type = entry.get('media_type') if kind == 'multi' else kind
            if media_type not in ('movie', 'tv'):
                continue
            self.media(media_summary(entry, media_type), mixed=kind == 'multi')
            count += 1
        if not count:
            self.dialog.notification('Ricerca TMDb', 'Nessun film o serie in questa pagina.')
        if page < min(int(data.get('total_pages', 1)), 500):
            self.item('Pagina successiva →', 'cat_search', type=kind, query=query, page=page + 1)
        self.end('movies' if kind == 'movie' else 'tvshows' if kind == 'tv' else 'videos')

    def details(self, q):
        kind, media_id = q['type'], int(q['id'])
        if kind not in ('movie', 'tv'):
            raise CatalogError('Tipo non valido.')
        data = self.api.get('%s/%d' % (kind, media_id), append_to_response='external_ids')
        summary = media_summary(data, kind)
        art = {'poster': image(summary['poster_path']), 'fanart': image(summary['backdrop_path'], 'w1280')}
        ctx = self.favorite_context(kind, media_id)
        if kind == 'movie':
            info = {'title': summary['title'], 'plot': summary['overview'], 'mediatype': 'movie'}
            self.item('▶ Riproduci · ' + summary['title'], 'play', folder=False, art=art, info=info, context=ctx, type='movie', id=playback_id(data))
        else:
            for season in data.get('seasons', []):
                number = season.get('season_number')
                # The working resolver expects positive seasons; specials omitted.
                if number is None or number < 1:
                    continue
                self.item(season.get('name') or 'Stagione %d' % number, 'cat_episodes',
                          art={'poster': image(season.get('poster_path') or summary['poster_path']), 'fanart': art['fanart']},
                          info={'title': season.get('name') or '', 'plot': season.get('overview') or summary['overview'], 'mediatype': 'season', 'season': number},
                          context=ctx, id=media_id, season=number, source=playback_id(data), title=summary['title'])
        self.item('Rimuovi dai preferiti' if (kind, media_id) in self.keys else 'Aggiungi ai preferiti',
                  'cat_fav_remove' if (kind, media_id) in self.keys else 'cat_fav_add', type=kind, id=media_id)
        self.end('seasons' if kind == 'tv' else 'movies')

    def episodes(self, q):
        data = self.api.get('tv/%d/season/%d' % (int(q['id']), int(q['season'])))
        for ep in data.get('episodes', []):
            number = ep.get('episode_number')
            if not number or number < 1:
                continue
            season = int(q['season'])
            title = ep.get('name') or 'Episodio %d' % number
            self.item('S%02dE%02d · %s' % (season, number, title), 'play', folder=False,
                      art={'thumb': image(ep.get('still_path'), 'w500')},
                      info={'title': title, 'plot': ep.get('overview') or '', 'mediatype': 'episode', 'season': season, 'episode': number, 'tvshowtitle': q.get('title', '')},
                      type='tv', id=q.get('source') or q['id'], season=season, episode=number)
        self.end('episodes')

    def mutate(self, action, q):
        if action == 'cat_fav_add':
            kind, media_id = q['type'], int(q['id'])
            if kind not in ('movie', 'tv'):
                raise CatalogError('Tipo non valido.')
            data = self.api.get('%s/%d' % (kind, media_id))
            self.store.add_favorite(media_summary(data, kind))
            self.dialog.notification('Preferiti', 'Titolo aggiunto')
        elif action == 'cat_fav_remove':
            self.store.remove_favorite(q['type'], q['id'])
            self.dialog.notification('Preferiti', 'Titolo rimosso')
        elif action == 'cat_search_remove':
            self.store.remove_search(q['type'], q['query'])
        elif action == 'cat_search_clear':
            if not self.dialog.yesno('Ricerche recenti', 'Eliminare tutte le ricerche salvate?'):
                return
            self.store.clear_searches()
        if self.handle < 0:
            xbmc.executebuiltin('Container.Refresh')

    def dispatch(self, q):
        action = q.get('action', '')
        if action in ('cat_fav_add', 'cat_fav_remove', 'cat_search_remove', 'cat_search_clear'):
            self.mutate(action, q)
            # RunPlugin has no directory handle. Clickable folder actions do.
            if self.handle >= 0:
                self.keys = self.store.favorite_keys()
                destination = 'cat_details' if action in ('cat_fav_add', 'cat_fav_remove') else 'cat_history'
                self.dispatch(dict(q, action=destination))
        elif action == 'cat_menu':
            kind = q['type']
            self.item('Cerca ' + LABELS[kind], 'cat_search', type=kind)
            for label, category in LISTS[kind]:
                self.item(label, 'cat_browse', type=kind, category=category)
            self.end()
        elif action == 'cat_browse':
            self.browse(q)
        elif action == 'cat_search':
            self.search(q)
        elif action == 'cat_details':
            self.details(q)
        elif action == 'cat_episodes':
            self.episodes(q)
        elif action == 'cat_favorites':
            kind = q.get('type', 'all')
            for entry in self.store.favorites(kind):
                self.media(entry, mixed=kind == 'all')
            self.end('movies' if kind == 'movie' else 'tvshows' if kind == 'tv' else 'videos')
        elif action == 'cat_history':
            for entry in self.store.searches():
                kind, query = entry['kind'], entry['query']
                self.item(query + ' · ' + LABELS[kind], 'cat_search', type=kind, query=query,
                          context=[('Elimina ricerca', self.command('cat_search_remove', type=kind, query=query))])
            self.item('Svuota cronologia ricerche', 'cat_search_clear')
            self.end()
        elif action == 'cat_about':
            self.dialog.ok('Catalogo TMDb', 'This product uses the TMDB API but is not endorsed or certified by TMDB.\n\nMetadati e immagini: The Movie Database (themoviedb.org).\nPreferiti e ricerche sono salvati solo nel profilo Kodi di questo dispositivo.\nLa presenza nel catalogo non garantisce la disponibilità sul servizio video.')
            self.end()
        else:
            raise CatalogError('Pagina catalogo non valida.')


def route(addon, base, handle, query):
    catalog = None
    try:
        catalog = Catalog(addon, base, handle)
        catalog.dispatch(query)
    except (CatalogError, sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        # Never include exception text from network/SQL in Kodi logs.
        import sys
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, CatalogError) else 'Impossibile leggere il catalogo o i dati locali.'
        xbmcgui.Dialog().ok('Catalogo TMDb', message)
        if handle >= 0:
            xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
    finally:
        if catalog:
            catalog.store.close()
