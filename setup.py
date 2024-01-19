#!/usr/bin/env python
import setuptools

def readme():
    """ function: inport README.md for setup long description"""
    with open('README.md') as f:
        return f.read()

setuptools.setup(name='Splunk-HEC-AIO',
      python_requires='>3.5',
      version='2.1.1',
      description='This is a python class file for use with other python scripts to send events to a Splunk http event collector.',
      long_description=readme(),
      long_description_content_type="text/markdown",
      author='George (starcher) Starcher',
      author_email='george@georgestarcher.com',
      url='https://github.com/georgestarcher/splunk_hec_aio',
      py_modules=['splunk_http_event_collector'],
      keywords="splunk hec aio",
      license="MIT",
      packages=setuptools.find_packages(),
      install_requires=[
          'aiohttp',
          'aiohttp_retry'
      ],
     )
