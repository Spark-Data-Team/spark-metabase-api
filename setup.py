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
    ],
    extras_require={
        "iac": ["PyYAML>=5.1"],
        "chatbot": ["anthropic>=0.40.0"],
        "streamlit": ["streamlit>=1.30", "PyYAML>=5.1", "anthropic>=0.40.0"],
    },
    entry_points={
        "console_scripts": [
            "spark-metabase=spark_metabase_api.iac:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
