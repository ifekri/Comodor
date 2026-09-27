# Service notes

The service is packaged by `pyproject.toml` and started with `python app.py`.

The listener port is the one declared in `config.DEFAULT_PORT`; `app.py` reads
it rather than repeating the number.
