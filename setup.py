# -*- coding: utf-8 -*-
"""Instalación del paquete redes_engine."""

from setuptools import find_packages, setup


with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()


setup(
    name="redes_engine",
    version="0.1.0",
    description=(
        "Motor de cálculo de redes eléctricas de distribución (MT+BT+VE+BESS) "
        "con análisis 8760h, host capacity y reportes ejecutivos."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Redes Engine Contributors",
    license="MIT",
    url="https://github.com/redes-engine/redes-engine",
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    package_data={
        "redes_engine.catalogs": ["data/*.json"],
        "redes_engine.api": ["static/*.html", "static/*.js", "static/*.css"],
    },
    python_requires=">=3.9",
    install_requires=[
        # núcleo: sin deps obligatorias (graph, network, persistence)
    ],
    extras_require={
        # Capacidades incrementales
        "opendss": ["opendssdirect.py>=0.7,<1.0"],
        "milp":    ["pulp>=2.7,<4.0"],
        "gis":     ["shapely>=2.0,<3.0"],
        "api": [
            "fastapi>=0.110,<1.0",
            "uvicorn[standard]>=0.27,<1.0",
            "pydantic>=2.0,<3.0",
            "python-multipart>=0.0.7",
        ],
        "reports": [
            "reportlab>=4.0,<5.0",
            "python-docx>=1.0,<2.0",
            "matplotlib>=3.7,<4.0",
        ],
        # Bundle completo recomendado para deploy
        "all": [
            "opendssdirect.py>=0.7,<1.0",
            "pulp>=2.7,<4.0",
            "shapely>=2.0,<3.0",
            "fastapi>=0.110,<1.0",
            "uvicorn[standard]>=0.27,<1.0",
            "pydantic>=2.0,<3.0",
            "python-multipart>=0.0.7",
            "reportlab>=4.0,<5.0",
            "python-docx>=1.0,<2.0",
            "matplotlib>=3.7,<4.0",
        ],
        "dev": [
            "pytest>=7.4,<9.0",
            "pytest-cov>=4.1,<6.0",
            "ruff>=0.1,<1.0",
            "pyogrio>=0.7,<1.0",   # importador shapefile/gpkg
        ],
    },
    entry_points={
        "console_scripts": [
            "redes-engine-api=redes_engine.api.main:_run_uvicorn_cli",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering",
        "Topic :: Scientific/Engineering :: GIS",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Framework :: FastAPI",
    ],
    keywords=(
        "power-flow distribution-network electric-vehicle "
        "battery-storage opendss qgis ecuador arcernnr"
    ),
)
