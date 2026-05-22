from setuptools import setup

setup(
    name='harmonica-sequencer',
    version='1.0.0',
    description='半音阶12孔口琴步进扒谱器',
    py_modules=['harmonica_to_midi'],
    python_requires='>=3.8',
    install_requires=[
        'PySide6>=6.5',
        'numpy>=1.24',
        'pyaudio>=0.2',
        'music21>=8.0',
    ],
)