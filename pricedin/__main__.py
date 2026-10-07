"""Start the local web app: `uv run python -m pricedin`."""

from pricedin import config
from pricedin.web.app import app


def main() -> None:
    app.run(host="127.0.0.1", port=config.port())


if __name__ == "__main__":
    main()
