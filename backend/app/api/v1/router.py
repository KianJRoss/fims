from app.api.v1.api import api_router
from app.api.v1.endpoints import inventory as inventory_endpoints


if not any(route.path.startswith("/inventory") for route in api_router.routes):
    api_router.include_router(inventory_endpoints.router, prefix="/inventory", tags=["inventory"])
