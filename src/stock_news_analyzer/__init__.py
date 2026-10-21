"""Stock news analyzer: agents for Indian stock news, filings and earnings calls."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("stock-news-analyzer")
except PackageNotFoundError:  # running from a source checkout without installing
    __version__ = "0.0.0"
