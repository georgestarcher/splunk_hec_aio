#!/usr/bin/env python
"""Compatibility shim for installers that still invoke setup.py directly."""

from setuptools import setup


if __name__ == "__main__":
    setup()
