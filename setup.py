from setuptools import setup, find_packages

setup(
	name='campy',
	version='2.0.1',
	packages=find_packages(),
	include_package_data=True,
	install_requires=[
					'imageio',
					'imageio-ffmpeg',
					'matplotlib',
					'numpy',
					'pypylon',
					'pyserial',
					'pyyaml',
					'scipy',
					'scikit-image',
					'PyQt5',
					],
	package_data={
		'campy.vendor': ['README.md'],
	},
	extras_require={
		'exe': ['pyinstaller'],
	},
	entry_points={
		"console_scripts": [
			"campy-acquire = campy.campy:Main",
			"campy-gui = campy.gui.app:main",
			"campy-evaluate = campy.utils.evaluate_session:main",
		]
	}
)
