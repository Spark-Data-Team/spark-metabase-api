import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="spark-metabase-api",
    version="0.1.4",
    author="Larry Page",
    author_email="tech@spark.do",
    description="A Python wrapper for the Metabase API developed by the ⭐️ Spark Tech team",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Spark-Data-Team/spark_metabase_api",
    packages=setuptools.find_packages(),
    install_requires=[
        "requests",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
