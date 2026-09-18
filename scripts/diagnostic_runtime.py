import os, re

DEFAULT_TARGET='16015'
DEFAULT_COMMUNE_NAME='Angoulême'
DEFAULT_PANEL_PEERS='19031,47001,24322,40192,79191,86066,33243,17299,40088,24037,17415,16102,17306,47323,47157'

def _env(name, default):
    value=os.getenv(name)
    return value.strip() if value and value.strip() else default

def target():
    value=_env('DIAG_TERRITORY',DEFAULT_TARGET).upper()
    if not re.fullmatch(r'[0-9A-Z]{5}',value):
        raise RuntimeError(f'DIAG_TERRITORY invalide: {value!r}')
    return value

def commune_name():
    return _env('DIAG_COMMUNE_NAME',DEFAULT_COMMUNE_NAME)

def panel_peers():
    raw=_env('DIAG_PANEL_CODES',DEFAULT_PANEL_PEERS)
    codes=[x.strip().upper() for x in raw.split(',') if x.strip()]
    t=target()
    if any(not re.fullmatch(r'[0-9A-Z]{5}',c) for c in codes):
        raise RuntimeError(f'DIAG_PANEL_CODES invalide: {codes}')
    if t in codes:
        raise RuntimeError('DIAG_PANEL_CODES doit exclure la commune cible')
    if len(codes)!=15 or len(set(codes))!=15:
        raise RuntimeError(f'DIAG_PANEL_CODES doit contenir exactement 15 communes distinctes; reçu={len(codes)}')
    return codes

def department_code(code=None):
    c=(code or target()).upper()
    if c.startswith(('97','98')):
        return c[:3]
    if c.startswith(('2A','2B')):
        return c[:2]
    return c[:2]

def runtime_metadata():
    return {
        'territory_source':'env' if os.getenv('DIAG_TERRITORY') else 'transition_default',
        'commune_name_source':'env' if os.getenv('DIAG_COMMUNE_NAME') else 'transition_default',
        'panel_source':'env' if os.getenv('DIAG_PANEL_CODES') else 'transition_default',
    }
