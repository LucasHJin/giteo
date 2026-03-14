from setuptools import setup, find_packages

setup(
    name="giteo",
    version="0.1.0",
    description="Git for Video Editing — version control timeline metadata, not media files",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "google-generativeai",
        "rich",
    ],
    extras_require={
        "qt": ["PySide6"],
    },
    entry_points={
        "console_scripts": [
            "giteo=giteo.cli:main",
        ],
    },
)
