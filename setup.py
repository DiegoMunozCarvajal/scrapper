from setuptools import setup

setup(
    entry_points={"scrapy": ["settings = src.scrapper.settings"]},
)
