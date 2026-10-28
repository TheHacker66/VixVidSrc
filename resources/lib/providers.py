"""Provider selection, shared by manual playback and the TMDb catalog."""
from resolver import Resolver, ResolverError

LABELS = {'vidsrc': 'VidSrc', 'vixsrc': 'VixSrc'}


def choices(setting='2', override=''):
    if override:
        if override not in LABELS:
            raise ResolverError('Fonte non valida')
        return [override]
    if setting == '0':
        return ['vidsrc']
    if setting == '1':
        return ['vixsrc']
    return ['vixsrc', 'vidsrc']


def create(source, node='node', progress=None, diagnostic=None):
    if source == 'vidsrc':
        return Resolver(node, progress, diagnostic)
    if source == 'vixsrc':
        from vix_resolver import VixResolver
        return VixResolver(progress, diagnostic, audio_language='it')
    raise ResolverError('Fonte non valida')
