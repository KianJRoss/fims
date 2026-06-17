from app.api.v1.api import api_router
from app.api.v1.endpoints import inventory as inventory_endpoints
from app.api.v1.endpoints import scanner as scanner_endpoints


if not any(route.path.startswith("/inventory") for route in api_router.routes):
    api_router.include_router(inventory_endpoints.router, prefix="/inventory", tags=["inventory"])

if not any(route.path.startswith("/scanner") for route in api_router.routes):
    # Scanner broadcasts are additive and must not duplicate if this module is imported twice.
    api_router.include_router(scanner_endpoints.router, prefix="/scanner", tags=["scanner"])
