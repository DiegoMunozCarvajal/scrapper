# scrapper

Multi-site web scraper for Reddit, Quora, Hotmart, Mercado Libre, Amazon, and Instagram.

## Setup

```bash
pip install -e ".[dev]"
playwright install chromium
```

## Usage

```bash
python -m src.scrapper.main <site> <query> [--limit N] [--output results.json]

# Examples
python -m src.scrapper.main amazon "mechanical keyboard" --limit 20 -o amazon.json
python -m src.scrapper.main reddit "python tips" -n 15
python -m src.scrapper.main mercadolibre "laptop gamer" --no-headless
```

### Supported sites

| Site | Key | Type |
|------|-----|------|
| Amazon | `amazon` | Products |
| Mercado Libre | `mercadolibre` | Products |
| Hotmart | `hotmart` | Products |
| Reddit | `reddit` | Posts |
| Quora | `quora` | Posts |
| Instagram | `instagram` | Posts |

### Options

| Flag | Description |
|------|-------------|
| `--limit, -n` | Max results (default: 10) |
| `--output, -o` | Save results to JSON file |
| `--no-headless` | Show browser window |
| `--proxy` | Proxy URL (e.g. `http://user:pass@host:port`) |

## Programmatic usage

```python
from scrapper.scrapers import AmazonScraper

scraper = AmazonScraper(headless=True)
result = scraper.run_sync("laptop", limit=5)

for product in result.products:
    print(product.title, product.price)
```

## Tests

```bash
pytest tests/ -v
```
