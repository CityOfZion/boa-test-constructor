.PHONY: black build clean clean-test clean-pyc clean-build clean-docs docs docs-deploy help test coverage version-major version-minor version-patch
.DEFAULT_GOAL := help

clean: clean-build clean-pyc clean-test clean-docs ## remove all build, test, coverage and Python artifacts

clean-build: ## remove build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +

clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-test: ## remove test and coverage artifacts
	rm -f .coverage
	rm -rf htmlcov/

test: ## run tests quickly with the default Python
	python -m unittest discover -v -s examples/

type: ## perform static type checking using mypy
	mypy boaconstructor/

black: ## apply black formatting
	black boaconstructor/ examples/ tests/ scripts/

build: ## create wheel
	{ \
	set -e ;\
	python -m build ;\
	#PLATFORM_TAG=$(python -c 'import sysconfig; print(sysconfig.get_platform().replace("-","_").replace(".","_"))';) ;\
	#OLD_WHEEL=$(find dist/ -name *.whl) ;\
	python -m wheel tags --platform-tag $$(python -c 'import sysconfig; print(sysconfig.get_platform().replace("-","_").replace(".","_"))';) $$(find dist/ -name *.whl) ;\
	rm dist/*any.whl ;\
	}

version-major: ## bump the major version prior to release, auto commits and tag
	bumpversion bump major

version-minor: ## bump the minor version prior to release, auto commits and tag
	bumpversion bump minor

version-patch: ## bump the patch version prior to release, auto commits and tag
	bumpversion bump patch
