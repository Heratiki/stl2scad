"""
Setup configuration for the STL to OpenSCAD converter.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="stl2scad",
    version="0.1.0",
    author="Herat",
    description="Convert STL files to OpenSCAD format with optimization and validation",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/herat/stl2scad",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Scientific/Engineering :: Computer Aided Design",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=[
        "numpy>=1.24.3",
        "numpy-stl>=3.1.2",
        "PyQt5>=5.15.11",
        "pyqtgraph>=0.13.3",
        "PyOpenGL>=3.1.7",
        "PyOpenGL-accelerate>=3.1.7",
        "typing_extensions>=4.12.2",
        "psutil>=5.9.0",
    ],
    extras_require={
        "parametric_phase1": [
            "trimesh>=4.0.0",
            "networkx>=3.0",
        ],
        "parametric_phase2": [
            "cgal>=6.0.1",
        ],
        "reporting": [
            "trimesh>=4.0.0",
            "networkx>=3.0",
            "pyglet>=1.5,<2",
            "matplotlib>=3.5.0",
            "pillow>=9.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "stl2scad=stl2scad.cli:main",
            "stl2scad-gui=stl2scad.__main__:main",
        ],
    },
)
