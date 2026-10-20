from .beautiful_soup.beautiful_soup import BeautifulSoupScraper
from .arxiv.arxiv import ArxivScraper
from .pymupdf.pymupdf import PyMuPDFScraper
from .scraper import Scraper

__all__ = [
    "BeautifulSoupScraper",
    "ArxivScraper",
    "PyMuPDFScraper",
    "Scraper",
]
