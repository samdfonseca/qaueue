import os

from setuptools import setup, find_packages


if __name__ == '__main__':
    HERE = os.path.abspath(os.path.dirname(__file__))

    with open(os.path.join(HERE, 'README.txt')) as f:
        README = f.read()

    with open(os.path.join(HERE, 'requirements.txt')) as f:
        REQUIREMENTS = [s.strip().split(' ')[0] for s in f.readlines()]

    setup(name='qaueue',
          version='1.0',
          description='QAueue: /qaueue manages the items in the QA pipeline',
          long_description=README,
          install_requires=REQUIREMENTS,
          packages=['qaueue'],
          )
