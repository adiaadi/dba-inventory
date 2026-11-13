from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web import templates

router = APIRouter(prefix='/schemas', tags=['schemas'])


@router.get('', response_class=HTMLResponse)
def schemas(request: Request, engine: str = '', database: str = ''):
    # Aggregated from the user-supplied ss snapshot on AML-PROD-DB02.
    # Counts are historical observations, not live health indicators.
    clients = [
        {'ip': '10.210.120.13', 'connections': 27},
        {'ip': '10.210.120.14', 'connections': 57},
        {'ip': '10.210.120.15', 'connections': 70},
        {'ip': '10.210.120.16', 'connections': 52},
    ]
    return templates.TemplateResponse(request, 'schemas.html', {
        'request': request, 'clients': clients,
        'engine': engine if engine in ('oracle', 'postgresql', 'sqlserver') else '',
        'selected': engine == 'postgresql' and database == 'aml',
    })
