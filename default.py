import os
import sys
from urllib.parse import parse_qs, urlencode
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

ADDON = xbmcaddon.Addon()
sys.path.insert(0, os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('path')), 'resources', 'lib'))
from resolver import Resolver, ResolverError

HANDLE = int(sys.argv[1])
BASE = sys.argv[0]
DIALOG = xbmcgui.Dialog()
DIAGNOSTIC = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), 'risposta-player.txt')


def save_diagnostic(text):
    os.makedirs(os.path.dirname(DIAGNOSTIC), exist_ok=True)
    with open(DIAGNOSTIC, 'w', encoding='utf-8') as stream:
        stream.write(text)


def prepare_subtitles(resolver, progress):
    mode = ADDON.getSetting('subtitles_mode') or '0'
    if mode == '2':
        return []
    from subtitles import Subtitles
    profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    subs = Subtitles(resolver.subtitle_context, os.path.join(profile, 'subtitles'),
                     ADDON.getSetting('subtitles_languages') or 'it,en')
    progress.update(0, message='Ricerca sottotitoli')
    try:
        if mode == '1':
            candidates = subs.candidates(manual=True)
            labels = ['Senza sottotitoli'] + ['[%s] %s' % (s['lang'], s['label']) for s in candidates]
            chosen = DIALOG.select('Sottotitoli · scegli una versione', labels)
            files = [subs.download(candidates[chosen - 1])] if chosen > 0 else []
        else:
            files = subs.automatic()
        if not files and (mode == '0' or subs.failures):
            DIALOG.notification('Sottotitoli', 'Nessun sottotitolo esterno caricato; puoi continuare la riproduzione.')
        return files
    except Exception:
        xbmc.log('VidSrc: recupero sottotitoli fallito; avvio video', xbmc.LOGWARNING)
        DIALOG.notification('Sottotitoli', 'Recupero non riuscito; avvio del video senza sottotitoli esterni.')
        return []


def main():
    query = parse_qs(sys.argv[2].lstrip('?'))
    action = query.get('action', [''])[0]
    if action == 'wasm_test':
        from resolver import wasm_helper
        try:
            result = wasm_helper(ADDON.getSetting('node_path') or 'node', self_test=True)
            DIALOG.ok('Test Node/WASM', 'Test locale riuscito.\nNode: %s\nArchitettura Node: %s\nSistema: %s\nIl test non verifica il modulo remoto del servizio.' %
                      (result.get('node', '?'), result.get('arch', '?'), result.get('platform', '?')))
        except ResolverError as error:
            DIALOG.ok('Test Node/WASM', str(error))
        xbmcplugin.endOfDirectory(HANDLE)
        return
    if action.startswith('cat_'):
        from catalog_ui import route
        route(ADDON, BASE, HANDLE, {k: v[0] for k, v in query.items()})
        return
    if action == 'export':
        if not xbmcvfs.exists(DIAGNOSTIC):
            DIALOG.ok('Diagnostica', 'Abilita il salvataggio HTML nelle impostazioni e riprova la riproduzione.')
        else:
            folder = DIALOG.browse(0, 'Scegli cartella per risposta-player.txt', 'files', treatAsFolder=True)
            if folder:
                destination = folder.rstrip('/\\') + '/risposta-player.txt'
                ok = xbmcvfs.copy(DIAGNOSTIC, destination)
                DIALOG.ok('Diagnostica', 'Esportazione completata. Controlla il file prima di condividerlo: la rimozione dei dati sensibili è parziale.' if ok else 'Esportazione non riuscita.')
        xbmcplugin.endOfDirectory(HANDLE)
        return
    if action == 'settings':
        ADDON.openSettings()
        xbmcplugin.endOfDirectory(HANDLE)
        return
    if action == 'play':
        progress = None
        try:
            from providers import choices, create, LABELS
            sources = choices(ADDON.getSetting('source_mode') or '2', query.get('source', [''])[0])
            source = sources[0]
            if len(sources) > 1:
                selected = DIALOG.select('Scegli la fonte', [LABELS[s] for s in sources])
                if selected < 0:
                    xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
                    return
                source = sources[selected]
            progress = xbmcgui.DialogProgressBG()
            progress.create(LABELS[source], 'Avvio resolver')
            if os.path.isfile(DIAGNOSTIC):
                os.remove(DIAGNOSTIC)
            resolver = create(source, ADDON.getSetting('node_path') or 'node', lambda msg: progress.update(0, message=msg),
                              save_diagnostic if ADDON.getSettingBool('diagnostic') else None)
            url, headers, title = resolver.resolve(query['type'][0], query['id'][0], int(query.get('season', ['1'])[0]), int(query.get('episode', ['1'])[0]))
            item = xbmcgui.ListItem(label=title, path=url + '|' + urlencode(headers))
            item.setMimeType('application/vnd.apple.mpegurl')
            item.setContentLookup(False)
            subtitle_files = prepare_subtitles(resolver, progress)
            if subtitle_files:
                item.setSubtitles(subtitle_files)
            xbmcplugin.setResolvedUrl(HANDLE, True, item)
        except (ResolverError, KeyError, ValueError) as exc:
            xbmc.log('VidSrc prototype: risoluzione fallita', xbmc.LOGERROR)
            DIALOG.ok('VidSrc - prototipo', str(exc))
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except Exception:
            xbmc.log('VidSrc prototype: errore interno (dettagli URL omessi)', xbmc.LOGERROR)
            DIALOG.ok('VidSrc - prototipo', 'Errore interno: formato del servizio non previsto.')
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        finally:
            if progress is not None:
                progress.close()
        return
    if action == 'choose':
        kind = query.get('type', ['movie'])[0]
        media_id = DIALOG.input('ID IMDb (tt...) oppure TMDb numerico').strip()
        if media_id:
            values = {'action': 'play', 'type': kind, 'id': media_id}
            if kind == 'tv':
                season = DIALOG.input('Stagione', defaultt='1', type=xbmcgui.INPUT_NUMERIC)
                episode = DIALOG.input('Episodio', defaultt='1', type=xbmcgui.INPUT_NUMERIC)
                if not season or not episode:
                    xbmcplugin.endOfDirectory(HANDLE)
                    return
                values.update(season=season, episode=episode)
            item = xbmcgui.ListItem(label='Riproduci ' + media_id)
            item.setProperty('IsPlayable', 'true')
            xbmcplugin.addDirectoryItem(HANDLE, BASE + '?' + urlencode(values), item, False)
    else:
        for label, values in [
                ('Film · catalogo TMDb', {'action': 'cat_menu', 'type': 'movie'}),
                ('Serie TV · catalogo TMDb', {'action': 'cat_menu', 'type': 'tv'}),
                ('Cerca film e serie TV', {'action': 'cat_search', 'type': 'multi'}),
                ('Preferiti', {'action': 'cat_favorites'}),
                ('Ricerche recenti', {'action': 'cat_history'}),
                ('Film da ID manuale', {'action': 'choose', 'type': 'movie'}),
                ('Episodio da ID manuale', {'action': 'choose', 'type': 'tv'}),
                ('Impostazioni', {'action': 'settings'}),
                ('Test Node/WASM', {'action': 'wasm_test'}),
                ('Informazioni · TMDb', {'action': 'cat_about'}),
                ('Esporta diagnostica', {'action': 'export'})]:
            xbmcplugin.addDirectoryItem(HANDLE, BASE + '?' + urlencode(values), xbmcgui.ListItem(label=label), True)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


main()
