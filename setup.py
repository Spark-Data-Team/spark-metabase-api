import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="spark-metabase-api",
    version="0.3.0",
    author="Larry Page",
    author_email="tech@spark.do",
    description="A Python wrapper for the Metabase API developed by the ⭐️ Spark Tech team",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Spark-Data-Team/spark-metabase-api",
    packages=setuptools.find_packages(),
    install_requires=[
        "requests",
        # scripts/reorg_lib.py, importé en chaîne par 18 fichiers de tests.
        # Il était déclaré dans l'extra "iac", supprimé avec le bloc IaC : sur
        # une machine propre les 18 tests ne se collectaient plus.
        "PyYAML>=5.1",
    ],
    extras_require={"dev": ["pytest"]},
    # Outil interne : plus de publication PyPI, plus d'extras IaC/chatbot/Streamlit.
    # Installation attendue : pip install -e .
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
