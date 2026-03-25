from setuptools import setup, find_packages

# Setup configuration for the eye-capture package
setup(
    name="eye-capture",
    version="0.2.2",
    description="AI-native vision capture tool for CUA workflows (derivative of nullvoider07/the-eyes, GPLv3)",
    author="Agent-eye fork contributors",
    license="GPL-3.0-or-later",
    packages=find_packages(),
    install_requires=[
        "click>=8.1.7",
        "pyyaml>=6.0.1",
        "requests>=2.31.0",
    ],
    entry_points={
        'console_scripts': [
            'eye=eye.cli:main',
        ],
    },
    python_requires=">=3.11",
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
    ],
)