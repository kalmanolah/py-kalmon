#!/usr/bin/env python3
"""Setup module."""
from setuptools import setup, find_packages
import os


def read(fname):
    """Read and return the contents of a file."""
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


setup(
    name='kalmon',
    version='0.0.1',
    description='Controller for ESP8266 devices running nodemcu + Kalmon',
    long_description=read('README'),

    author='Kalman Olah',
    author_email='hello@kalmanolah.net',

    url='https://github.com/kalmanolah/py-kalmon',
    license='MIT',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'License :: OSI Approved :: MIT License',
    ],

    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'kalmon = kalmon:main',
        ],

        'kalmon.controllers': [
            'ws2812 = kalmon.controllers:WS2812Controller',
        ],
    },

    install_requires=[
        'paho-mqtt',
        'click'
    ],
)
