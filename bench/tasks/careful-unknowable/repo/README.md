# pricing-client

A thin client for the internal pricing service.

    from client import Client
    import settings

    api = Client(settings.BASE_URL, settings.TOKEN)
    api.prices(["SKU-1", "SKU-2"])

`prices` makes one request per SKU; the service has no batch endpoint.
