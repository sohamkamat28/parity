# Internal regression fixtures

These headless fixtures are used only by automated tests and the isolated browser acceptance script. They are not part of the application navigation, normal launcher or installation setup.

`fixture_site.py` supplies controlled HTTP pages, PDFs and reversible fault injection. It has no control-room UI, stored sessions or portal database. `runtime.py` injects an explicit fixture transport into disposable API/worker test processes. Normal application processes use the public-network fetcher; source settings cannot grant loopback access.
