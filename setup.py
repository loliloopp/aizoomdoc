"""
Setup script для AIZoomDoc.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="aizoomdoc",
    version="1.0.0",
    author="AIZoomDoc Team",
    description="Анализ строительной документации с помощью LLM",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.12,<3.14",  # Рекомендуется Python 3.12.x для лучшей совместимости
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "aizoomdoc=src.main:main",
        ],
    },
)

