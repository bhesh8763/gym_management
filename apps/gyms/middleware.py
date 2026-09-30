from .managers import tenant_context


class TenantContextMiddleware:
    """Clear request-local tenant state before and after each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_context.gym = None
        tenant_context.branch = None
        try:
            return self.get_response(request)
        finally:
            tenant_context.gym = None
            tenant_context.branch = None
